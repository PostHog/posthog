import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team

from products.llm_analytics.backend.llm.errors import StructuredOutputParseError
from products.llm_analytics.backend.models.evaluation_config import EvaluationConfig
from products.llm_analytics.backend.models.evaluations import Evaluation
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

from .run_evaluation import (
    BooleanEvalResult,
    BooleanWithNAEvalResult,
    EmitEvaluationEventInputs,
    ExecuteLLMJudgeInputs,
    RunEvaluationInputs,
    RunEvaluationWorkflow,
    disable_evaluation_activity,
    emit_evaluation_event_activity,
    execute_hog_eval_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
    run_hog_eval,
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

        result = {
            "verdict": True,
            "reasoning": "Test passed",
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

        result = {
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

        result = {
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

        assert evaluation.enabled is True

        await disable_evaluation_activity(str(evaluation.id), team.id)

        await sync_to_async(evaluation.refresh_from_db)()
        assert evaluation.enabled is False

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


class TestDynamicKeyResolution:
    """When no explicit provider_key_id is set on an evaluation, the runtime
    resolves the best available key: BYOK preferred over trial."""

    @staticmethod
    def _make_evaluation(evaluation_obj, team, model_configuration=None):
        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this accurate?"},
            "output_type": "boolean",
            "output_config": {},
            "team_id": team.id,
        }
        if model_configuration is not None:
            evaluation["model_configuration"] = model_configuration
        return evaluation

    @staticmethod
    def _make_event_data(team):
        return create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "test"}],
                "$ai_output_choices": [{"role": "assistant", "content": "response"}],
            },
        )

    @staticmethod
    def _mock_llm_client():
        return patch("posthog.temporal.llm_analytics.run_evaluation.Client")

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize(
        "byok_provider,byok_state,trial_used,has_model_config,expected_is_byok",
        [
            ("openai", LLMProviderKey.State.OK, 0, True, True),
            ("anthropic", LLMProviderKey.State.OK, 0, True, False),
            ("openai", LLMProviderKey.State.OK, 100, True, True),
            ("openai", LLMProviderKey.State.INVALID, 0, True, False),
            ("openai", LLMProviderKey.State.OK, 0, False, True),
        ],
        ids=[
            "byok_preferred_over_trial",
            "wrong_provider_falls_back_to_trial",
            "trial_exhausted_uses_byok",
            "unhealthy_key_falls_back_to_trial",
            "legacy_path_prefers_byok",
        ],
    )
    async def test_key_resolution(
        self, setup_data, byok_provider, byok_state, trial_used, has_model_config, expected_is_byok
    ):
        team = setup_data["team"]

        byok_key = await sync_to_async(LLMProviderKey.objects.create)(
            team=team,
            provider=byok_provider,
            name="Test Key",
            state=byok_state,
            encrypted_config={"api_key": "sk-test"},
        )

        if trial_used:
            config, _ = await sync_to_async(EvaluationConfig.objects.get_or_create)(team_id=team.id)
            config.trial_evals_used = trial_used
            await sync_to_async(config.save)(update_fields=["trial_evals_used"])

        model_config = (
            {"provider": "openai", "model": "gpt-5-mini", "provider_key_id": None} if has_model_config else None
        )
        evaluation = self._make_evaluation(setup_data["evaluation"], team, model_configuration=model_config)

        with self._mock_llm_client() as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_response = MagicMock()
            mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="Good")
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = await execute_llm_judge_activity(
                ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=self._make_event_data(team))
            )

            assert result["is_byok"] is expected_is_byok
            if expected_is_byok:
                assert result["key_id"] == str(byok_key.id)
            else:
                assert result["key_id"] is None

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_trial_exhausted_without_byok_key_raises(self, setup_data):
        team = setup_data["team"]

        config, _ = await sync_to_async(EvaluationConfig.objects.get_or_create)(team_id=team.id)
        config.trial_evals_used = 100
        await sync_to_async(config.save)(update_fields=["trial_evals_used"])

        evaluation = self._make_evaluation(
            setup_data["evaluation"],
            team,
            model_configuration={"provider": "openai", "model": "gpt-5-mini", "provider_key_id": None},
        )

        with pytest.raises(ApplicationError, match="Trial evaluation limit"):
            await execute_llm_judge_activity(
                ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=self._make_event_data(team))
            )

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_most_recently_used_byok_key_preferred(self, setup_data):
        team = setup_data["team"]
        now = timezone.now()

        older_key = await sync_to_async(LLMProviderKey.objects.create)(
            team=team,
            provider="openai",
            name="Recently Used Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-old"},
            last_used_at=now - timedelta(minutes=5),
        )
        await sync_to_async(LLMProviderKey.objects.create)(
            team=team,
            provider="openai",
            name="Never Used Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-new"},
            last_used_at=None,
        )

        evaluation = self._make_evaluation(
            setup_data["evaluation"],
            team,
            model_configuration={"provider": "openai", "model": "gpt-5-mini", "provider_key_id": None},
        )

        with self._mock_llm_client() as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_response = MagicMock()
            mock_response.parsed = BooleanEvalResult(verdict=True, reasoning="Good")
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            result = await execute_llm_judge_activity(
                ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=self._make_event_data(team))
            )

            assert result["is_byok"] is True
            assert result["key_id"] == str(older_key.id)


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
