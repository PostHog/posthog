import json
from typing import TypedDict
from ee.hogai.graph import InsightsAssistantGraph

# Replace import with direct definition
# from ee.hogai.graph.sql.toolkit import HOGQL_SCHEMA
from ee.models.assistant import Conversation
from .conftest import MaxEval
import pytest
from braintrust import EvalCase, Score
from autoevals.llm import LLMClassifier
from braintrust_core.score import Scorer

from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import (
    AssistantHogQLQuery,
    HumanMessage,
    VisualizationMessage,
)
from .scorers import TimeRangeRelevancy

# Define an empty schema as placeholder
HOGQL_SCHEMA = {
    "description": "HogQL query schema for PostHog",
    "properties": {"query": {"type": "string", "description": "SQL query using HogQL dialect"}},
}


class SQLPlanCorrectness(LLMClassifier):
    """Evaluate if the generated plan correctly answers the user's question."""

    def __init__(self, **kwargs):
        super().__init__(
            name="plan_correctness",
            prompt_template="""You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a SQL insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about SQL insights.

User question:
<user_question>
{{input}}
</user_question>

Expected plan:
<expected_plan>
{{expected.plan}}
</expected_plan>

Actual generated plan:
<output_plan>
{{output.plan}}
</output_plan>

Evaluation criteria:
1. A plan must define a clear intent for the SQL query to be generated, including which tables/entities are being queried, what filters are being applied, and what is being returned.
2. Compare tables, entities, filters, aggregations, group by clauses, and any other SQL elements mentioned in the 'expected plan' and 'output plan'.
3. Check if the outlined query in 'output plan' can answer the user's question according to the 'expected plan'.
4. If 'expected plan' mentions specific joins, aggregations, or window functions, check if 'output plan' includes similar operations, and heavily penalize if they are not present or significantly different.
5. If 'expected plan' mentions specific time range filters, check if 'output plan' includes similar time range filters, and heavily penalize if they are not present or different.
6. Heavily penalize if the 'output plan' contains any excessive operations not present in the 'expected plan' that would change the meaning of the query.

How would you rate the correctness of the plan? Choose one:
- perfect: The plan fully matches the expected plan and addresses the user question.
- near_perfect: The plan mostly matches the expected plan with at most one immaterial detail missed from the user question.
- slightly_off: The plan mostly matches the expected plan with minor discrepancies.
- somewhat_misaligned: The plan has some correct elements but misses key aspects of the expected plan or question.
- strongly_misaligned: The plan does not match the expected plan or fails to address the user question.
- useless: The plan is incomprehensible.""",
            choice_scores={
                "perfect": 1.0,
                "near_perfect": 0.9,
                "slightly_off": 0.75,
                "somewhat_misaligned": 0.5,
                "strongly_misaligned": 0.25,
                "useless": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


class SQLQueryAndPlanAlignment(LLMClassifier):
    """Evaluate if the generated SQL query aligns with the plan generated in the previous step."""

    def __init__(self, **kwargs):
        super().__init__(
            name="query_and_plan_alignment",
            prompt_template="""Evaluate if the generated SQL query aligns with the query plan.

<input_vs_output>

Original user question:
<user_question>
{{input}}
</user_question>

Generated query plan:
<plan>
{{output.plan}}
</plan>

Actual generated query that should be aligned with the plan:
<output_query>
{{output.query}}
</output_query>

</input_vs_output>

Use knowledge of the HogQL Query schema, especially included descriptions:
<hogql_schema>
{{hogql_schema}}
</hogql_schema>

How would you rate the alignment of the generated query with the plan? Choose one:
- perfect: The generated query fully matches the plan.
- near_perfect: The generated query matches the plan with at most one immaterial detail missed from the user question.
- slightly_off: The generated query mostly matches the plan, with minor discrepancies that may slightly change the meaning of the query.
- somewhat_misaligned: The generated query has some correct elements, but misses key aspects of the plan.
- strongly_misaligned: The generated query does not match the plan and fails to address the user question.
- useless: The generated query is basically incomprehensible.
""",
            choice_scores={
                "perfect": 1.0,
                "near_perfect": 0.9,
                "slightly_off": 0.75,
                "somewhat_misaligned": 0.5,
                "strongly_misaligned": 0.25,
                "useless": 0.0,
            },
            model="gpt-4.1",
            hogql_schema=json.dumps(HOGQL_SCHEMA),
            **kwargs,
        )


class SQLSyntaxCorrectness(Scorer):
    """Evaluate if the generated SQL query has correct syntax."""

    def _name(self):
        return "sql_syntax_correctness"

    def _run_eval_sync(self, output, expected=None, **kwargs):
        query = output["query"]
        if not query or not hasattr(query, "query") or not query.query:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No SQL query"})

        try:
            from posthog.hogql.parser import parse_select
            from posthog.hogql.printer import print_ast
            from posthog.hogql.context import HogQLContext

            # Create a basic HogQL context
            hogql_context = HogQLContext(team_id=1)  # team_id doesn't matter for syntax validation

            # Try to parse and print the query
            ast = parse_select(query.query)
            print_ast(ast, context=hogql_context, dialect="clickhouse")

            # If we get here, the query is syntactically valid
            return Score(name=self._name(), score=1.0)
        except Exception as e:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"SQL syntax error: {str(e)}"})


