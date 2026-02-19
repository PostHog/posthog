"""Evaluations for CreateExperimentTool."""

import uuid
from typing import Any, TypedDict

import pytest
from unittest.mock import patch

from autoevals.llm import LLMClassifier
from braintrust import EvalCase, Score
from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode, AssistantMessage, AssistantToolCallMessage, HumanMessage

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation


class EvalInput(TypedDict):
    input: str


EXPERIMENT_OPERATION_ACCURACY_PROMPT = """
Evaluate if the agent correctly created an experiment.

<user_request>
{{input.input}}
</user_request>

<expected>
{{#expected}}
Experiment created: {{expected.experiment_created}}
{{#expected.experiment_name_contains}}
Experiment name should contain: {{expected.experiment_name_contains}}
{{/expected.experiment_name_contains}}
{{#expected.experiment_type}}
Experiment type: {{expected.experiment_type}}
{{/expected.experiment_type}}
{{#expected.variant_count}}
Expected number of variants: {{expected.variant_count}}
{{/expected.variant_count}}
{{#expected.has_uneven_split}}
Expected uneven variant split: {{expected.has_uneven_split}}
{{/expected.has_uneven_split}}
{{/expected}}
</expected>

<actual_output>
Feature flag tool called: {{output.flag_tool_called}}
Feature flag tool args: {{output.flag_tool_args}}
Feature flag tool output: {{output.flag_tool_output}}
Create experiment tool called: {{output.experiment_tool_called}}
Create experiment args: {{output.experiment_tool_args}}
Create experiment output: {{output.experiment_tool_output}}
Error: {{output.error}}
</actual_output>

Evaluate:
1. Did the agent call create_experiment?
2. Was the experiment created successfully (no error in output)?
3. Does the experiment name/configuration match the user's request?
4. If variant count was specified, does the feature flag have the correct number of variants?
5. If uneven split was specified, were the variant percentages set accordingly?

Choose: pass (all requirements met) or fail (any requirement not met)
""".strip()


