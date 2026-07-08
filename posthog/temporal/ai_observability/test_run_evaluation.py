import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team
from posthog.temporal.ai_observability.sentiment.extraction import truncate_to_head_tail
from posthog.temporal.ai_observability.sentiment.schema import SentimentResult

from products.ai_observability.backend.llm.errors import (
    AuthenticationError,
    ModelNotFoundError,
    ModelPermissionError,
    QuotaExceededError,
    RateLimitError,
    StructuredOutputParseError,
)
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.model_configuration import LLMModelConfiguration
from products.ai_observability.backend.models.provider_keys import LLMProviderKey

from .evaluation_errors import (
    MAX_STATUS_REASON_DETAIL_LENGTH,
    require_user_error_spec,
    status_reason_detail_for_terminal_user_error,
    terminal_user_error_result_from_application_error,
)
from .evaluation_llm_judge import JUDGE_EVENT_MAX_CHARS
from .run_evaluation import (
    BooleanEvalResult,
    BooleanWithNAEvalResult,
    EmitEvaluationEventInputs,
    EvaluationActivityResult,
    ExecuteLLMJudgeInputs,
    RunEvaluationInputs,
    RunEvaluationWorkflow,
    SendEvaluationDisabledEmailInputs,
    SendTrialUsageEmailInputs,
    WorkflowResult,
    disable_evaluation_activity,
    emit_evaluation_event_activity,
    execute_hog_eval_activity,
    execute_llm_judge_activity,
    execute_sentiment_eval_activity,
    extract_event_tools,
    fetch_evaluation_activity,
    increment_trial_eval_count_activity,
    run_hog_eval,
    send_evaluation_disabled_email_activity,
    send_trial_usage_email_activity,
)


def test_status_reason_detail_for_terminal_user_error_only_keeps_truncated_hog_errors():
    hog_spec = require_user_error_spec("hog_error")
    permission_spec = require_user_error_spec("permission_error")
    long_message = "x" * (MAX_STATUS_REASON_DETAIL_LENGTH + 10)

    assert status_reason_detail_for_terminal_user_error(permission_spec, "provider denied") is None
    assert status_reason_detail_for_terminal_user_error(hog_spec, long_message) == (
        f"{long_message[: MAX_STATUS_REASON_DETAIL_LENGTH - 3]}..."
    )