class CallNodeOutput(TypedDict):
    plan: str | None
    query: AssistantHogQLQuery | None


@pytest.fixture
def call_node(demo_org_team_user):
    # This graph structure will first get a plan, then generate the SQL query.
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.SQL_PLANNER)
        .add_sql_planner(next_node=AssistantNodeName.SQL_GENERATOR)  # Planner output goes to generator
        .add_sql_generator(AssistantNodeName.END)  # Generator output is the final output
        .compile()
    )

    def callable(query: str) -> CallNodeOutput:
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        # Initial state for the graph
        initial_state = AssistantState(
            messages=[HumanMessage(content=f"Answer this question: {query}")],
            root_tool_insight_plan=query,  # User query is the initial plan for the planner
            root_tool_call_id="eval_test_sql",
            root_tool_insight_type="sql",
        )

        # Invoke the graph. The state will be updated through planner and then generator.
        final_state_raw = graph.invoke(
            initial_state,
            {"configurable": {"thread_id": conversation.id}},
        )
        final_state = AssistantState.model_validate(final_state_raw)

        if not final_state.messages or not isinstance(final_state.messages[-1], VisualizationMessage):
            return {"plan": None, "query": None}

        # Ensure the answer is of the expected type for SQL eval
        answer = final_state.messages[-1].answer
        if not isinstance(answer, AssistantHogQLQuery):
            # This case should ideally not happen if the graph is configured correctly for SQL
            return {"plan": final_state.messages[-1].plan, "query": None}

        return {"plan": final_state.messages[-1].plan, "query": answer}

    return callable


