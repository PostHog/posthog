import pytest
from typing import cast
from autoevals.llm import LLMClassifier
from braintrust import EvalCase

from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation
from posthog.schema import AssistantHogQLQuery, HumanMessage, VisualizationMessage

from .conftest import MaxEval


class SQLQueryCorrectness(LLMClassifier):
    """Evaluate generated SQL query correctness against expected query."""

    def __init__(self, **kwargs):
        super().__init__(
            name="sql_query_correctness",
            prompt_template="""You will be given a user question, a SQL query plan, the expected SQL query, and the actual generated SQL query. Evaluate if the actual query correctly implements the plan and would answer the user's question effectively.

User question: {{input}}
SQL plan: {{context}}
Expected SQL query: {{expected}}
Actual SQL query: {{output}}

Evaluation steps:
- Check if the query includes the correct tables and fields mentioned in the plan.
- Verify that the filtering conditions match the requirements in the plan and user's question.
- Ensure that the right aggregations (COUNT, SUM, AVG, etc.) are implemented as specified in the plan.
- Check that the query is syntactically correct and follows proper SQL conventions.
- Be flexible in your evaluation, as there are many ways to write a correct SQL query that answers the same question.

How would you rate the correctness of the actual SQL query? Choose one:
- perfect: The query fully implements the plan and would correctly answer the user's question.
- good: The query implements most of the plan with minor differences that don't affect correctness.
- partial: The query implements some aspects of the plan but has issues that might affect results.
- incorrect: The query fails to implement the plan or would not correctly answer the question.""",
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "incorrect": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


@pytest.fixture
def call_node(demo_org_team_user):
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.SQL_GENERATOR)
        .add_sql_generator(AssistantNodeName.END)
        .compile()
    )

    def callable(query_and_plan):
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        query, plan = query_and_plan.split("|||")
        state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)], plan=plan),
            {"configurable": {"thread_id": conversation.id}},
        )
        message = cast(VisualizationMessage, AssistantState.model_validate(state).messages[-1])
        answer = message.answer
        assert isinstance(answer, AssistantHogQLQuery), "Expected AssistantHogQLQuery"
        return answer

    return callable


@pytest.mark.django_db
def eval_sql_generator(call_node):
    MaxEval(
        experiment_name="sql_generator",
        task=call_node,
        scores=[SQLQueryCorrectness()],
        data=[
            # Test basic count over time
            EvalCase(
                input="What's our $pageview count over time|||Logic:\n- Count the occurrences of the `$pageview` event.\n- Group the counts by a time dimension, such as day, week, or month, depending on the granularity required.\n\nSources:\n- `$pageview` event\n    - Use the event to count occurrences and group by timestamp to analyze the count over time.",
                expected="""
SELECT toStartOfDay(timestamp) AS day, count() AS pageview_count
FROM events
WHERE event = '$pageview'
GROUP BY day
ORDER BY day
""",
                context="Logic:\n- Count the occurrences of the `$pageview` event.\n- Group the counts by a time dimension, such as day, week, or month, depending on the granularity required.\n\nSources:\n- `$pageview` event\n    - Use the event to count occurrences and group by timestamp to analyze the count over time.",
            ),
            # Test filtering with date range
            EvalCase(
                input="How many file downloads did we have in the last 5 days|||Logic:\n- Count the number of occurrences of the 'downloaded_file' event within the last 5 days.\n\nSources:\n- Event: downloaded_file\n    - Use this event to count the number of file downloads. Filter the event data to include only those that occurred in the last 5 days.",
                expected="""
SELECT toStartOfDay(timestamp) AS day, count() AS pageview_count
FROM events
WHERE event = 'downloaded_file' AND timestamp >= toDate(now()) - toIntervalDay(5)
GROUP BY day
ORDER BY day
""",
                context="Logic:\n- Count the number of occurrences of the 'downloaded_file' event within the last 5 days.\n\nSources:\n- Event: downloaded_file\n    - Use this event to count the number of file downloads. Filter the event data to include only those that occurred in the last 5 days.",
            ),
        ],
    )
