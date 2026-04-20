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
    mock_key: str


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
5. When a metric's goal is "Decrease", a reduction in the metric is a positive outcome. The agent must frame lower values as good and not treat them as a regression.
6. When multiple metrics are present (primary and secondary), the agent must mention results from both. It must not ignore a significant secondary metric that contradicts the primary.

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


MOCK_BAYESIAN_SIGNIFICANT = MaxExperimentSummaryContext(
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


# Non-significant Bayesian case: test variant slightly leads on chance-to-win,
# but credible intervals cross zero and neither variant is flagged significant.
# Exercises the scorer's "do not declare a winner when not significant" rule.
MOCK_BAYESIAN_NON_SIGNIFICANT = MaxExperimentSummaryContext(
    experiment_id=0,  # replaced at runtime
    experiment_name="Homepage Hero Copy Test",
    description="Testing whether new hero copy increases signup conversion",
    variants=["control", "test"],
    exposures={"control": 2103.0, "test": 2089.0},
    primary_metrics_results=[
        MaxExperimentMetricResult(
            name="1. Signup conversion",
            goal=Goal.INCREASE,
            variant_results=[
                MaxExperimentVariantResultBayesian(
                    key="control",
                    chance_to_win=0.46,
                    credible_interval=[-0.018, 0.014],
                    delta=-0.002,
                    significant=False,
                ),
                MaxExperimentVariantResultBayesian(
                    key="test",
                    chance_to_win=0.54,
                    credible_interval=[-0.014, 0.018],
                    delta=0.002,
                    significant=False,
                ),
            ],
        ),
    ],
    secondary_metrics_results=[],
    stats_method=ExperimentStatsMethod.BAYESIAN,
)


# Bayesian experiment with goal=decrease: the test variant reduces cart
# abandonment (a good outcome when lower is better). Chance-to-win is
# already inverted by the data service for decrease goals, so test shows
# a high chance to win. Delta and credible interval are negative for the
# test variant, reflecting that abandonment went down — which is the
# desired direction. Checks that Claude frames the reduction as positive
# rather than treating the negative delta as a regression.
MOCK_BAYESIAN_GOAL_DECREASE = MaxExperimentSummaryContext(
    experiment_id=0,  # replaced at runtime
    experiment_name="Cart Abandonment Reduction Test",
    description="Testing whether a streamlined cart page reduces abandonment rate",
    variants=["control", "test"],
    exposures={"control": 3512.0, "test": 3480.0},
    primary_metrics_results=[
        MaxExperimentMetricResult(
            name="1. Cart abandonment rate",
            goal=Goal.DECREASE,
            variant_results=[
                MaxExperimentVariantResultBayesian(
                    key="control",
                    chance_to_win=0.08,
                    credible_interval=[-0.009, 0.058],
                    delta=0.0245,
                    significant=False,
                ),
                MaxExperimentVariantResultBayesian(
                    key="test",
                    chance_to_win=0.92,
                    credible_interval=[-0.071, -0.021],
                    delta=-0.046,
                    significant=True,
                ),
            ],
        ),
    ],
    secondary_metrics_results=[],
    stats_method=ExperimentStatsMethod.BAYESIAN,
)


# Mixed metrics: primary says ship (test wins on conversion), but a secondary
# guardrail metric shows a significant regression (revenue per user dropped).
# Checks that Claude surfaces both signals and doesn't cherry-pick the winner.
MOCK_BAYESIAN_MIXED_METRICS = MaxExperimentSummaryContext(
    experiment_id=0,  # replaced at runtime
    experiment_name="Simplified Pricing Page Test",
    description="Testing whether a simplified pricing page increases plan upgrades",
    variants=["control", "test"],
    exposures={"control": 5210.0, "test": 5185.0},
    primary_metrics_results=[
        MaxExperimentMetricResult(
            name="1. Plan upgrade conversion",
            goal=Goal.INCREASE,
            variant_results=[
                MaxExperimentVariantResultBayesian(
                    key="control",
                    chance_to_win=0.09,
                    credible_interval=[-0.041, 0.008],
                    delta=-0.0165,
                    significant=False,
                ),
                MaxExperimentVariantResultBayesian(
                    key="test",
                    chance_to_win=0.91,
                    credible_interval=[0.015, 0.058],
                    delta=0.0365,
                    significant=True,
                ),
            ],
        ),
    ],
    secondary_metrics_results=[
        MaxExperimentMetricResult(
            name="1. Revenue per user",
            goal=Goal.INCREASE,
            variant_results=[
                MaxExperimentVariantResultBayesian(
                    key="control",
                    chance_to_win=0.86,
                    credible_interval=[0.012, 0.049],
                    delta=0.0305,
                    significant=True,
                ),
                MaxExperimentVariantResultBayesian(
                    key="test",
                    chance_to_win=0.14,
                    credible_interval=[-0.049, -0.012],
                    delta=-0.0305,
                    significant=False,
                ),
            ],
        ),
    ],
    stats_method=ExperimentStatsMethod.BAYESIAN,
)


MOCK_CONTEXTS: dict[str, MaxExperimentSummaryContext] = {
    "bayesian_significant": MOCK_BAYESIAN_SIGNIFICANT,
    "bayesian_non_significant": MOCK_BAYESIAN_NON_SIGNIFICANT,
    "bayesian_goal_decrease": MOCK_BAYESIAN_GOAL_DECREASE,
    "bayesian_mixed_metrics": MOCK_BAYESIAN_MIXED_METRICS,
}


@pytest.fixture
def experiment_with_mock_data(demo_org_team_user):
    """Create an experiment matching a mock context template and return both."""
    _, team, user = demo_org_team_user

    async def setup(mock_template: MaxExperimentSummaryContext):
        unique_suffix = uuid.uuid4().hex[:6]
        # Distribute rollout percentages evenly across variants, putting any
        # remainder on the first variant so the total is exactly 100.
        num_variants = len(mock_template.variants)
        base_pct = 100 // num_variants
        remainder = 100 - (base_pct * num_variants)
        flag = await FeatureFlag.objects.acreate(
            team=team,
            created_by=user,
            key=f"eval-experiment-{unique_suffix}",
            name=f"{mock_template.experiment_name} Flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {
                            "key": variant,
                            "name": variant.title(),
                            "rollout_percentage": base_pct + (remainder if i == 0 else 0),
                        }
                        for i, variant in enumerate(mock_template.variants)
                    ]
                },
            },
        )

        now = datetime.now(tz=ZoneInfo("UTC"))
        experiment = await Experiment.objects.acreate(
            name=mock_template.experiment_name,
            team=team,
            created_by=user,
            feature_flag=flag,
            description=mock_template.description or "",
            start_date=now - timedelta(days=14),
            metrics=[
                {
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "name": metric.name,
                }
                for metric in mock_template.primary_metrics_results
            ],
            metrics_secondary=[],
        )

        mock_context = mock_template.model_copy(update={"experiment_id": experiment.id})
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
        mock_template = MOCK_CONTEXTS[input["mock_key"]]
        experiment, mock_context = await experiment_with_mock_data(mock_template)

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
                    mock_key="bayesian_significant",
                ),
                metadata={"test_type": "bayesian_significant"},
            ),
            EvalCase(
                input=EvalInput(
                    input="Summarize experiment {experiment_id}. What do the results show?",
                    mock_key="bayesian_non_significant",
                ),
                metadata={"test_type": "bayesian_non_significant"},
            ),
            EvalCase(
                input=EvalInput(
                    input="Summarize experiment {experiment_id}. What do the results show?",
                    mock_key="bayesian_goal_decrease",
                ),
                metadata={"test_type": "bayesian_goal_decrease"},
            ),
            EvalCase(
                input=EvalInput(
                    input="Summarize experiment {experiment_id}. What do the results show?",
                    mock_key="bayesian_mixed_metrics",
                ),
                metadata={"test_type": "bayesian_mixed_metrics"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
