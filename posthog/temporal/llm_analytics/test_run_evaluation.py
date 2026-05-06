import json
import uuid
from datetime import datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team

from products.llm_analytics.backend.llm.errors import StructuredOutputParseError
from products.llm_analytics.backend.models.evaluation_config import EvaluationConfig
from products.llm_analytics.backend.models.evaluations import Evaluation
from products.llm_analytics.backend.models.model_configuration import LLMModelConfiguration

from .run_evaluation import (
    BooleanEvalResult,
    BooleanWithNAEvalResult,
    EmitEvaluationEventInputs,
    ExecuteLLMJudgeInputs,
    LLMJudgeResult,
    RunEvaluationInputs,
    RunEvaluationWorkflow,
    SendEvaluationDisabledEmailInputs,
    SendTrialUsageEmailInputs,
    disable_evaluation_activity,
    emit_evaluation_event_activity,
    execute_hog_eval_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    run_hog_eval,
    send_evaluation_disabled_email_activity,
    send_trial_usage_email_activity,
)


def create_mock_event_data(team_id: int, **overrides: Any) -> dict[str, Any]:
    """Helper to create mock event data for tests"""
    defaults = {
        "uuid": str(uuid.uuid4()),
        "event": "$ai_generation",
        "properties": {"$ai_input": "test input", "$ai_output": "test output"},
        "timestamp": datetime.now().isoformat(),
        "team_id": team_id,
        "distinct_id": "test-user",
    }
    return {**defaults, **overrides}


@pytest.fixture
def setup_data():
    """Create test organization, team, and evaluation"""
    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=organization, name="Test Team")
    evaluation = Evaluation.objects.create(
        team=team,
        name="Test Evaluation",
        evaluation_type="llm_judge",
        evaluation_config={"prompt": "Is this response factually accurate?"},
        output_type="boolean",
        output_config={},
        enabled=True,
    )
    return {"organization": organization, "team": team, "evaluation": evaluation}


