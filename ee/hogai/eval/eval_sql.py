from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.graph.sql.toolkit import SQL_SCHEMA
from ee.models.assistant import Conversation
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.errors import BaseHogQLError
from posthog.models.team.team import Team
from .conftest import MaxEval
import pytest
from braintrust import EvalCase, Score
from braintrust_core.score import Scorer
from asgiref.sync import sync_to_async

from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.context import HogQLContext
from posthog.schema import AssistantHogQLQuery, HumanMessage, NodeKind, VisualizationMessage
from .scorers import PlanCorrectness, QueryAndPlanAlignment, TimeRangeRelevancy, PlanAndQueryOutput


class SQLSyntaxCorrectness(Scorer):
    """Evaluate if the generated SQL query has correct syntax."""

    def _name(self):
        return "sql_syntax_correctness"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        query = output["query"]
        if not query or not hasattr(query, "query") or not query.query:
            return Score(
                name=self._name(), score=None, metadata={"reason": "No SQL query to verify, skipping evaluation"}
            )
        team = await Team.objects.alatest("created_at")
        hogql_context = HogQLContext(team=team, database=await sync_to_async(create_hogql_database)(team=team))
        try:
            # Try to parse and print the query
            print_ast(parse_select(query.query), context=hogql_context, dialect="clickhouse")
        except BaseHogQLError as e:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"SQL syntax error: {str(e)}"})
        else:
            return Score(name=self._name(), score=1.0)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        query = output["query"]
        if not query or not hasattr(query, "query") or not query.query:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No SQL query"})
        team = Team.objects.latest("created_at")
        hogql_context = HogQLContext(team=team, database=create_hogql_database(team=team))
        try:
            # Try to parse and print the query
            print_ast(parse_select(query.query), context=hogql_context, dialect="clickhouse")
        except BaseHogQLError as e:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"SQL syntax error: {str(e)}"})
        else:
            return Score(name=self._name(), score=1.0)


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

    def callable(query: str) -> PlanAndQueryOutput:
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
            PlanCorrectness(
                query_kind=NodeKind.HOG_QL_QUERY,
                evaluation_criteria="""
1. A plan must define a clear intent for the SQL query to be generated, including which tables/entities are being queried, what filters are being applied, and what is being returned.
2. Compare tables, entities, filters, aggregations, group by clauses, and any other SQL elements mentioned in the 'expected plan' and 'output plan'.
3. Check if the outlined query in 'output plan' can answer the user's question according to the 'expected plan'.
4. If 'expected plan' mentions specific joins, aggregations, or window functions, check if 'output plan' includes similar operations, and heavily penalize if they are not present or significantly different.
5. If 'expected plan' mentions specific time range filters, check if 'output plan' includes similar time range filters, and heavily penalize if they are not present or different.
6. Heavily penalize if the 'output plan' contains any excessive operations not present in the 'expected plan' that would change the meaning of the query.
""",
            ),
            QueryAndPlanAlignment(
                query_kind=NodeKind.HOG_QL_QUERY,
                json_schema=SQL_SCHEMA,
                evaluation_criteria="""
Most importantly, evaluate the `query` field, containing the generated HogQL.
HogQL is simply an SQL flavor derived from ClickHouse SQL, with some PostHog-specific syntax.
The most important piece of PostHog-specific syntax is easy access to JSON properties, which is done using `.`, like so: `SELECT properties.$browser FROM events`.
It's also possible to access nested tables, such the `events` table has a `person` field that actually points to the related row in the `persons` table (the concrete field on `events` is `person_id`).
This means the following syntax is valid and useful too: `SELECT person.properties.foo.bar FROM events`.
The other standard table is `sessions`, which contains data of the session the event belongs to (though events can be outside of a session as well).

Important points:
- The generated query should use `person_id` or `person.id` for any aggregation on unique users, should NOT be using `distinct_id` or properties.
- $identify generally should not be used, as they're mostly for internal purposes, and not useful for insights. A more useful event (or no event filter) should be used.
- For session duration, `session.$session_duration` should be used instead of things like `properties.$session_duration`.""",
            ),
            SQLSyntaxCorrectness(),
            TimeRangeRelevancy(query_kind=NodeKind.HOG_QL_QUERY),
        ],
        data=[
            EvalCase(
                input="Count pageviews by browser",
                expected=PlanAndQueryOutput(
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
                expected=PlanAndQueryOutput(
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
                expected=PlanAndQueryOutput(
                    plan="""
Query to calculate average session duration by day of week:
- FROM: sessions table (or equivalent calculation)
- SELECT: day_of_week(timestamp), avg(session_duration)
- GROUP BY: day_of_week
- ORDER BY: day_of_week
""",
                    query=AssistantHogQLQuery(
                        query="""
SELECT toDayOfWeek(timestamp) as day_of_week,
       avg(session.$session_duration) as avg_session_duration
FROM events
GROUP BY day_of_week
ORDER BY day_of_week
"""
                    ),
                ),
            ),
            EvalCase(
                input="What percentage of users who visited the pricing page made a purchase in this month?",
                expected=PlanAndQueryOutput(
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
                expected=PlanAndQueryOutput(
                    plan="""
Query to count users who completed the full onboarding sequence:
- Use window functions to assign sequence numbers to each step
- Check that users have all three steps in the correct order
- Count distinct users who completed all steps
""",
                    query=AssistantHogQLQuery(
                        query="""
WITH occurences AS (
    SELECT
        person_id,
        event,
        timestamp,
        ROW_NUMBER() OVER (PARTITION BY person_id, event ORDER BY timestamp) as occurrence
    FROM events
    WHERE event IN ('viewed_welcome_page', 'created_profile', 'completed_tutorial')
),
user_funnel AS (
    SELECT
        person_id,
        maxIf(timestamp, event = 'viewed_welcome_page') as welcome_time,
        maxIf(timestamp, event = 'created_profile') as profile_time,
        maxIf(timestamp, event = 'completed_tutorial') as tutorial_time
    FROM occurences
    WHERE occurrence = 1
    GROUP BY person_id
    HAVING count(distinct event) = 3
)
SELECT count(*) as users_completed_onboarding
FROM user_funnel
WHERE welcome_time < profile_time AND profile_time < tutorial_time
"""
                    ),
                ),
            ),
            EvalCase(
                input="How many users completed the onboarding flow (viewed welcome page, created profile, and completed tutorial) regardless of sequence?",
                expected=PlanAndQueryOutput(
                    plan="""
Query to count users who completed the full onboarding sequence:
- Aggregate occurences of each event per user
- Count users who have all three events
""",
                    query=AssistantHogQLQuery(
                        query="""
WITH occurences AS (
    SELECT person_id, event
    FROM events
    WHERE event IN ('viewed_welcome_page', 'created_profile', 'completed_tutorial')
),
user_funnel AS (
    SELECT
        person_id,
        count(distinct event) as event_count
    FROM occurences
    GROUP BY person_id
)
SELECT count(*) as users_completed_onboarding
FROM user_funnel
WHERE event_count = 3
"""
                    ),
                ),
            ),
        ],
    )
