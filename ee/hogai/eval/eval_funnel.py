from ee.hogai.graph import InsightsAssistantGraph
from ee.models.assistant import Conversation
from .conftest import MaxEval
import pytest
from typing import cast
from braintrust import EvalCase, Score
from autoevals.llm import LLMClassifier
from autoevals.value import ExactMatch

from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage, VisualizationMessage


class FunnelCorrectness(LLMClassifier):
    """Evaluate if the generated funnel correctly answers the user's question."""

    def __init__(self, **kwargs):
        super().__init__(
            name="funnel_correctness",
            prompt_template="""Evaluate if the generated funnel correctly answers the user's question.

User question: {{input}}
Generated funnel: {{output}}

Evaluation criteria:
1. The funnel should have at least two steps
2. The steps should logically follow each other to answer the question
3. Property filters should be appropriate for the question
4. Time periods should match what was asked for
5. Breakdowns should be relevant to the question

How would you rate the correctness of the funnel? Choose one:
- perfect: The funnel fully answers the user's question with appropriate steps and filters.
- good: The funnel mostly answers the question with minor issues that don't affect correctness.
- partial: The funnel has some correct elements but misses key aspects of the question.
- incorrect: The funnel would not correctly answer the question.""",
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "incorrect": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


class TextSearchCorrectness(ExactMatch):
    """Check if text searches use appropriate operators."""

    def _run_evaluation(self, output, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0)

        json_output = output.model_dump_json(exclude_none=True)
        if "exact" in json_output:
            return Score(name=self._name(), score=0.0, comment="Used 'exact' instead of 'contains'")

        if "icontains" in json_output:
            return Score(name=self._name(), score=1.0, comment="Uses case-insensitive contains")

        return Score(name=self._name(), score=0.5, comment="No text search operators found")


@pytest.fixture
def call_node(demo_org_team_user):
    graph = (
        InsightsAssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_PLANNER)
        .add_funnel_planner()
        .add_funnel_generator(AssistantNodeName.END)
        .compile()
    )

    def callable(query: str):
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        state = graph.invoke(
            AssistantState(
                messages=[HumanMessage(content=f"Answer this question: {query}")],
                root_tool_insight_plan=query,
                root_tool_call_id="eval_test",
                root_tool_insight_type="funnel",
            ),
            {"configurable": {"thread_id": conversation.id}},
        )
        return cast(VisualizationMessage, AssistantState.model_validate(state).messages[-1]).answer

    return callable


@pytest.mark.django_db
def eval_funnel(call_node):
    MaxEval(
        experiment_name="funnel",
        task=call_node,
        scores=[FunnelCorrectness(), TextSearchCorrectness()],
        data=[
            # Test basic funnel
            EvalCase(
                input="Conversion from page view to sign up",
                expected="",
            ),
        ],
    )