class TestRunEvaluationWorkflow:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_fetch_evaluation_activity(self, setup_data):
        """Test fetching evaluation from database"""
        evaluation = setup_data["evaluation"]
        team = setup_data["team"]

        inputs = RunEvaluationInputs(
            evaluation_id=str(evaluation.id),
            event_data=create_mock_event_data(team.id),
        )

        with patch("posthog.temporal.llm_analytics.run_evaluation.Evaluation.objects.get") as mock_get:
            mock_evaluation = MagicMock()
            mock_evaluation.id = evaluation.id
            mock_evaluation.name = "Test Evaluation"
            mock_evaluation.evaluation_type = "llm_judge"
            mock_evaluation.evaluation_config = {"prompt": "Is this response factually accurate?"}
            mock_evaluation.output_type = "boolean"
            mock_evaluation.output_config = {}
            mock_evaluation.team_id = team.id
            mock_get.return_value = mock_evaluation

            result = await fetch_evaluation_activity(inputs)

            assert result["id"] == str(evaluation.id)
            assert result["name"] == "Test Evaluation"
            assert result["evaluation_type"] == "llm_judge"
            assert result["evaluation_config"] == {"prompt": "Is this response factually accurate?"}
            assert result["output_type"] == "boolean"
            assert result["output_config"] == {"allows_na": False}

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_llm_judge_activity(self, setup_data):
        """Test LLM judge execution with realistic message array format"""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this response factually accurate?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "4"}],
            },
        )

        # Mock unified Client response
        with patch("posthog.temporal.llm_analytics.run_evaluation.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_parsed = BooleanEvalResult(verdict=True, reasoning="The answer is correct")

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = await execute_llm_judge_activity(
                ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data)
            )

            assert result["verdict"] is True
            assert result["reasoning"] == "The answer is correct"
            mock_client.complete.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_emit_evaluation_event_activity(self, setup_data):
        """Test emitting evaluation event"""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
        }

        event_data = create_mock_event_data(team.id, properties={})

        result: LLMJudgeResult = {
            "verdict": True,
            "reasoning": "Test passed",
            "allows_na": False,
            "model": "gpt-5-mini",
            "provider": "openai",
            "input_tokens": 42,
            "output_tokens": 18,
        }

        with patch("posthog.temporal.llm_analytics.run_evaluation.Team.objects.get") as mock_team_get:
            with patch("posthog.temporal.llm_analytics.run_evaluation.capture_internal") as mock_capture:
                mock_team_get.return_value = team
                mock_capture.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

                await emit_evaluation_event_activity(
                    EmitEvaluationEventInputs(
                        evaluation=evaluation,
                        event_data=event_data,
                        result=result,
                        start_time=datetime(2024, 1, 1, 12, 0, 0),
                    )
                )

                mock_capture.assert_called_once()
                call_kwargs = mock_capture.call_args[1]
                assert call_kwargs["event_name"] == "$ai_evaluation"
                assert call_kwargs["token"] == team.api_token
                assert call_kwargs["process_person_profile"] is True
                props = call_kwargs["properties"]
                assert props["$ai_evaluation_result"] is True
                assert props["$ai_model"] == "gpt-5-mini"
                assert props["$ai_provider"] == "openai"
                assert props["$ai_input_tokens"] == 42
                assert props["$ai_output_tokens"] == 18
                assert props["$ai_evaluation_type"] == "online"

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_emit_evaluation_event_activity_skipped_omits_cost_attribution(self, setup_data):
        """Skipped evaluations never made an API call, so the emitted event must not attribute
        a model, provider, or token usage. The skip is surfaced via dedicated properties so
        consumers can still distinguish a skip from a regular result."""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
        }

        event_data = create_mock_event_data(team.id, properties={})

        result: LLMJudgeResult = {
            "verdict": False,
            "reasoning": "Source trace errored before producing output; evaluation skipped.",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "is_byok": False,
            "key_id": None,
            "allows_na": False,
            "skipped": True,
            "skip_reason": "trace_errored",
        }

        with patch("posthog.temporal.llm_analytics.run_evaluation.Team.objects.get") as mock_team_get:
            with patch("posthog.temporal.llm_analytics.run_evaluation.capture_internal") as mock_capture:
                mock_team_get.return_value = team
                mock_capture.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

                await emit_evaluation_event_activity(
                    EmitEvaluationEventInputs(
                        evaluation=evaluation,
                        event_data=event_data,
                        result=result,
                        start_time=datetime(2024, 1, 1, 12, 0, 0),
                    )
                )

                props = mock_capture.call_args[1]["properties"]

        assert props["$ai_evaluation_skipped"] is True
        assert props["$ai_evaluation_skip_reason"] == "trace_errored"
        assert props["$ai_evaluation_result"] is False
        for cost_key in (
            "$ai_model",
            "$ai_provider",
            "$ai_input_tokens",
            "$ai_output_tokens",
            "$ai_evaluation_model",
            "$ai_evaluation_provider",
            "$ai_evaluation_key_type",
            "$ai_evaluation_key_id",
        ):
            assert cost_key not in props, f"{cost_key} must be omitted for skipped evaluations"

    def test_parse_inputs(self):
        """Test that parse_inputs correctly parses workflow inputs"""
        event_data = create_mock_event_data(team_id=1)
        inputs = ["eval-123", json.dumps(event_data)]

        parsed = RunEvaluationWorkflow.parse_inputs(inputs)

        assert parsed.evaluation_id == "eval-123"
        assert parsed.event_data == event_data

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_llm_judge_activity_allows_na_applicable(self, setup_data):
        """Test LLM judge execution with allows_na=True when applicable"""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this response factually accurate?"},
            "output_type": "boolean",
            "output_config": {"allows_na": True},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "4"}],
            },
        )

        with patch("posthog.temporal.llm_analytics.run_evaluation.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_parsed = BooleanWithNAEvalResult(verdict=True, applicable=True, reasoning="The answer is correct")

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = await execute_llm_judge_activity(
                ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data)
            )

            assert result["verdict"] is True
            assert result["applicable"] is True
            assert result["reasoning"] == "The answer is correct"
            assert result["allows_na"] is True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_llm_judge_activity_allows_na_not_applicable(self, setup_data):
        """Test LLM judge execution with allows_na=True when not applicable"""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Check mathematical accuracy"},
            "output_type": "boolean",
            "output_config": {"allows_na": True},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "Hello, how are you?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "I'm doing well, thanks!"}],
            },
        )

        with patch("posthog.temporal.llm_analytics.run_evaluation.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_parsed = BooleanWithNAEvalResult(
                verdict=None, applicable=False, reasoning="This is a greeting, not a math problem"
            )

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = await execute_llm_judge_activity(
                ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data)
            )

            assert result["verdict"] is None
            assert result["applicable"] is False
            assert result["reasoning"] == "This is a greeting, not a math problem"
            assert result["allows_na"] is True

    @pytest.mark.parametrize(
        "ai_is_error_value",
        [
            pytest.param(True, id="bool_true"),
            pytest.param("true", id="string_true"),
            pytest.param("True", id="string_True_capitalized"),
        ],
    )
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_llm_judge_activity_skips_errored_traces(self, ai_is_error_value: bool | str, setup_data):
        """Errored traces have no meaningful output — the judge must short-circuit instead of
        producing a verdict against an empty Output (which historically defaulted to true)."""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this response relevant?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [],
                "$ai_is_error": ai_is_error_value,
            },
        )

        with patch("posthog.temporal.llm_analytics.run_evaluation.Client") as mock_client_class:
            result = await execute_llm_judge_activity(
                ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data)
            )

            mock_client_class.assert_not_called()

        assert result["verdict"] is False
        assert result["skipped"] is True
        assert result["skip_reason"] == "trace_errored"
        assert result["allows_na"] is False
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["total_tokens"] == 0
        assert "errored" in result["reasoning"].lower()
        # `model` / `provider` must be omitted so they don't get attributed to a phantom call
        # via `.get(..., DEFAULT_JUDGE_MODEL)` defaults in downstream consumers.
        assert "model" not in result
        assert "provider" not in result

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_llm_judge_activity_skips_errored_trace_with_allows_na(self, setup_data):
        """When N/A is allowed, errored traces should be marked inapplicable rather than verdict=false."""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this response relevant?"},
            "output_type": "boolean",
            "output_config": {"allows_na": True},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "Hi"}],
                "$ai_is_error": True,
            },
        )

        with patch("posthog.temporal.llm_analytics.run_evaluation.Client") as mock_client_class:
            result = await execute_llm_judge_activity(
                ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data)
            )

            mock_client_class.assert_not_called()

        assert result["verdict"] is None
        assert result["applicable"] is False
        assert result["allows_na"] is True
        assert result["skipped"] is True
        assert result["skip_reason"] == "trace_errored"

    @pytest.mark.parametrize(
        "error_props",
        [
            pytest.param({}, id="missing"),
            pytest.param({"$ai_is_error": False}, id="explicit_false"),
            pytest.param({"$ai_is_error": "false"}, id="string_false"),
        ],
    )
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_llm_judge_activity_does_not_skip_when_not_errored(
        self, error_props: dict[str, Any], setup_data
    ):
        """Sanity check: traces without `$ai_is_error=true` still flow through to the LLM judge."""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this response relevant?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "4"}],
                **error_props,
            },
        )

        with patch("posthog.temporal.llm_analytics.run_evaluation.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_response = MagicMock()
            mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="Correct")
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = await execute_llm_judge_activity(
                ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data)
            )

            mock_client.complete.assert_called_once()

        assert result["verdict"] is True
        assert result.get("skipped") is not True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_emit_evaluation_event_activity_allows_na_applicable(self, setup_data):
        """Test emitting evaluation event for applicable allows_na result"""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
        }

        event_data = create_mock_event_data(team.id, properties={})

        result: LLMJudgeResult = {
            "verdict": True,
            "reasoning": "Test passed",
            "applicable": True,
            "allows_na": True,
        }

        with patch("posthog.temporal.llm_analytics.run_evaluation.Team.objects.get") as mock_team_get:
            with patch("posthog.temporal.llm_analytics.run_evaluation.capture_internal") as mock_capture:
                mock_team_get.return_value = team
                mock_capture.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

                await emit_evaluation_event_activity(
                    EmitEvaluationEventInputs(
                        evaluation=evaluation,
                        event_data=event_data,
                        result=result,
                        start_time=datetime(2024, 1, 1, 12, 0, 0),
                    )
                )

                mock_capture.assert_called_once()
                props = mock_capture.call_args[1]["properties"]
                assert props["$ai_evaluation_result"] is True
                assert props["$ai_evaluation_applicable"] is True
                assert props["$ai_evaluation_allows_na"] is True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_emit_evaluation_event_activity_allows_na_not_applicable(self, setup_data):
        """Test emitting evaluation event for not applicable allows_na result"""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
        }

        event_data = create_mock_event_data(team.id, properties={})

        result: LLMJudgeResult = {
            "verdict": None,
            "reasoning": "Not applicable",
            "applicable": False,
            "allows_na": True,
        }

        with patch("posthog.temporal.llm_analytics.run_evaluation.Team.objects.get") as mock_team_get:
            with patch("posthog.temporal.llm_analytics.run_evaluation.capture_internal") as mock_capture:
                mock_team_get.return_value = team
                mock_capture.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

                await emit_evaluation_event_activity(
                    EmitEvaluationEventInputs(
                        evaluation=evaluation,
                        event_data=event_data,
                        result=result,
                        start_time=datetime(2024, 1, 1, 12, 0, 0),
                    )
                )

                mock_capture.assert_called_once()
                props = mock_capture.call_args[1]["properties"]
                assert "$ai_evaluation_result" not in props
                assert props["$ai_evaluation_applicable"] is False
                assert props["$ai_evaluation_allows_na"] is True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_disable_evaluation_activity(self, setup_data):
        evaluation = setup_data["evaluation"]
        team = setup_data["team"]

        assert evaluation.enabled

        await disable_evaluation_activity(str(evaluation.id), team.id, "trial_limit_reached")

        await sync_to_async(evaluation.refresh_from_db)()
        assert not evaluation.enabled
        assert evaluation.status == "error"
        assert evaluation.status_reason == "trial_limit_reached"

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_successful_execution_does_not_disable_evaluation(self, setup_data):
        evaluation = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation_dict = {
            "id": str(evaluation.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this response factually accurate?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "4"}],
            },
        )

        with patch("posthog.temporal.llm_analytics.run_evaluation.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_response = MagicMock()
            mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="Correct")
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            await execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation_dict, event_data=event_data))

        await sync_to_async(evaluation.refresh_from_db)()
        assert evaluation.enabled is True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_llm_judge_activity_parse_error_raises_non_retryable(self, setup_data):
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this response factually accurate?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "4"}],
            },
        )

        with patch("posthog.temporal.llm_analytics.run_evaluation.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.complete.side_effect = StructuredOutputParseError(
                "Failed to parse structured output: I need to fetch your bundles..."
            )

            with pytest.raises(ApplicationError, match="Failed to parse structured output") as exc_info:
                await execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

            assert exc_info.value.non_retryable is True
            assert exc_info.value.details[0] == {"error_type": "parse_error"}

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_llm_judge_activity_rejects_non_trial_model_on_posthog_key(self, setup_data):
        team = setup_data["team"]

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this accurate?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
            "model_configuration": {
                "provider": "openai",
                "model": "o3-pro",
                "provider_key_id": None,
            },
        }

        event_data = create_mock_event_data(team.id)

        with pytest.raises(ApplicationError, match="not available on the trial plan") as exc_info:
            await execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

        assert exc_info.value.non_retryable is True
        assert exc_info.value.details[0]["error_type"] == "model_not_allowed"


class TestExecuteHogEvalActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_returns_true(self, setup_data):
        team = setup_data["team"]

        # Compile source to bytecode for the test
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return true", "destination")

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return true", "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        result = await execute_hog_eval_activity(evaluation, event_data)

        assert result["verdict"] is True
        assert result["reasoning"] == ""

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_returns_false(self, setup_data):
        team = setup_data["team"]

        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return false", "destination")

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return false", "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        result = await execute_hog_eval_activity(evaluation, event_data)

        assert result["verdict"] is False

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_non_bool_raises_error(self, setup_data):
        team = setup_data["team"]

        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return 42", "destination")

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return 42", "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with pytest.raises(ApplicationError, match="Must return boolean"):
            await execute_hog_eval_activity(evaluation, event_data)

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_captures_print_as_reasoning(self, setup_data):
        team = setup_data["team"]

        from posthog.cdp.validation import compile_hog

        source = "print('checking output'); return true"
        bytecode = compile_hog(source, "destination")

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": source, "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        result = await execute_hog_eval_activity(evaluation, event_data)

        assert result["verdict"] is True
        assert "checking output" in result["reasoning"]

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_missing_bytecode_raises_error(self, setup_data):
        team = setup_data["team"]

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return true"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with pytest.raises(ApplicationError, match="Missing bytecode"):
            await execute_hog_eval_activity(evaluation, event_data)

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_wrong_type_raises_error(self, setup_data):
        team = setup_data["team"]

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "LLM Eval",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "test"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with pytest.raises(ApplicationError, match="Unsupported evaluation type"):
            await execute_hog_eval_activity(evaluation, event_data)

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_accesses_globals(self, setup_data):
        team = setup_data["team"]

        from posthog.cdp.validation import compile_hog

        source = "let out := output; if (out == 'test output') { return true } return false"
        bytecode = compile_hog(source, "destination")

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": source, "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        result = await execute_hog_eval_activity(evaluation, event_data)

        assert result["verdict"] is True