def test_terminal_user_error_result_from_application_error_uses_key_details_for_byok_model_not_found():
    result = terminal_user_error_result_from_application_error(
        ApplicationError(
            "Model 'missing-model' not found.",
            {
                "error_type": "model_not_found",
                "key_id": "key-123",
                "provider": "openai",
                "model": "missing-model",
            },
            non_retryable=True,
        ),
        allows_na=False,
    )

    assert result is not None
    assert result["terminal_user_error"] is True
    assert result["skip_reason"] == "model_not_found"
    assert result["status_reason"] == "model_not_found"
    assert result["is_byok"] is True
    assert result["key_id"] == "key-123"
    assert result["provider"] == "openai"
    assert result["model"] == "missing-model"


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

        with patch(
            "posthog.temporal.ai_observability.evaluation_workflow_activities.Evaluation.objects.get"
        ) as mock_get:
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

    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity(self, setup_data):
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
        with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_parsed = BooleanEvalResult(verdict=True, reasoning="The answer is correct")

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

            assert result["verdict"] is True
            assert result["reasoning"] == "The answer is correct"
            mock_client.complete.assert_called_once()

    @pytest.mark.parametrize(
        "oversized_input",
        [
            pytest.param(
                [{"role": "user", "content": f"message {i}: " + "x" * 200} for i in range(3000)],
                id="many_lines",
            ),
            pytest.param([{"role": "user", "content": "x" * 600_000}], id="single_line_blob"),
        ],
    )
    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity_bounds_oversized_input(self, oversized_input, setup_data):
        team = setup_data["team"]
        evaluation_obj = setup_data["evaluation"]

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
                "$ai_input": oversized_input,
                "$ai_output_choices": [{"role": "assistant", "content": "ok"}],
            },
        )

        with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_response = MagicMock()
            mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="ok")
            mock_response.usage = MagicMock(input_tokens=1, output_tokens=1, total_tokens=1)
            mock_client.complete.return_value = mock_response

            execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

            sent_prompt = mock_client.complete.call_args.args[0].messages[0]["content"]
            raw_size = sum(len(message["content"]) for message in oversized_input)
            assert len(sent_prompt) <= JUDGE_EVENT_MAX_CHARS
            assert len(sent_prompt) < raw_size

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

        result: EvaluationActivityResult = {
            "result_type": "boolean",
            "verdict": True,
            "reasoning": "Test passed",
            "allows_na": False,
            "model": "gpt-5-mini",
            "provider": "openai",
            "input_tokens": 42,
            "output_tokens": 18,
        }

        with patch(
            "posthog.temporal.ai_observability.evaluation_workflow_activities.Team.objects.get"
        ) as mock_team_get:
            with patch(
                "posthog.temporal.ai_observability.evaluation_workflow_activities.capture_internal"
            ) as mock_capture:
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
                assert props["$ai_evaluation_result_type"] == "boolean"
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

        result: EvaluationActivityResult = {
            "result_type": "boolean",
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

        with patch(
            "posthog.temporal.ai_observability.evaluation_workflow_activities.Team.objects.get"
        ) as mock_team_get:
            with patch(
                "posthog.temporal.ai_observability.evaluation_workflow_activities.capture_internal"
            ) as mock_capture:
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
        assert props["$ai_evaluation_result_type"] == "boolean"
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

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_emit_evaluation_event_activity_sentiment_omits_boolean_and_cost_props(self, setup_data):
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Sentiment Evaluation",
            "evaluation_type": "sentiment",
        }
        event_data = create_mock_event_data(team.id, properties={"$ai_trace_id": "trace-1"})
        result: EvaluationActivityResult = {
            "result_type": "sentiment",
            "reasoning": "Classified 1 user message as positive.",
            "sentiment_label": "positive",
            "sentiment_score": 0.9,
            "sentiment_scores": {"positive": 0.9, "neutral": 0.08, "negative": 0.02},
            "sentiment_messages": {
                "0": {"label": "positive", "score": 0.9, "scores": {"positive": 0.9, "neutral": 0.08, "negative": 0.02}}
            },
            "sentiment_message_count": 1,
        }

        with patch(
            "posthog.temporal.ai_observability.evaluation_workflow_activities.Team.objects.get"
        ) as mock_team_get:
            with patch(
                "posthog.temporal.ai_observability.evaluation_workflow_activities.capture_internal"
            ) as mock_capture:
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

        assert props["$ai_evaluation_runtime"] == "sentiment"
        assert props["$ai_evaluation_result_type"] == "sentiment"
        assert props["$ai_sentiment_label"] == "positive"
        assert props["$ai_sentiment_score"] == 0.9
        assert props["$ai_sentiment_message_count"] == 1
        assert "$ai_evaluation_result" not in props
        assert "$ai_evaluation_allows_na" not in props
        assert "$ai_model" not in props
        assert "$ai_provider" not in props

    def test_parse_inputs(self):
        """Test that parse_inputs correctly parses workflow inputs"""
        event_data = create_mock_event_data(team_id=1)
        inputs = ["eval-123", json.dumps(event_data)]

        parsed = RunEvaluationWorkflow.parse_inputs(inputs)

        assert parsed.evaluation_id == "eval-123"
        assert parsed.event_data == event_data

    @pytest.mark.asyncio
    async def test_terminal_user_error_disables_emails_without_emitting_evaluation_event(self):
        calls: list[str] = []

        @activity.defn(name="fetch_evaluation_activity")
        async def mock_fetch_evaluation(inputs: RunEvaluationInputs) -> dict[str, Any]:
            calls.append("fetch")
            return {
                "id": inputs.evaluation_id,
                "name": "Hog eval",
                "evaluation_type": "hog",
                "evaluation_config": {},
                "output_type": "boolean",
                "output_config": {},
                "team_id": 1,
            }

        @activity.defn(name="execute_hog_eval_activity")
        async def mock_execute_hog_eval(
            evaluation: dict[str, Any], event_data: dict[str, Any]
        ) -> EvaluationActivityResult:
            calls.append("execute_hog")
            return {
                "result_type": "boolean",
                "verdict": False,
                "reasoning": "Must return boolean, got int: 42",
                "allows_na": False,
                "skipped": True,
                "skip_reason": "hog_error",
                "terminal_user_error": True,
                "status_reason": "hog_error",
            }

        @activity.defn(name="disable_evaluation_activity")
        async def mock_disable_evaluation(
            evaluation_id: str, team_id: int, reason: str, reason_detail: str | None = None
        ) -> bool:
            calls.append(f"disable:{evaluation_id}:{team_id}:{reason}:{reason_detail}")
            return True

        @activity.defn(name="send_evaluation_disabled_email_activity")
        async def mock_send_evaluation_disabled_email(inputs: SendEvaluationDisabledEmailInputs) -> None:
            calls.append(f"email:{inputs.evaluation_id}:{inputs.status_reason}:{inputs.human_readable_reason}")

        @activity.defn(name="emit_evaluation_event_activity")
        async def mock_emit_evaluation_event(inputs: EmitEvaluationEventInputs) -> None:
            calls.append("emit")
            raise AssertionError("terminal user errors must not emit $ai_evaluation")

        task_queue = str(uuid.uuid4())
        evaluation_id = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunEvaluationWorkflow],
                activities=[
                    mock_fetch_evaluation,
                    mock_execute_hog_eval,
                    mock_disable_evaluation,
                    mock_send_evaluation_disabled_email,
                    mock_emit_evaluation_event,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result: WorkflowResult = await env.client.execute_workflow(
                    RunEvaluationWorkflow.run,
                    RunEvaluationInputs(
                        evaluation_id=evaluation_id,
                        event_data=create_mock_event_data(team_id=1),
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert calls == [
            "fetch",
            "execute_hog",
            f"disable:{evaluation_id}:1:hog_error:Must return boolean, got int: 42",
            (
                f"email:{evaluation_id}:hog_error:"
                "The Hog evaluation code failed. Fix the code before re-enabling this evaluation."
            ),
        ]
        assert result["evaluation_id"] == evaluation_id
        assert result["evaluation_type"] == "hog"
        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_error"
        assert result["message"] == "Must return boolean, got int: 42"

    @pytest.mark.asyncio
    async def test_terminal_user_error_does_not_email_when_evaluation_was_already_disabled(self):
        calls: list[str] = []

        @activity.defn(name="fetch_evaluation_activity")
        async def mock_fetch_evaluation(inputs: RunEvaluationInputs) -> dict[str, Any]:
            calls.append("fetch")
            return {
                "id": inputs.evaluation_id,
                "name": "Hog eval",
                "evaluation_type": "hog",
                "evaluation_config": {},
                "output_type": "boolean",
                "output_config": {},
                "team_id": 1,
            }

        @activity.defn(name="execute_hog_eval_activity")
        async def mock_execute_hog_eval(
            evaluation: dict[str, Any], event_data: dict[str, Any]
        ) -> EvaluationActivityResult:
            calls.append("execute_hog")
            return {
                "result_type": "boolean",
                "verdict": False,
                "reasoning": "Must return boolean, got int: 42",
                "allows_na": False,
                "skipped": True,
                "skip_reason": "hog_error",
                "terminal_user_error": True,
                "status_reason": "hog_error",
            }

        @activity.defn(name="disable_evaluation_activity")
        async def mock_disable_evaluation(
            evaluation_id: str, team_id: int, reason: str, reason_detail: str | None = None
        ) -> bool:
            calls.append(f"disable:{evaluation_id}:{team_id}:{reason}:{reason_detail}")
            return False

        @activity.defn(name="send_evaluation_disabled_email_activity")
        async def mock_send_evaluation_disabled_email(inputs: SendEvaluationDisabledEmailInputs) -> None:
            calls.append("email")
            raise AssertionError("already-disabled terminal errors must not send another email")

        task_queue = str(uuid.uuid4())
        evaluation_id = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunEvaluationWorkflow],
                activities=[
                    mock_fetch_evaluation,
                    mock_execute_hog_eval,
                    mock_disable_evaluation,
                    mock_send_evaluation_disabled_email,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result: WorkflowResult = await env.client.execute_workflow(
                    RunEvaluationWorkflow.run,
                    RunEvaluationInputs(
                        evaluation_id=evaluation_id,
                        event_data=create_mock_event_data(team_id=1),
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

        assert calls == [
            "fetch",
            "execute_hog",
            f"disable:{evaluation_id}:1:hog_error:Must return boolean, got int: 42",
        ]
        assert result["evaluation_id"] == evaluation_id
        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_error"

    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity_allows_na_applicable(self, setup_data):
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

        with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_parsed = BooleanWithNAEvalResult(verdict=True, applicable=True, reasoning="The answer is correct")

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

            assert result["verdict"] is True
            assert result["applicable"] is True
            assert result["reasoning"] == "The answer is correct"
            assert result["allows_na"] is True

    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity_allows_na_not_applicable(self, setup_data):
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

        with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_parsed = BooleanWithNAEvalResult(
                verdict=None, applicable=False, reasoning="This is a greeting, not a math problem"
            )

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

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
    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity_skips_errored_traces(self, ai_is_error_value: bool | str, setup_data):
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

        with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
            result = execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

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

    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity_skips_errored_trace_with_allows_na(self, setup_data):
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

        with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
            result = execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

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
    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity_does_not_skip_when_not_errored(self, error_props: dict[str, Any], setup_data):
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

        with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_response = MagicMock()
            mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="Correct")
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

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

        result: EvaluationActivityResult = {
            "result_type": "boolean",
            "verdict": True,
            "reasoning": "Test passed",
            "applicable": True,
            "allows_na": True,
        }

        with patch(
            "posthog.temporal.ai_observability.evaluation_workflow_activities.Team.objects.get"
        ) as mock_team_get:
            with patch(
                "posthog.temporal.ai_observability.evaluation_workflow_activities.capture_internal"
            ) as mock_capture:
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
                assert props["$ai_evaluation_result_type"] == "boolean"
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

        result: EvaluationActivityResult = {
            "result_type": "boolean",
            "verdict": None,
            "reasoning": "Not applicable",
            "applicable": False,
            "allows_na": True,
        }

        with patch(
            "posthog.temporal.ai_observability.evaluation_workflow_activities.Team.objects.get"
        ) as mock_team_get:
            with patch(
                "posthog.temporal.ai_observability.evaluation_workflow_activities.capture_internal"
            ) as mock_capture:
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
                assert props["$ai_evaluation_result_type"] == "boolean"
                assert "$ai_evaluation_result" not in props
                assert props["$ai_evaluation_applicable"] is False
                assert props["$ai_evaluation_allows_na"] is True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_disable_evaluation_activity(self, setup_data):
        from posthog.models.activity_logging.activity_log import ActivityLog

        evaluation = setup_data["evaluation"]
        team = setup_data["team"]

        assert evaluation.enabled

        disabled = await disable_evaluation_activity(
            str(evaluation.id), team.id, "hog_error", "Must return boolean, got int: 42"
        )

        await sync_to_async(evaluation.refresh_from_db)()
        assert disabled is True
        assert not evaluation.enabled
        assert evaluation.status == "error"
        assert evaluation.status_reason == "hog_error"
        assert evaluation.status_reason_detail == "Must return boolean, got int: 42"

        logs = await sync_to_async(
            lambda: list(ActivityLog.objects.filter(scope="Evaluation", item_id=str(evaluation.id), activity="updated"))
        )()
        assert len(logs) == 1
        detail = logs[0].detail
        assert detail is not None
        fields = {c["field"]: c for c in detail["changes"]}
        assert fields["status"]["before"] == "active"
        assert fields["status"]["after"] == "error"
        assert fields["status_reason"]["after"] == "hog_error"
        assert fields["status_reason_detail"]["after"] == "Must return boolean, got int: 42"
        assert logs[0].is_system is True

        disabled_again = await disable_evaluation_activity(
            str(evaluation.id), team.id, "hog_error", "Must return boolean, got int: 42"
        )

        logs_after_retry = await sync_to_async(
            lambda: ActivityLog.objects.filter(
                scope="Evaluation", item_id=str(evaluation.id), activity="updated"
            ).count()
        )()
        assert disabled_again is False
        assert logs_after_retry == 1

    @pytest.mark.django_db(transaction=True)
    def test_successful_execution_does_not_disable_evaluation(self, setup_data):
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

        with patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_response = MagicMock()
            mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="Correct")
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation_dict, event_data=event_data))

        evaluation.refresh_from_db()
        assert evaluation.enabled is True

    def test_execute_llm_judge_activity_parse_error_raises_non_retryable(self):
        evaluation = {
            "id": "eval-123",
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this response factually accurate?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": 1,
            "model_configuration": {
                "provider": "openai",
                "model": "gpt-4.1",
                "provider_key_id": None,
            },
        }

        event_data = create_mock_event_data(
            1,
            properties={
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "4"}],
            },
        )

        with (
            patch(
                "posthog.temporal.ai_observability.model_resolution.EvaluationConfig.objects.get_or_create"
            ) as mock_get_or_create,
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class,
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.increment_errors") as mock_increment_errors,
        ):
            mock_get_or_create.return_value = (
                MagicMock(active_provider_key=None, trial_evals_used=0, trial_eval_limit=100),
                False,
            )
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.complete.side_effect = StructuredOutputParseError(
                "Failed to parse structured output: I need to fetch your bundles..."
            )

            with pytest.raises(ApplicationError, match="Failed to parse structured output") as exc_info:
                execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

        mock_increment_errors.assert_called_once_with("parse_error", provider="openai")
        assert exc_info.value.non_retryable is True
        assert exc_info.value.details[0] == {"error_type": "parse_error"}

    @pytest.mark.parametrize(
        "raised_exception, expected_label",
        [
            pytest.param(RuntimeError("network down"), "RuntimeError", id="runtime_error"),
            pytest.param(ValueError("bad payload"), "ValueError", id="value_error"),
            pytest.param(TimeoutError("read timeout"), "TimeoutError", id="timeout_error"),
        ],
    )
    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity_unhandled_exception_uses_class_name(
        self, raised_exception: Exception, expected_label: str, setup_data
    ):
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this accurate?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }
        event_data = create_mock_event_data(team.id)

        with (
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class,
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.increment_errors") as mock_increment_errors,
        ):
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.complete.side_effect = raised_exception

            with pytest.raises(type(raised_exception)):
                execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

            mock_increment_errors.assert_called_once_with(expected_label, provider="openai")

    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity_rejects_non_trial_model_on_posthog_key(self, setup_data):
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
                "model": "gpt-5.4",
                "provider_key_id": None,
            },
        }

        event_data = create_mock_event_data(team.id)

        with (
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class,
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.increment_user_errors") as mock_user_errors,
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.increment_errors") as mock_errors,
        ):
            result = execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

        mock_client_class.assert_not_called()
        mock_user_errors.assert_called_once_with("model_not_allowed", provider=None)
        mock_errors.assert_not_called()
        assert result["terminal_user_error"] is True
        assert result["skipped"] is True
        assert result["skip_reason"] == "model_not_allowed"
        assert result["status_reason"] == "model_not_allowed"
        assert result["verdict"] is None

    @pytest.mark.parametrize(
        "raised_exception, skip_reason, status_reason, provider_key_state",
        [
            pytest.param(
                AuthenticationError(),
                "auth_error",
                "provider_key_invalid",
                LLMProviderKey.State.INVALID,
                id="auth_error",
            ),
            pytest.param(
                ModelPermissionError("gpt-5.4"),
                "permission_error",
                "provider_key_permission_denied",
                LLMProviderKey.State.ERROR,
                id="permission_error",
            ),
            pytest.param(
                QuotaExceededError(),
                "quota_error",
                "provider_key_quota_exceeded",
                LLMProviderKey.State.ERROR,
                id="quota_error",
            ),
            pytest.param(
                RateLimitError(),
                "rate_limit",
                "provider_key_rate_limited",
                LLMProviderKey.State.ERROR,
                id="rate_limit",
            ),
            pytest.param(
                ModelNotFoundError("gpt-5.4"),
                "model_not_found",
                "model_not_found",
                None,
                id="model_not_found",
            ),
        ],
    )
    @pytest.mark.django_db(transaction=True)
    def test_execute_llm_judge_activity_byok_provider_user_errors_return_terminal_result(
        self,
        raised_exception: Exception,
        skip_reason: str,
        status_reason: str,
        provider_key_state: str | None,
        setup_data,
    ):
        team = setup_data["team"]
        provider_key = LLMProviderKey.objects.create(
            team=team,
            provider="openai",
            name="OpenAI",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
        )

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
                "model": "gpt-5.4",
                "provider_key_id": str(provider_key.id),
            },
        }
        event_data = create_mock_event_data(team.id)

        with (
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class,
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.increment_user_errors") as mock_user_errors,
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.increment_errors") as mock_errors,
        ):
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.complete.side_effect = raised_exception

            result = execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

        mock_client.complete.assert_called_once()
        mock_user_errors.assert_called_once_with(skip_reason, provider="openai")
        mock_errors.assert_not_called()
        assert result["terminal_user_error"] is True
        assert result["skipped"] is True
        assert result["skip_reason"] == skip_reason
        assert result["status_reason"] == status_reason
        assert result["is_byok"] is True
        assert result["key_id"] == str(provider_key.id)
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-5.4"
        if provider_key_state is None:
            assert "provider_key_state" not in result
        else:
            assert result["provider_key_state"] == provider_key_state


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
    async def test_hog_eval_non_bool_returns_skipped(self, setup_data):
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

        # A non-boolean result is a user-authored Hog error: recorded as skipped, not raised.
        result = await execute_hog_eval_activity(evaluation, event_data)

        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_error"
        assert result["terminal_user_error"] is True
        assert result["status_reason"] == "hog_error"
        assert "Must return boolean" in result["reasoning"]

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

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_hog_eval_runtime_error_returns_skipped(self, setup_data):
        team = setup_data["team"]

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

        # A HogVM runtime error in user-authored Hog (e.g. unsupported function, unknown global)
        # is recorded as skipped, not raised — so it never reaches error tracking.
        user_error = {"verdict": None, "reasoning": "", "error": "Runtime error: Global variable not found: continue"}
        with patch(
            "posthog.temporal.ai_observability.evaluation_hog.run_hog_eval",
            return_value=user_error,
        ):
            result = await execute_hog_eval_activity(evaluation, event_data)

        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_error"
        assert result["terminal_user_error"] is True
        assert result["status_reason"] == "hog_error"
        assert "Global variable not found" in result["reasoning"]

    @pytest.mark.asyncio
    async def test_hog_eval_length_null_returns_skipped(self):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return length(null) > 0", "destination")
        evaluation = {
            "id": "eval-id",
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return length(null) > 0", "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": 1,
        }

        result = await execute_hog_eval_activity(evaluation, create_mock_event_data(1))

        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_error"
        assert result["terminal_user_error"] is True
        assert result["status_reason"] == "hog_error"
        assert result["verdict"] is False
        assert "Runtime error: Can not call length on null" in result["reasoning"]
        assert "TypeError" not in result["reasoning"]
        assert "NoneType" not in result["reasoning"]

    @pytest.mark.asyncio
    async def test_hog_eval_comparison_type_error_returns_skipped(self):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return properties.missing <= 1.0", "destination")
        evaluation = {
            "id": "eval-id",
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return properties.missing <= 1.0", "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": 1,
        }

        result = await execute_hog_eval_activity(evaluation, create_mock_event_data(1))

        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_error"
        assert result["terminal_user_error"] is True
        assert result["status_reason"] == "hog_error"
        assert result["verdict"] is False
        assert "Runtime error: '<=' not supported between instances of 'NoneType' and 'float'" in result["reasoning"]
        assert "Unexpected error during evaluation" not in result["reasoning"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("source", "properties", "expected_reasoning"),
        [
            (
                "return output =~ properties.pattern",
                {"pattern": "\\u"},
                "Invalid regex pattern",
            ),
            (
                "return match(properties.tool_calls, 'tool')",
                {"tool_calls": ["tool_call"]},
                "Function match requires input",
            ),
            (
                "let calls := []; calls[1] := 'tool_call'; return true",
                {},
                "Index 1 out of range",
            ),
        ],
        ids=["invalid-regex", "list-regex-input", "array-assignment-index"],
    )
    async def test_hog_eval_vm_user_errors_return_skipped(self, source, properties, expected_reasoning):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog(source, "destination")
        evaluation = {
            "id": "eval-id",
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": source, "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": 1,
        }
        event_properties = {"$ai_input": "test input", "$ai_output": "test output", **properties}

        result = await execute_hog_eval_activity(evaluation, create_mock_event_data(1, properties=event_properties))

        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_error"
        assert result["terminal_user_error"] is True
        assert result["status_reason"] == "hog_error"
        assert result["verdict"] is False
        assert expected_reasoning in result["reasoning"]
        assert "Unexpected error during evaluation" not in result["reasoning"]

    @pytest.mark.asyncio
    async def test_hog_eval_unexpected_error_raises(self):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return true", "destination")

        evaluation = {
            "id": "eval-id",
            "name": "Hog Eval",
            "evaluation_type": "hog",
            "evaluation_config": {"source": "return true", "bytecode": bytecode},
            "output_type": "boolean",
            "output_config": {},
            "team_id": 1,
        }

        event_data = create_mock_event_data(1)

        # An unexpected error is a bug in our code, so it must still surface to error tracking.
        unexpected_error = {
            "verdict": None,
            "reasoning": "",
            "error": "Unexpected error during evaluation: KeyError: 'foo'",
            "unexpected": True,
        }
        with patch(
            "posthog.temporal.ai_observability.evaluation_hog.run_hog_eval",
            return_value=unexpected_error,
        ):
            with pytest.raises(ApplicationError, match="Unexpected error during evaluation"):
                await execute_hog_eval_activity(evaluation, event_data)


class TestExecuteSentimentEvalActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_sentiment_eval_classifies_user_messages(self, setup_data):
        team = setup_data["team"]
        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Sentiment Eval",
            "evaluation_type": "sentiment",
            "evaluation_config": {"source": "user_messages"},
            "output_type": "sentiment",
            "output_config": {},
            "team_id": team.id,
        }
        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [
                    {"role": "system", "content": "Be helpful."},
                    {"role": "user", "content": "I love this answer."},
                    {"role": "assistant", "content": "Thanks!"},
                ],
                "$ai_output": "Thanks!",
            },
        )

        classification = SentimentResult(
            label="positive",
            score=0.9,
            scores={"positive": 0.9, "neutral": 0.08, "negative": 0.02},
        )
        with patch(
            "posthog.temporal.ai_observability.sentiment.model.classify", return_value=[classification]
        ) as mock_classify:
            result = await execute_sentiment_eval_activity(evaluation, event_data)

        mock_classify.assert_called_once_with(["I love this answer."])
        assert "verdict" not in result
        assert result["sentiment_label"] == "positive"
        assert result["sentiment_score"] == 0.9
        assert result["sentiment_message_count"] == 1
        assert result["sentiment_messages"]["1"]["label"] == "positive"

    @pytest.mark.asyncio
    async def test_sentiment_eval_classifies_only_last_user_message(self):
        evaluation = {
            "id": "sentiment-eval-id",
            "name": "Sentiment Eval",
            "evaluation_type": "sentiment",
            "evaluation_config": {"source": "user_messages"},
            "output_type": "sentiment",
            "output_config": {},
            "team_id": 1,
        }
        last_message = ("I am really frustrated. " * 20) + ("Here are logs: " * 80) + "please fix this"
        event_data = create_mock_event_data(
            1,
            properties={
                "$ai_input": [
                    {"role": "user", "content": "Earlier context that should not be classified."},
                    {"role": "assistant", "content": "Can you share more detail?"},
                    {"role": "user", "content": last_message},
                ],
                "$ai_output": "I can help.",
            },
        )

        classification = SentimentResult(
            label="negative",
            score=0.8,
            scores={"positive": 0.05, "neutral": 0.15, "negative": 0.8},
        )
        with patch(
            "posthog.temporal.ai_observability.sentiment.model.classify", return_value=[classification]
        ) as mock_classify:
            result = await execute_sentiment_eval_activity(evaluation, event_data)

        mock_classify.assert_called_once_with([truncate_to_head_tail(last_message)])
        assert result["sentiment_label"] == "negative"
        assert result["sentiment_message_count"] == 1
        assert result["sentiment_messages"]["2"]["label"] == "negative"

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_sentiment_eval_defaults_to_neutral_without_user_messages(self, setup_data):
        team = setup_data["team"]
        evaluation = {
            "id": str(setup_data["evaluation"].id),
            "name": "Sentiment Eval",
            "evaluation_type": "sentiment",
            "evaluation_config": {"source": "user_messages"},
            "output_type": "sentiment",
            "output_config": {},
            "team_id": team.id,
        }
        event_data = create_mock_event_data(
            team.id,
            properties={"$ai_input": [{"role": "assistant", "content": "Hello"}]},
        )

        with patch("posthog.temporal.ai_observability.sentiment.model.classify") as mock_classify:
            result = await execute_sentiment_eval_activity(evaluation, event_data)

        mock_classify.assert_not_called()
        assert "verdict" not in result
        assert result["sentiment_label"] == "neutral"
        assert result["sentiment_message_count"] == 0


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
    async def test_hog_eval_null_return_without_allows_na_returns_skipped(self, setup_data):
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

        result = await execute_hog_eval_activity(evaluation, event_data)

        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_error"
        assert result["terminal_user_error"] is True
        assert result["status_reason"] == "hog_error"
        assert result["verdict"] is False
        assert "Must return boolean" in result["reasoning"]


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
            (50, "ai_observability_trial_warning"),
            (75, "ai_observability_trial_warning"),
            (100, "ai_observability_trial_exhausted"),
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
                    disabled_at=datetime(2026, 6, 25, 12, 0, 0, tzinfo=UTC),
                )
            )

            mock_email_class.assert_called_once()
            call_kwargs = mock_email_class.call_args[1]
            assert call_kwargs["template_name"] == "ai_observability_evaluation_disabled"
            assert call_kwargs["template_context"]["evaluation_name"] == "My Eval"
            assert "isn't available on the trial plan" in call_kwargs["template_context"]["disabled_reason"]
            # Campaign key must include the reason so a later different-reason error triggers a fresh email.
            assert "model_not_allowed" in call_kwargs["campaign_key"]
            # It also includes the disable timestamp so a later same-reason disable sends a fresh email.
            assert "1782388800000000" in call_kwargs["campaign_key"]
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


