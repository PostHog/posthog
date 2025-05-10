import pytest
from typing import cast
from datetime import datetime
from braintrust import EvalCase, Score
from autoevals.llm import LLMClassifier
from autoevals.value import ExactMatch

from ee.hogai.graph import InsightsAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation
from posthog.schema import (
    AssistantRetentionQuery,
    HumanMessage,
    VisualizationMessage,
)

from .conftest import MaxEval


class RetentionGeneratorCorrectness(LLMClassifier):
    """Evaluate retention generator output correctness."""

    def __init__(self, **kwargs):
        super().__init__(
            name="retention_generator_correctness",
            prompt_template="""Evaluate if the generated retention query correctly implements the plan and would answer the user's question effectively.

User question: {{input}}
Retention plan: {{context}}
Generated retention query: {{output}}

Evaluation criteria:
1. The target event and returning event should match those specified in the plan
2. Property filters should be implemented correctly, with appropriate operators (contains instead of equals for text)
3. Time periods and granularity should match what's specified in the plan

How would you rate the correctness of the generated retention query? Choose one:
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
    """Check if the generator replaced 'equals' with 'contains' for text searches in retention."""

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


class RetentionStructureCorrectness(ExactMatch):
    """Check if the generator creates the correct retention structure."""

    def _run_evaluation(self, output, expected, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0)

        if not hasattr(output, "retentionFilter"):
            return Score(name=self._name(), score=0.0, comment="No retention filter specified")

        retention_filter = output.retentionFilter
        if not retention_filter:
            return Score(name=self._name(), score=0.0, comment="Empty retention filter")

        # Split the expected string into target and returning events
        target_event = expected.split("|")[0]
        returning_event = expected.split("|")[1]

        target_correct = retention_filter.targetEntity.id == target_event
        returning_correct = retention_filter.returningEntity.id == returning_event

        if target_correct and returning_correct:
            return Score(name=self._name(), score=1.0, comment="Both target and returning events are correct")
        elif target_correct:
            return Score(name=self._name(), score=0.5, comment="Target event is correct, but returning event is wrong")
        elif returning_correct:
            return Score(name=self._name(), score=0.5, comment="Returning event is correct, but target event is wrong")
        else:
            return Score(name=self._name(), score=0.0, comment="Both target and returning events are wrong")


class DateRangeCorrectness(ExactMatch):
    """Check if the generator sets the correct date range for retention."""

    def _run_evaluation(self, output, expected, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0)

        if not hasattr(output, "dateRange"):
            return Score(name=self._name(), score=0.0, comment="No date range specified")

        date_range = output.dateRange
        if not date_range:
            return Score(name=self._name(), score=0.0, comment="Empty date range")

        # For tests that check for current year inclusion
        if expected == "current_year":
            year = str(datetime.now().year)
            has_current_year = (date_range.date_from and year in date_range.date_from) or (
                date_range.date_to and year in date_range.date_to
            )
            return Score(
                name=self._name(),
                score=1.0 if has_current_year else 0.0,
                comment=f"Current year {year} is "
                + ("included" if has_current_year else "not included")
                + " in date range",
            )

        return Score(name=self._name(), score=0.5, comment="Couldn't evaluate date range")


@pytest.fixture
def call_node(demo_org_team_user):
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.RETENTION_GENERATOR)
        .add_retention_generator(AssistantNodeName.END)
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
        assert isinstance(answer, AssistantRetentionQuery), "Expected AssistantRetentionQuery"
        return answer

    return callable


@pytest.mark.django_db
def eval_retention_generator(call_node):
    MaxEval(
        experiment_name="retention_generator",
        task=call_node,
        scores=[
            RetentionGeneratorCorrectness(),
            ContainsInsteadOfEquals(),
            RetentionStructureCorrectness(),
            DateRangeCorrectness(),
        ],
        data=[
            # Test replacing equals with contains
            EvalCase(
                input="Show file upload retention after signup for users with name John|||Target event:\n    - signed_up\n\n    Returning event:\n    - file_uploaded\n\n    Filters:\n        - property filter 1:\n            - person\n            - name\n            - equals\n            - John",
                expected="John",
                context="Target event:\n    - signed_up\n\n    Returning event:\n    - file_uploaded\n\n    Filters:\n        - property filter 1:\n            - person\n            - name\n            - equals\n            - John",
            ),
            # Test basic retention structure
            EvalCase(
                input="Show retention for users who signed up|||Target Event:\n    - signed_up\n\n    Returning Event:\n    - file_uploaded",
                expected="signed_up|file_uploaded",
                context="Target Event:\n    - signed_up\n\n    Returning Event:\n    - file_uploaded",
            ),
            # Test current date
            EvalCase(
                input="Show retention for users who signed up in this January?|||Target Event:\n    - signed_up\n\n    Returning Event:\n    - file_uploaded",
                expected="current_year",
                context="Target Event:\n    - signed_up\n\n    Returning Event:\n    - file_uploaded",
            ),
        ],
    )