class TestEvalResultModels:
    def test_boolean_eval_result(self):
        """Test BooleanEvalResult model"""
        result = BooleanEvalResult(reasoning="Test reasoning", verdict=True)
        assert result.reasoning == "Test reasoning"
        assert result.verdict is True

    def test_boolean_with_na_eval_result_applicable(self):
        """Test BooleanWithNAEvalResult model when applicable"""
        result = BooleanWithNAEvalResult(reasoning="Test reasoning", applicable=True, verdict=True)
        assert result.reasoning == "Test reasoning"
        assert result.applicable is True
        assert result.verdict is True

    def test_boolean_with_na_eval_result_not_applicable(self):
        """Test BooleanWithNAEvalResult model when not applicable"""
        result = BooleanWithNAEvalResult(reasoning="Not applicable", applicable=False, verdict=None)
        assert result.reasoning == "Not applicable"
        assert result.applicable is False
        assert result.verdict is None

    def test_boolean_with_na_eval_result_rejects_verdict_when_not_applicable(self):
        """Test that verdict must be null when applicable is false"""
        with pytest.raises(ValueError, match="verdict must be null when applicable is false"):
            BooleanWithNAEvalResult(reasoning="Not applicable", applicable=False, verdict=True)


class TestRunHogEvalAllowsNA:
    @pytest.fixture(autouse=True)
    def _compile(self):
        from posthog.cdp.validation import compile_hog

        self.compile_hog = compile_hog

    def _event_data(self) -> dict[str, Any]:
        return create_mock_event_data(team_id=1)

    @parameterized.expand(
        [
            ("true_result", "return true", True, True),
            ("false_result", "return false", False, True),
        ]
    )
    def test_bool_result_with_allows_na(self, _name, source, expected_verdict, expected_applicable):
        bytecode = self.compile_hog(source, "destination")
        result = run_hog_eval(bytecode, self._event_data(), allows_na=True)

        assert result["verdict"] is expected_verdict
        assert result["applicable"] is expected_applicable
        assert result["error"] is None

    def test_null_return_with_allows_na_true(self):
        bytecode = self.compile_hog("return null", "destination")
        result = run_hog_eval(bytecode, self._event_data(), allows_na=True)

        assert result["verdict"] is None
        assert result["applicable"] is False
        assert result["error"] is None

    def test_null_return_with_allows_na_false(self):
        bytecode = self.compile_hog("return null", "destination")
        result = run_hog_eval(bytecode, self._event_data(), allows_na=False)

        assert result["verdict"] is None
        assert result["error"] is not None
        assert "Must return boolean" in result["error"]
        assert "applicable" not in result

    def test_bool_result_without_allows_na_has_no_applicable(self):
        bytecode = self.compile_hog("return true", "destination")
        result = run_hog_eval(bytecode, self._event_data(), allows_na=False)

        assert result["verdict"] is True
        assert "applicable" not in result


