import pytest
from autoevals.llm import LLMClassifier
from braintrust import EvalCase
from ee.models.assistant import Conversation

from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage

from .conftest import MaxEval


class SQLPlanCorrectness(LLMClassifier):
    """Evaluate SQL query plan correctness against expected plan."""

    def __init__(self, **kwargs):
        super().__init__(
            name="sql_plan_correctness",
            prompt_template="""You will be given expected and actual generated SQL query plans to answer a user's question. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan.

Evaluation steps:
- Check if the plan includes the correct tables and fields needed to answer the question.
- Verify that the proposed filtering matches the requirements in the user's question.
- Ensure that the right aggregations are mentioned (COUNT, SUM, AVG, etc.) to answer the question.
- Be flexible in your evaluation, as there are many ways to write a correct SQL query that answers the same question.

User question: {{input}}
Expected SQL plan: {{expected}}
Actual SQL plan: {{output}}

How would you rate the accuracy of the actual SQL plan compared to the expected plan? Choose one:
- perfect: The actual plan fully matches the expected plan in terms of tables, fields, filtering, and aggregations.
- good: The actual plan uses the correct tables and fields but might have minor differences in approach that don't affect correctness.
- partial: The actual plan has some correct elements but is missing key components or uses incorrect approaches.
- incorrect: The actual plan is completely wrong or would not answer the user's question correctly.""",
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
        .add_edge(AssistantNodeName.START, AssistantNodeName.SQL_PLANNER)
        .add_sql_planner(AssistantNodeName.END)
        .compile()
    )

    def callable(query: str):
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        raw_state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)]),
            {"configurable": {"thread_id": conversation.id}},
        )
        state = AssistantState.model_validate(raw_state)
        return state.plan or "NO PLAN WAS GENERATED"

    return callable


@pytest.mark.django_db
def eval_sql_planner(call_node):
    MaxEval(
        experiment_name="sql_planner",
        task=call_node,
        scores=[SQLPlanCorrectness()],
        data=[
            # Test basic count over time
            EvalCase(
                input="What's our $pageview count over time",
                expected="""
Logic:
- Count the occurrences of the `$pageview` event.
- Group the counts by a time dimension, such as day, week, or month, depending on the granularity required.

Sources:
- `$pageview` event
    - Use the event to count occurrences and group by timestamp to analyze the count over time.""".strip(),
            ),
            # Test filtering with date range
            EvalCase(
                input="How many file downloads did we have in the last 5 days",
                expected="""
Logic:
- Count the number of occurrences of the 'downloaded_file' event within the last 5 days.

Sources:
- Event: downloaded_file
    - Use this event to count the number of file downloads. Filter the event data to include only those that occurred in the last 5 days.""".strip(),
            ),
        ],
    )
