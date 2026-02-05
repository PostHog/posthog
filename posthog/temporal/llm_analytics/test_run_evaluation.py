import json
import uuid
from datetime import datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async

from posthog.models import Organization, Team

from products.llm_analytics.backend.models.evaluations import Evaluation

from .run_evaluation import (
    BooleanEvalResult,
    BooleanWithNAEvalResult,
    RunEvaluationInputs,
    RunEvaluationWorkflow,
    disable_evaluation_activity,
    emit_evaluation_event_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
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

            result = await execute_llm_judge_activity(evaluation, event_data)

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

        event_data = create_mock_event_data(
            team.id,
            properties={},
            person_id=str(uuid.uuid4()),
        )

        result = {"verdict": True, "reasoning": "Test passed"}

        with patch("posthog.temporal.llm_analytics.run_evaluation.Team.objects.get") as mock_team_get:
            with patch("posthog.temporal.llm_analytics.run_evaluation.create_event") as mock_create:
                mock_team_get.return_value = team

                await emit_evaluation_event_activity(evaluation, event_data, result, start_time=datetime.now())

                mock_create.assert_called_once()
                call_kwargs = mock_create.call_args[1]
                assert call_kwargs["event"] == "$ai_evaluation"
                assert call_kwargs["properties"]["$ai_evaluation_result"] is True

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

            result = await execute_llm_judge_activity(evaluation, event_data)

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

            result = await execute_llm_judge_activity(evaluation, event_data)

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

        event_data = create_mock_event_data(
            team.id,
            properties={},
            person_id=str(uuid.uuid4()),
        )

        result = {
            "verdict": True,
            "reasoning": "Test passed",
            "applicable": True,
            "allows_na": True,
        }

        with patch("posthog.temporal.llm_analytics.run_evaluation.Team.objects.get") as mock_team_get:
            with patch("posthog.temporal.llm_analytics.run_evaluation.create_event") as mock_create:
                mock_team_get.return_value = team

                await emit_evaluation_event_activity(evaluation, event_data, result, start_time=datetime.now())

                mock_create.assert_called_once()
                call_kwargs = mock_create.call_args[1]
                assert call_kwargs["event"] == "$ai_evaluation"
                assert call_kwargs["properties"]["$ai_evaluation_result"] is True
                assert call_kwargs["properties"]["$ai_evaluation_applicable"] is True
                assert call_kwargs["properties"]["$ai_evaluation_allows_na"] is True

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

        event_data = create_mock_event_data(
            team.id,
            properties={},
            person_id=str(uuid.uuid4()),
        )

        result = {
            "verdict": None,
            "reasoning": "Not applicable",
            "applicable": False,
            "allows_na": True,
        }

        with patch("posthog.temporal.llm_analytics.run_evaluation.Team.objects.get") as mock_team_get:
            with patch("posthog.temporal.llm_analytics.run_evaluation.create_event") as mock_create:
                mock_team_get.return_value = team

                await emit_evaluation_event_activity(evaluation, event_data, result, start_time=datetime.now())

                mock_create.assert_called_once()
                call_kwargs = mock_create.call_args[1]
                assert call_kwargs["event"] == "$ai_evaluation"
                # Result should not be set when not applicable
                assert "$ai_evaluation_result" not in call_kwargs["properties"]
                assert call_kwargs["properties"]["$ai_evaluation_applicable"] is False
                assert call_kwargs["properties"]["$ai_evaluation_allows_na"] is True

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

            await execute_llm_judge_activity(evaluation_dict, event_data)

        await sync_to_async(evaluation.refresh_from_db)()
        assert evaluation.enabled is True


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