class TestExecuteHogEvalActivityAllowsNA:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_null_return_with_allows_na(self, setup_data):
        team = setup_data["team"]

        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return null", "destination")

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return null", "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {"allows_na": True},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        result = await execute_hog_eval_activity(evaluation, event_data)

        assert result["verdict"] is None
        assert result["applicable"] is False
        assert result["allows_na"] is True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_bool_return_with_allows_na(self, setup_data):
        team = setup_data["team"]

        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return true", "destination")

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return true", "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {"allows_na": True},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        result = await execute_hog_eval_activity(evaluation, event_data)

        assert result["verdict"] is True
        assert result["applicable"] is True
        assert result["allows_na"] is True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_null_return_without_allows_na_raises(self, setup_data):
        team = setup_data["team"]

        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return null", "destination")

        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return null", "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with pytest.raises(ApplicationError, match="Must return boolean"):
            await execute_hog_eval_activity(evaluation, event_data)


class TestIncrementTrialEvalCountActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "trial_eval_limit, trial_evals_used, expected_threshold, expected_used_after",
        [
            (100, 0, None, 1),
            (100, 49, 50, 50),
            (100, 74, 75, 75),
            (100, 99, 100, 100),
            (100, 100, None, 101),  # already exceeded — should not re-trigger
            (100, 50, None, 51),  # just past 50% — no threshold
            (10, 4, 50, 5),  # 50% of 10
            (10, 7, 75, 8),  # round(10 * 75 / 100) = round(7.5) = 8
            (10, 9, 100, 10),  # 100% of 10
        ],
        ids=[
            "no_threshold",
            "50pct_reached",
            "75pct_reached",
            "100pct_reached",
            "already_exceeded",
            "past_50pct",
            "small_limit_50pct",
            "small_limit_75pct_rounds",
            "small_limit_100pct",
        ],
    )
    async def test_increment_trial_eval_count(
        self, setup_data, trial_eval_limit, trial_evals_used, expected_threshold, expected_used_after
    ):
        team = setup_data["team"]
        config, _ = await sync_to_async(EvaluationConfig.objects.get_or_create)(team_id=team.id)
        config.trial_eval_limit = trial_eval_limit
        config.trial_evals_used = trial_evals_used
        await sync_to_async(config.save)()

        result = await increment_trial_eval_count_activity(team.id)

        assert result == expected_threshold
        config = await sync_to_async(EvaluationConfig.objects.get)(team_id=team.id)
        assert config.trial_evals_used == expected_used_after


class TestSendTrialUsageEmailActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "threshold_pct, expected_template",
        [
            (50, "llm_analytics_trial_warning"),
            (75, "llm_analytics_trial_warning"),
            (100, "llm_analytics_trial_exhausted"),
        ],
        ids=["50pct_warning", "75pct_warning", "100pct_exhausted"],
    )
    async def test_sends_correct_template_for_threshold(self, setup_data, threshold_pct, expected_template):
        team = setup_data["team"]
        await sync_to_async(EvaluationConfig.objects.get_or_create)(team_id=team.id)

        with (
            patch("posthog.email.is_email_available", return_value=True),
            patch("posthog.email.EmailMessage") as mock_email_class,
        ):
            mock_message = MagicMock()
            mock_email_class.return_value = mock_message

            await send_trial_usage_email_activity(
                SendTrialUsageEmailInputs(team_id=team.id, threshold_pct=threshold_pct)
            )

            mock_email_class.assert_called_once()
            call_kwargs = mock_email_class.call_args[1]
            assert call_kwargs["template_name"] == expected_template
            mock_message.send.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_skips_when_email_not_available(self, setup_data):
        team = setup_data["team"]
        await sync_to_async(EvaluationConfig.objects.get_or_create)(team_id=team.id)

        with (
            patch("posthog.email.is_email_available", return_value=False),
            patch("posthog.email.EmailMessage") as mock_email_class,
        ):
            await send_trial_usage_email_activity(SendTrialUsageEmailInputs(team_id=team.id, threshold_pct=50))

            mock_email_class.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize("threshold_pct", [50, 75, 100], ids=["50pct", "75pct", "100pct"])
    async def test_campaign_key_includes_threshold_and_team(self, setup_data, threshold_pct):
        team = setup_data["team"]
        await sync_to_async(EvaluationConfig.objects.get_or_create)(team_id=team.id)

        with (
            patch("posthog.email.is_email_available", return_value=True),
            patch("posthog.email.EmailMessage") as mock_email_class,
        ):
            mock_message = MagicMock()
            mock_email_class.return_value = mock_message

            await send_trial_usage_email_activity(
                SendTrialUsageEmailInputs(team_id=team.id, threshold_pct=threshold_pct)
            )

            call_kwargs = mock_email_class.call_args[1]
            assert call_kwargs["campaign_key"] == f"llm_analytics_trial_{threshold_pct}pct_{team.id}"

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_includes_affected_eval_names_in_context(self, setup_data):
        team = setup_data["team"]
        await sync_to_async(EvaluationConfig.objects.get_or_create)(team_id=team.id)

        # Trial eval (no provider_key) — should be included
        mc_trial = await sync_to_async(LLMModelConfiguration.objects.create)(
            team=team, provider="openai", model="gpt-4o-mini"
        )
        await sync_to_async(Evaluation.objects.create)(
            team=team,
            name="My Trial Eval",
            evaluation_type="llm_judge",
            output_type="boolean",
            model_configuration=mc_trial,
            enabled=True,
        )
        # Legacy eval (no model_configuration) — should be included
        await sync_to_async(Evaluation.objects.create)(
            team=team,
            name="Legacy Eval",
            evaluation_type="llm_judge",
            output_type="boolean",
            model_configuration=None,
            enabled=True,
        )
        # Disabled eval — should NOT be included
        await sync_to_async(Evaluation.objects.create)(
            team=team,
            name="Disabled Eval",
            evaluation_type="llm_judge",
            output_type="boolean",
            model_configuration=mc_trial,
            enabled=False,
        )

        with (
            patch("posthog.email.is_email_available", return_value=True),
            patch("posthog.email.EmailMessage") as mock_email_class,
        ):
            mock_message = MagicMock()
            mock_email_class.return_value = mock_message

            await send_trial_usage_email_activity(SendTrialUsageEmailInputs(team_id=team.id, threshold_pct=75))

            call_kwargs = mock_email_class.call_args[1]
            affected = call_kwargs["template_context"]["affected_evals"]
            assert "My Trial Eval" in affected
            assert "Legacy Eval" in affected


