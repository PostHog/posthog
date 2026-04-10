"""Evaluations for ExperimentSummaryTool."""

import uuid
from datetime import datetime, timedelta
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import patch

from autoevals.llm import LLMClassifier
from braintrust import EvalCase, Score
from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AgentMode,
    AssistantMessage,
    AssistantToolCallMessage,
    ExperimentStatsMethod,
    Goal,
    HumanMessage,
    MaxExperimentMetricResult,
    MaxExperimentSummaryContext,
    MaxExperimentVariantResultBayesian,
)

from posthog.models import FeatureFlag

from products.experiments.backend.models.experiment import Experiment

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation


class EvalInput(TypedDict):
    input: str


EXPERIMENT_SUMMARY_ACCURACY_PROMPT = """
You are evaluating whether an AI agent's experiment summary accurately reflects
the data returned by the tools it called.

The agent may call multiple tools (e.g. read_data for experiment metadata and
experiment_results_summary for statistical results). All tool outputs are provided below.

<tool_outputs>
{{output.all_tool_outputs}}
</tool_outputs>

<agent_summary>
{{output.agent_summary}}
</agent_summary>

Check:
1. Every number in the agent's summary must be traceable to one of the tool outputs. No invented or hallucinated figures.
2. Significance status (significant vs not) must be correctly stated for each variant.
3. The agent must not declare a winner when results are not statistically significant.
4. Variant names must match the tool output.

Choose: pass (all facts accurate, no hallucinations) or fail (any factual error, hallucinated number, or wrong conclusion)
""".strip()


class ExperimentSummaryAccuracy(LLMClassifier):
    """LLM judge for experiment summary factual accuracy."""

    def _normalize(self, output: dict | None) -> dict:
        return {
            "all_tool_outputs": None,
            "agent_summary": None,
            "error": None,
            **(output or {}),
        }

    async def _run_eval_async(self, output: dict | None, expected: dict | None = None, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output provided"})
        normalized_output = self._normalize(output)
        return await super()._run_eval_async(normalized_output, expected, **kwargs)

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output provided"})
        normalized_output = self._normalize(output)
        return super()._run_eval_sync(normalized_output, expected, **kwargs)

    def __init__(self, **kwargs):
        super().__init__(
            name="experiment_summary_accuracy",
            prompt_template=EXPERIMENT_SUMMARY_ACCURACY_PROMPT,
            choice_scores={"pass": 1.0, "fail": 0.0},
            model="gpt-5.2",
            max_tokens=2048,
            reasoning_effort="medium",
            **kwargs,
        )


def _extract_summary_result(state: AssistantState) -> dict[str, Any]:
    """Extract all tool outputs and agent summary from final state."""
    result: dict[str, Any] = {
        "all_tool_outputs": None,
        "agent_summary": None,
        "error": None,
    }

    tool_outputs: list[str] = []
    for msg in state.messages:
        if isinstance(msg, AssistantToolCallMessage) and msg.content:
            tool_outputs.append(msg.content)
            if "error" in msg.content.lower() or "failed" in msg.content.lower():
                result["error"] = msg.content

    if tool_outputs:
        result["all_tool_outputs"] = "\n\n---\n\n".join(tool_outputs)

    for msg in reversed(state.messages):
        if isinstance(msg, AssistantMessage) and msg.content and not msg.tool_calls:
            result["agent_summary"] = msg.content
            break

    return result


MOCK_SUMMARY_CONTEXT = MaxExperimentSummaryContext(
    experiment_id=0,  # replaced at runtime
    experiment_name="Checkout Redesign Test",
    description="Testing whether a simplified one-page checkout increases purchase conversion",
    variants=["control", "test"],
    exposures={"control": 4821.0, "test": 4793.0},
    primary_metrics_results=[
        MaxExperimentMetricResult(
            name="1. Purchase conversion",
            goal=Goal.INCREASE,
            variant_results=[
                MaxExperimentVariantResultBayesian(
                    key="control",
                    chance_to_win=0.12,
                    credible_interval=[-0.032, 0.011],
                    delta=-0.0105,
                    significant=False,
                ),
                MaxExperimentVariantResultBayesian(
                    key="test",
                    chance_to_win=0.88,
                    credible_interval=[0.018, 0.065],
                    delta=0.0415,
                    significant=True,
                ),
            ],
        ),
    ],
    secondary_metrics_results=[],
    stats_method=ExperimentStatsMethod.BAYESIAN,
)


@pytest.fixture
def experiment_with_mock_data(demo_org_team_user):
    """Create an experiment and patch the data service to return known results."""
    _, team, user = demo_org_team_user

    async def setup():
        unique_suffix = uuid.uuid4().hex[:6]
        flag = await FeatureFlag.objects.acreate(
            team=team,
            created_by=user,
            key=f"eval-checkout-redesign-{unique_suffix}",
            name="Checkout Redesign Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        now = datetime.now(tz=ZoneInfo("UTC"))
        experiment = await Experiment.objects.acreate(
            name="Checkout Redesign Test",
            team=team,
            created_by=user,
            feature_flag=flag,
            description="Testing whether a simplified one-page checkout increases purchase conversion",
            start_date=now - timedelta(days=14),
            metrics=[
                {
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "purchase_completed"}],
                    "name": "Purchase conversion",
                }
            ],
            metrics_secondary=[],
        )

        mock_context = MOCK_SUMMARY_CONTEXT.model_copy(update={"experiment_id": experiment.id})
        return experiment, mock_context

    return setup


@pytest.fixture
def call_agent_for_summary(demo_org_team_user, experiment_with_mock_data):
    """Run the agent graph with mocked experiment data."""
    _, team, user = demo_org_team_user

    graph = (
        AssistantGraph(team, user)
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root()
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(input: EvalInput) -> dict:
        experiment, mock_context = await experiment_with_mock_data()

        conversation = await Conversation.objects.acreate(team=team, user=user)
        initial_state = AssistantState(
            messages=[HumanMessage(content=input["input"].format(experiment_id=experiment.id))],
            agent_mode=AgentMode.FLAGS,
        )
        config = RunnableConfig(configurable={"thread_id": conversation.id}, recursion_limit=48)

        mock_return = (mock_context, datetime.now(tz=ZoneInfo("UTC")), False)
        with (
            patch(
                "products.experiments.backend.max_tools.ExperimentSummaryDataService.fetch_experiment_data",
                return_value=mock_return,
            ),
            patch(
                "ee.hogai.core.agent_modes.presets.flags.has_experiment_summary_tool_feature_flag",
                return_value=True,
            ),
        ):
            raw_state = await graph.ainvoke(initial_state, config)

        state = AssistantState.model_validate(raw_state)
        return _extract_summary_result(state)

    yield callable


@pytest.mark.django_db
async def eval_experiment_summary(call_agent_for_summary, pytestconfig):
    """Test that experiment summaries are factually accurate."""
    await MaxPublicEval(
        experiment_name="experiment_summary",
        task=call_agent_for_summary,
        scores=[ExperimentSummaryAccuracy()],
        data=[
            EvalCase(
                input=EvalInput(
                    input="Summarize experiment {experiment_id}. What do the results show?",
                ),
                metadata={"test_type": "bayesian_summary_accuracy"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