class ExperimentOperationAccuracy(LLMClassifier):
    """Binary LLM judge for full agent experiment creation (tests trajectory)."""

    def _normalize(self, output: dict | None, expected: dict | None) -> tuple[dict, dict]:
        normalized_output = {
            "experiment_tool_called": None,
            "experiment_tool_args": None,
            "experiment_tool_output": None,
            "error": None,
            **(output or {}),
        }
        normalized_expected = {**(expected or {})}
        return normalized_output, normalized_expected

    async def _run_eval_async(self, output: dict | None, expected: dict | None = None, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output provided"})
        normalized_output, normalized_expected = self._normalize(output, expected)
        return await super()._run_eval_async(normalized_output, normalized_expected, **kwargs)

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output provided"})
        normalized_output, normalized_expected = self._normalize(output, expected)
        return super()._run_eval_sync(normalized_output, normalized_expected, **kwargs)

    def __init__(self, **kwargs):
        super().__init__(
            name="experiment_operation_accuracy",
            prompt_template=EXPERIMENT_OPERATION_ACCURACY_PROMPT,
            choice_scores={"pass": 1.0, "fail": 0.0},
            model="gpt-5.2",
            max_tokens=2048,
            reasoning_effort="medium",
            **kwargs,
        )


def _extract_experiment_result(state: AssistantState) -> dict[str, Any]:
    """Extract experiment creation result from final state."""
    result: dict[str, Any] = {
        "experiment_tool_called": None,
        "experiment_tool_args": None,
        "experiment_tool_output": None,
        "flag_tool_called": None,
        "flag_tool_args": None,
        "flag_tool_output": None,
        "error": None,
    }

    create_experiment_tool_call_id: str | None = None
    create_flag_tool_call_id: str | None = None

    for msg in state.messages:
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                if tool_call.name == "create_experiment":
                    result["experiment_tool_called"] = "create_experiment"
                    result["experiment_tool_args"] = tool_call.args
                    create_experiment_tool_call_id = tool_call.id
                elif tool_call.name == "create_feature_flag":
                    result["flag_tool_called"] = "create_feature_flag"
                    result["flag_tool_args"] = tool_call.args
                    create_flag_tool_call_id = tool_call.id

    for msg in state.messages:
        if isinstance(msg, AssistantToolCallMessage):
            if msg.tool_call_id == create_experiment_tool_call_id:
                result["experiment_tool_output"] = msg.content
                if msg.content and ("error" in msg.content.lower() or "failed" in msg.content.lower()):
                    result["error"] = msg.content
            elif msg.tool_call_id == create_flag_tool_call_id:
                result["flag_tool_output"] = msg.content

    return result


@pytest.fixture
def call_agent_for_experiment(demo_org_team_user):
    """Run full agent graph in FLAGS mode with natural language experiment requests."""
    with patch("ee.hogai.chat_agent.mode_manager.has_flags_mode_feature_flag", return_value=True):
        _, team, user = demo_org_team_user

        graph = (
            AssistantGraph(team, user)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root()
            .compile(checkpointer=DjangoCheckpointer())
        )

        async def callable(input: EvalInput) -> dict:
            conversation = await Conversation.objects.acreate(team=team, user=user)
            initial_state = AssistantState(
                messages=[HumanMessage(content=input["input"])],
                agent_mode=AgentMode.FLAGS,
            )
            config = RunnableConfig(configurable={"thread_id": conversation.id}, recursion_limit=48)
            raw_state = await graph.ainvoke(initial_state, config)
            state = AssistantState.model_validate(raw_state)
            return _extract_experiment_result(state)

        yield callable


@pytest.mark.django_db
async def eval_create_experiment_llm(call_agent_for_experiment, pytestconfig):
    """Test experiment creation via full agent with natural language prompts."""
    unique_suffix = uuid.uuid4().hex[:6]

    await MaxPublicEval(
        experiment_name="create_experiment_llm",
        task=call_agent_for_experiment,
        scores=[ExperimentOperationAccuracy()],
        data=[
            EvalCase(
                input=EvalInput(
                    input=f"Create an A/B test experiment called 'Pricing Test {unique_suffix}' to test our new pricing page"
                ),
                expected={
                    "experiment_created": True,
                    "experiment_name_contains": "pricing",
                },
                metadata={"test_type": "full_workflow"},
            ),
            EvalCase(
                input=EvalInput(
                    input=f"Set up an experiment named 'Checkout Flow {unique_suffix}' to test a new checkout experience"
                ),
                expected={
                    "experiment_created": True,
                    "experiment_name_contains": "checkout",
                },
                metadata={"test_type": "full_workflow"},
            ),
            EvalCase(
                input=EvalInput(
                    input=f"I want to run an A/B test on our homepage hero section, call it 'Hero Test {unique_suffix}'"
                ),
                expected={
                    "experiment_created": True,
                    "experiment_name_contains": "hero",
                },
                metadata={"test_type": "full_workflow"},
            ),
            EvalCase(
                input=EvalInput(
                    input=f"Create an experiment called 'Multi-variant CTA {unique_suffix}' with three variants: control, variant_a, and variant_b to test different call-to-action buttons"
                ),
                expected={
                    "experiment_created": True,
                    "experiment_name_contains": "CTA",
                    "variant_count": 3,
                },
                metadata={"test_type": "multivariate"},
            ),
            EvalCase(
                input=EvalInput(
                    input=f"Set up an experiment called 'Gradual Rollout {unique_suffix}' with an 80/20 split between control and test to cautiously test a new onboarding flow"
                ),
                expected={
                    "experiment_created": True,
                    "experiment_name_contains": "rollout",
                    "has_uneven_split": True,
                },
                metadata={"test_type": "uneven_split"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