class TestSendEvaluationDisabledEmailActivity:
    @pytest.fixture
    def setup_data(self, db):
        from posthog.models import Organization, Team, User

        organization = Organization.objects.create(name="Test Org")
        User.objects.create_and_join(organization=organization, email="test@example.com", password="password")
        team = Team.objects.create(organization=organization, name="Test Team")
        return {"team": team, "organization": organization}

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_sends_email_with_evaluation_disabled_template(self, setup_data):
        team = setup_data["team"]

        with (
            patch("posthog.email.is_email_available", return_value=True),
            patch("posthog.email.EmailMessage") as mock_email_class,
        ):
            mock_message = MagicMock()
            mock_email_class.return_value = mock_message

            await send_evaluation_disabled_email_activity(
                SendEvaluationDisabledEmailInputs(
                    team_id=team.id,
                    evaluation_id="eval-123",
                    evaluation_name="My Eval",
                    status_reason="model_not_allowed",
                    human_readable_reason="The model 'gpt-9' isn't available on the trial plan.",
                )
            )

            mock_email_class.assert_called_once()
            call_kwargs = mock_email_class.call_args[1]
            assert call_kwargs["template_name"] == "llm_analytics_evaluation_disabled"
            assert call_kwargs["template_context"]["evaluation_name"] == "My Eval"
            assert "isn't available on the trial plan" in call_kwargs["template_context"]["disabled_reason"]
            # Campaign key must include the reason so a later different-reason error triggers a fresh email.
            assert "model_not_allowed" in call_kwargs["campaign_key"]
            mock_message.send.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_skips_when_email_not_available(self, setup_data):
        team = setup_data["team"]

        with (
            patch("posthog.email.is_email_available", return_value=False),
            patch("posthog.email.EmailMessage") as mock_email_class,
        ):
            await send_evaluation_disabled_email_activity(
                SendEvaluationDisabledEmailInputs(
                    team_id=team.id,
                    evaluation_id="eval-123",
                    evaluation_name="My Eval",
                    status_reason="model_not_allowed",
                    human_readable_reason="reason",
                )
            )

            mock_email_class.assert_not_called()
