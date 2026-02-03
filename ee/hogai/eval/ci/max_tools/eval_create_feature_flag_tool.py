"""Evaluations for CreateFeatureFlagTool."""

import uuid
from typing import Any, TypedDict

import pytest
from unittest.mock import patch

from autoevals.llm import LLMClassifier
from autoevals.partial import ScorerWithPartial
from autoevals.ragas import AnswerSimilarity
from braintrust import EvalCase, Score
from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode, AssistantMessage, AssistantToolCallMessage, HumanMessage

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation


class FeatureFlagOutputScorer(ScorerWithPartial):
    """Custom scorer for feature flag tool output that combines semantic similarity for text and exact matching for numbers/booleans."""

    def __init__(self, semantic_fields: set[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.semantic_fields = semantic_fields or {"message"}

    def _run_eval_sync(self, output: dict, expected: dict, **kwargs):
        if not expected:
            return Score(name=self._name(), score=None, metadata={"reason": "No expected value provided"})
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output provided"})

        total_fields = len(expected)
        if total_fields == 0:
            return Score(name=self._name(), score=1.0)

        score_per_field = 1.0 / total_fields
        total_score = 0.0
        metadata = {}

        for field_name, expected_value in expected.items():
            actual_value = output.get(field_name)

            if field_name in self.semantic_fields:
                # Use semantic similarity for text fields
                if actual_value is not None and expected_value is not None:
                    similarity_scorer = AnswerSimilarity(model="text-embedding-3-small")
                    result = similarity_scorer.eval(output=str(actual_value), expected=str(expected_value))
                    field_score = result.score * score_per_field
                    total_score += field_score
                    metadata[f"{field_name}_score"] = result.score
                else:
                    metadata[f"{field_name}_missing"] = True
            else:
                # Use exact match for numeric/boolean fields
                if actual_value == expected_value:
                    total_score += score_per_field
                    metadata[f"{field_name}_match"] = True
                else:
                    metadata[f"{field_name}_mismatch"] = {
                        "expected": expected_value,
                        "actual": actual_value,
                    }

        return Score(name=self._name(), score=total_score, metadata=metadata)


class EvalInput(TypedDict):
    input: str


FEATURE_FLAG_OPERATION_ACCURACY_PROMPT = """
Evaluate if the agent correctly performed the feature flag creation.

<user_request>
{{input.input}}
</user_request>

<expected>
{{#expected}}
Created: {{expected.created}}
{{#expected.key_contains}}
Flag key should contain: {{expected.key_contains}}
{{/expected.key_contains}}
{{#expected.rollout_percentage}}
Rollout percentage: {{expected.rollout_percentage}}
{{/expected.rollout_percentage}}
{{#expected.has_properties}}
Should have property filters: {{expected.has_properties}}
{{/expected.has_properties}}
{{#expected.has_multivariate}}
Should be multivariate: {{expected.has_multivariate}}
{{/expected.has_multivariate}}
{{#expected.variant_count}}
Variant count: {{expected.variant_count}}
{{/expected.variant_count}}
{{/expected}}
</expected>

<actual_output>
Tool called: {{output.tool_called}}
Tool output: {{output.tool_output}}
Tool args (if any): {{output.tool_args}}
Error: {{output.error}}
</actual_output>

Evaluate:
1. Did the agent call create_feature_flag?
2. Was the flag created successfully (no error in output)?
3. Do the tool args/output match the expected configuration (key, rollout, properties, variants)?

Choose: pass (all requirements met) or fail (any requirement not met)
""".strip()


class FeatureFlagOperationAccuracy(LLMClassifier):
    """Binary LLM judge for full agent feature flag creation (tests trajectory)."""

    def _normalize(self, output: dict | None, expected: dict | None) -> tuple[dict, dict]:
        normalized_output = {
            "tool_called": None,
            "tool_output": None,
            "tool_args": None,
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
            name="feature_flag_operation_accuracy",
            prompt_template=FEATURE_FLAG_OPERATION_ACCURACY_PROMPT,
            choice_scores={"pass": 1.0, "fail": 0.0},
            model="gpt-5.2",
            max_tokens=2048,
            reasoning_effort="medium",
            **kwargs,
        )


def _extract_feature_flag_result(state: AssistantState) -> dict[str, Any]:
    """Extract feature flag creation result from final state."""
    result: dict[str, Any] = {
        "tool_called": None,
        "tool_output": None,
        "tool_args": None,
        "error": None,
    }

    create_flag_tool_call_id: str | None = None

    for msg in state.messages:
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                if tool_call.name == "create_feature_flag":
                    result["tool_called"] = "create_feature_flag"
                    result["tool_args"] = tool_call.args
                    create_flag_tool_call_id = tool_call.id
                    break

    for msg in state.messages:
        if isinstance(msg, AssistantToolCallMessage) and msg.tool_call_id == create_flag_tool_call_id:
            result["tool_output"] = msg.content
            if msg.content and ("error" in msg.content.lower() or "invalid" in msg.content.lower()):
                result["error"] = msg.content
            break

    return result


@pytest.fixture
def call_agent_for_feature_flag(demo_org_team_user):
    """Run full agent graph in FLAGS mode with natural language feature flag requests."""
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
            return _extract_feature_flag_result(state)

        yield callable


@pytest.mark.django_db
async def eval_create_feature_flag_llm(call_agent_for_feature_flag, pytestconfig):
    """Test feature flag creation via full agent with natural language prompts."""
    unique_suffix = uuid.uuid4().hex[:6]

    await MaxPublicEval(
        experiment_name="create_feature_flag_llm",
        task=call_agent_for_feature_flag,
        scores=[FeatureFlagOperationAccuracy()],
        data=[
            EvalCase(
                input=EvalInput(
                    input=f"Create a feature flag called 'new-homepage-{unique_suffix}' for testing the new homepage design"
                ),
                expected={"created": True, "key_contains": "new-homepage"},
                metadata={"test_type": "basic_flag"},
            ),
            EvalCase(
                input=EvalInput(
                    input=f"Create a feature flag 'dark-mode-{unique_suffix}' for dark mode, but keep it inactive"
                ),
                expected={"created": True, "key_contains": "dark-mode"},
                metadata={"test_type": "inactive_flag"},
            ),
            EvalCase(
                input=EvalInput(
                    input=f"Create a feature flag 'rollout-10-{unique_suffix}' that rolls out to 10% of users"
                ),
                expected={"created": True, "rollout_percentage": 10},
                metadata={"test_type": "rollout_percentage"},
            ),
            EvalCase(
                input=EvalInput(
                    input=f"Create an A/B test feature flag 'pricing-test-{unique_suffix}' with control and test variants, 50/50 split"
                ),
                expected={"created": True, "has_multivariate": True, "variant_count": 2},
                metadata={"test_type": "ab_test"},
            ),
            EvalCase(
                input=EvalInput(
                    input=f"Create a feature flag 'company-users-{unique_suffix}' that targets users with email containing @company.com"
                ),
                expected={"created": True, "has_properties": True},
                metadata={"test_type": "property_filter"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
