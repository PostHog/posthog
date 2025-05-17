import pytest
from typing import cast
from braintrust import EvalCase, Score
from autoevals.llm import LLMClassifier
from autoevals.value import ExactMatch

from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage, VisualizationMessage

from .conftest import MaxEval


class TrendsGeneratorCorrectness(LLMClassifier):
    """Evaluate trends generator output correctness."""

    def __init__(self, **kwargs):
        super().__init__(
            name="trends_generator_correctness",
            prompt_template="""Evaluate if the generated trends query correctly implements the plan and would answer the user's question effectively.

User question: {{input}}
Trends plan: {{context}}
Generated trends query: {{output}}

Evaluation criteria:
1. The generated query should use the events specified in the plan
2. Math operations (total, unique users, etc.) should match what's in the plan
3. Property filters should be implemented correctly, with appropriate operators (contains instead of equals for text)
4. Breakdowns should be implemented as specified in the plan
5. Formulas should be implemented as specified in the plan
6. The display type should be appropriate for the data being visualized (line graph for time series, etc.)
7. Time periods and intervals should match what's specified in the plan

How would you rate the correctness of the generated trends query? Choose one:
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


class ContainsInsteadOfEquals(ExactMatch):
    """Check if the generator replaced 'equals' with 'contains' for text searches."""

    def _run_evaluation(self, output, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0)

        json_output = output.model_dump_json(exclude_none=True)
        if "exact" in json_output:
            return Score(name=self._name(), score=0.0, comment="Used 'exact' instead of 'contains'")

        # Check if 'icontains' is used for text properties
        if "icontains" in json_output:
            # For case-insensitive searching, check if the value is lowercase
            is_lowercase = False
            if kwargs.get("expected"):
                search_term = kwargs["expected"]
                if search_term.lower() in json_output and search_term not in json_output:
                    is_lowercase = True

            return Score(
                name=self._name(),
                score=1.0 if is_lowercase else 0.5,
                comment="Uses 'icontains' but case handling is " + ("correct" if is_lowercase else "incorrect"),
            )

        return Score(name=self._name(), score=0.5, comment="No text search operators found")


class UseAppropriateDisplayType(ExactMatch):
    """Check if the generator uses an appropriate display type for the data."""

    def _run_evaluation(self, output, expected, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0)

        if not hasattr(output, "trendsFilter") or not hasattr(output.trendsFilter, "display"):
            return Score(name=self._name(), score=0.0, comment="No display type specified")

        display_type = output.trendsFilter.display

        # Time series data should use line graph
        if expected == "line":
            return Score(
                name=self._name(),
                score=1.0 if "LineGraph" in display_type else 0.0,
                comment=f"Expected line graph, got {display_type}",
            )

        # Multiple series that should be compared should use bar chart
        if expected == "bar":
            return Score(
                name=self._name(),
                score=1.0 if "ActionsBar" in display_type else 0.0,
                comment=f"Expected bar chart, got {display_type}",
            )

        # Table data should use table
        if expected == "table":
            return Score(
                name=self._name(),
                score=1.0 if "ActionsTable" in display_type else 0.0,
                comment=f"Expected table, got {display_type}",
            )

        return Score(name=self._name(), score=0.5, comment="Couldn't evaluate display type")


class TimeIntervalCorrectness(ExactMatch):
    """Check if the generator sets the correct time interval."""

    def _run_evaluation(self, output, expected, **kwargs):
        if not output or not expected:
            return Score(name=self._name(), score=0.0)

        if not hasattr(output, "interval"):
            return Score(name=self._name(), score=0.0, comment="No interval specified")

        return Score(
            name=self._name(),
            score=1.0 if output.interval == expected else 0.0,
            comment=f"Expected interval '{expected}', got '{output.interval}'",
        )


@pytest.fixture
def call_node(demo_org_team_user):
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_GENERATOR)
        .add_trends_generator(AssistantNodeName.END)
        .compile()
    )

    def callable(query_and_plan):
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        query, plan = query_and_plan.split("|||")
        state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)], plan=plan),
            {"configurable": {"thread_id": conversation.id}},
        )
        return cast(VisualizationMessage, AssistantState.model_validate(state).messages[-1]).answer

    return callable


@pytest.mark.django_db
def eval_trends_generator(call_node):
    MaxEval(
        experiment_name="trends_generator",
        task=call_node,
        scores=[
            TrendsGeneratorCorrectness(),
            ContainsInsteadOfEquals(),
            UseAppropriateDisplayType(),
            TimeIntervalCorrectness(),
        ],
        data=[
            # Test replacing equals with contains
            EvalCase(
                input="what is pageview trend for users with name John?|||Events:\n    - $pageview\n        - math operation: total count\n        - property filter 1\n            - person\n            - name\n            - equals\n            - John",
                expected="John",
            ),
            # Test line graph
            EvalCase(
                input="How often do users download files?|||Events:\n    - downloaded_file\n        - math operation: total count\n    - downloaded_file\n        - math operation: median count per user",
                expected="line",
            ),
            # Test time interval - years
            EvalCase(
                input="$pageview trends for the last five years|||Series:\n    - event: $pageview\n        - math operation: total count\n\n    Time period: the last five years\n    Time interval: month",
                expected="month",
            ),
            # Test time interval - days
            EvalCase(
                input="$pageview trends for the last 80 days|||Series:\n    - event: $pageview\n        - math operation: total count\n\n    Time period: the last 80 days\n    Time interval: week",
                expected="week",
            ),
            # Test time interval - weeks
            EvalCase(
                input="$pageview trends for the last four weeks|||Series:\n    - event: $pageview\n        - math operation: total count\n\n    Time period: the last four weeks\n    Time interval: week",
                expected="week",
            ),
            # Test time interval - days
            EvalCase(
                input="$pageview trends for the last 15 days|||Series:\n    - event: $pageview\n        - math operation: total count\n\n    Time period: the last 15 days\n    Time interval: day",
                expected="day",
            ),
            # Test time interval - hours
            EvalCase(
                input="$pageview trends for the last 12 hours|||Series:\n    - event: $pageview\n        - math operation: total count\n\n    Time period: the last 12 hours\n    Time interval: hour",
                expected="hour",
            ),
        ],
    )