@pytest.mark.django_db
def eval_sql(call_node):
    MaxEval(
        experiment_name="sql",
        task=call_node,
        scores=[
            SQLPlanCorrectness(),
            SQLQueryAndPlanAlignment(),
            SQLSyntaxCorrectness(),
            TimeRangeRelevancy(query_type="SQL"),
        ],
        data=[
            EvalCase(
                input="Count pageviews by browser",
                expected=CallNodeOutput(
                    plan="""
Query to count pageviews grouped by browser:
- FROM: events table
- WHERE: event = '$pageview'
- GROUP BY: properties.$browser
- SELECT: properties.$browser, count(*) as pageview_count
- ORDER BY: pageview_count DESC
""",
                    query=AssistantHogQLQuery(
                        query="""
SELECT properties.$browser as browser, count(*) as pageview_count
FROM events
WHERE event = '$pageview'
GROUP BY browser
ORDER BY pageview_count DESC
LIMIT 100
"""
                    ),
                ),
            ),
            EvalCase(
                input="What are the top 10 countries by number of users in the last 7 days?",
                expected=CallNodeOutput(
                    plan="""
Query to find the top 10 countries by number of users in the last 7 days:
- FROM: events table
- WHERE: timestamp >= now() - interval 7 day
- GROUP BY: properties.$geoip_country_name
- SELECT: properties.$geoip_country_name, count(distinct person_id) as user_count
- ORDER BY: user_count DESC
- LIMIT: 10
""",
                    query=AssistantHogQLQuery(
                        query="""
SELECT properties.$geoip_country_name as country, count(distinct person_id) as user_count
FROM events
WHERE timestamp >= now() - interval 7 day
GROUP BY country
ORDER BY user_count DESC
LIMIT 10
"""
                    ),
                ),
            ),
            EvalCase(
                input="Show me the average session duration by day of week",
                expected=CallNodeOutput(
                    plan="""
Query to calculate average session duration by day of week:
- FROM: sessions table (or equivalent calculation)
- SELECT: day_of_week(timestamp), avg(session_duration)
- GROUP BY: day_of_week
- ORDER BY: day_of_week
""",
                    query=AssistantHogQLQuery(
                        query="""
SELECT dayOfWeek(timestamp) as day_of_week,
       avg(properties.$session_duration) as avg_session_duration
FROM events
WHERE properties.$session_duration is not null
GROUP BY day_of_week
ORDER BY day_of_week
"""
                    ),
                ),
            ),
            EvalCase(
                input="What percentage of users who visited the pricing page made a purchase in this month?",
                expected=CallNodeOutput(
                    plan="""
Query to calculate the percentage of users who visited the pricing page and also made a purchase this month:
- Subquery 1: Find distinct users who visited pricing page this month
- Subquery 2: Find distinct users who made a purchase this month
- Calculate: (Users who did both) / (Users who visited pricing page) * 100
- Time filter: date_trunc('month', timestamp) = date_trunc('month', now())
""",
                    query=AssistantHogQLQuery(
                        query="""
WITH pricing_visitors AS (
    SELECT distinct person_id
    FROM events
    WHERE event = 'viewed_pricing_page'
    AND date_trunc('month', timestamp) = date_trunc('month', now())
),
purchasers AS (
    SELECT distinct person_id
    FROM events
    WHERE event = 'purchase'
    AND date_trunc('month', timestamp) = date_trunc('month', now())
)

SELECT
    count(DISTINCT pv.person_id) AS pricing_visitors_count,
    count(DISTINCT p.person_id) AS purchasers_count,
    (count(DISTINCT p.person_id) * 100.0 / nullIf(count(DISTINCT pv.person_id), 0)) AS conversion_percentage
FROM pricing_visitors pv
LEFT JOIN purchasers p ON pv.person_id = p.person_id
"""
                    ),
                ),
            ),
            EvalCase(
                input="How many users completed the onboarding flow (viewed welcome page, created profile, and completed tutorial) in sequence?",
                expected=CallNodeOutput(
                    plan="""
Query to count users who completed the full onboarding sequence:
- Use window functions to assign sequence numbers to each step
- Check that users have all three steps in the correct order
- Count distinct users who completed all steps
""",
                    query=AssistantHogQLQuery(
                        query="""
WITH onboarding_steps AS (
    SELECT
        person_id,
        event,
        timestamp,
        CASE
            WHEN event = 'viewed_welcome_page' THEN 1
            WHEN event = 'created_profile' THEN 2
            WHEN event = 'completed_tutorial' THEN 3
        END AS step_number,
        ROW_NUMBER() OVER (PARTITION BY person_id, CASE
            WHEN event = 'viewed_welcome_page' THEN 1
            WHEN event = 'created_profile' THEN 2
            WHEN event = 'completed_tutorial' THEN 3
        END ORDER BY timestamp) AS step_occurrence
    FROM events
    WHERE event IN ('viewed_welcome_page', 'created_profile', 'completed_tutorial')
),
user_steps AS (
    SELECT
        person_id,
        array_agg(step_number ORDER BY timestamp) AS steps_completed
    FROM onboarding_steps
    WHERE step_occurrence = 1
    GROUP BY person_id
)

SELECT count(DISTINCT person_id) AS users_completed_onboarding
FROM user_steps
WHERE steps_completed = [1, 2, 3]
"""
                    ),
                ),
            ),
        ],
    )