class TestExtractEventTools:
    def test_returns_tools_when_property_present(self):
        properties = {
            "$ai_tools": [{"type": "function", "function": {"name": "send_email", "description": "Send email"}}],
        }
        tools = extract_event_tools(properties)
        assert tools is not None
        assert isinstance(tools, list)
        assert tools[0]["function"]["name"] == "send_email"

    def test_returns_none_when_property_missing(self):
        assert extract_event_tools({}) is None


class TestJudgePromptAssembly:
    """Asserts on the actual user prompt sent to the judge — guards against
    regressions in section ordering, tool catalog inclusion, and tool_call_id
    correlation that the unit tests for the helpers can't catch alone."""

    def test_prompt_contains_input_tools_and_output_sections_in_order(self):
        evaluation = {
            "id": "eval-123",
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Did the agent call the right tool?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": 1,
        }
        event_data = create_mock_event_data(
            1,
            properties={
                "$ai_input": [
                    {"role": "user", "content": "Send the welcome email."},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "send_email", "arguments": '{"to": "x@y.com"}'},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
                ],
                "$ai_output_choices": [{"role": "assistant", "content": "Done."}],
                "$ai_tools": [
                    {"type": "function", "function": {"name": "send_email", "description": "Send an email."}},
                    {"type": "function", "function": {"name": "lookup_user", "description": "Look up a user."}},
                ],
            },
        )

        with (
            patch(
                "posthog.temporal.ai_observability.model_resolution.EvaluationConfig.objects.get_or_create"
            ) as mock_get_or_create,
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class,
        ):
            mock_get_or_create.return_value = (
                MagicMock(active_provider_key=None, trial_evals_used=0, trial_eval_limit=100),
                False,
            )
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_response = MagicMock()
            mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="ok")
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

        completion_request = mock_client.complete.call_args[0][0]
        user_prompt = completion_request.messages[0]["content"]

        # Section ordering: Input first, then Tools available, then Output.
        input_idx = user_prompt.index("Input:")
        tools_idx = user_prompt.index("Tools available:")
        output_idx = user_prompt.index("Output:")
        assert input_idx < tools_idx < output_idx

        # Tool calls and their results are paired via tool_call_id.
        assert "tool_call call_1: send_email" in user_prompt
        assert "tool[call_1]: ok" in user_prompt

        # Tool catalog is rendered compactly, one entry per line.
        assert "- send_email: Send an email." in user_prompt
        assert "- lookup_user: Look up a user." in user_prompt

    def test_prompt_omits_tools_section_when_catalog_absent(self):
        evaluation = {
            "id": "eval-123",
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this correct?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": 1,
        }
        event_data = create_mock_event_data(
            1,
            properties={
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "4"}],
            },
        )

        with (
            patch(
                "posthog.temporal.ai_observability.model_resolution.EvaluationConfig.objects.get_or_create"
            ) as mock_get_or_create,
            patch("posthog.temporal.ai_observability.evaluation_llm_judge.Client") as mock_client_class,
        ):
            mock_get_or_create.return_value = (
                MagicMock(active_provider_key=None, trial_evals_used=0, trial_eval_limit=100),
                False,
            )
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_response = MagicMock()
            mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="ok")
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            execute_llm_judge_activity(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=event_data))

        user_prompt = mock_client.complete.call_args[0][0].messages[0]["content"]
        assert "Tools available:" not in user_prompt
        assert "Input:" in user_prompt
        assert "Output:" in user_prompt
