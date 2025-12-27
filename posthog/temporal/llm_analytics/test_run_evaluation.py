import json
import uuid
from datetime import datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team

from products.llm_analytics.backend.models.evaluations import Evaluation

from .run_evaluation import (
    BooleanEvalResult,
    BooleanWithNAEvalResult,
    RunEvaluationInputs,
    RunEvaluationWorkflow,
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
            assert result["output_config"] == {}

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

        # Mock OpenAI response
        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            mock_parsed = MagicMock()
            mock_parsed.verdict = True
            mock_parsed.reasoning = "The answer is correct"

            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.parsed = mock_parsed
            mock_client.beta.chat.completions.parse.return_value = mock_response

            result = await execute_llm_judge_activity(evaluation, event_data)

            assert result["verdict"] is True
            assert result["reasoning"] == "The answer is correct"
            mock_client.beta.chat.completions.parse.assert_called_once()

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
    async def test_execute_llm_judge_activity_boolean_with_na_applicable(self, setup_data):
        """Test LLM judge execution with boolean_with_na output type when applicable"""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Is this response factually accurate?"},
            "output_type": "boolean_with_na",
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

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            mock_parsed = MagicMock()
            mock_parsed.verdict = True
            mock_parsed.applicable = True
            mock_parsed.reasoning = "The answer is correct"

            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.parsed = mock_parsed
            mock_client.beta.chat.completions.parse.return_value = mock_response

            result = await execute_llm_judge_activity(evaluation, event_data)

            assert result["verdict"] is True
            assert result["applicable"] is True
            assert result["reasoning"] == "The answer is correct"
            assert result["output_type"] == "boolean_with_na"

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_llm_judge_activity_boolean_with_na_not_applicable(self, setup_data):
        """Test LLM judge execution with boolean_with_na output type when not applicable"""
        evaluation_obj = setup_data["evaluation"]
        team = setup_data["team"]

        evaluation = {
            "id": str(evaluation_obj.id),
            "name": "Test Evaluation",
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": "Check mathematical accuracy"},
            "output_type": "boolean_with_na",
            "output_config": {},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "Hello, how are you?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "I'm doing well, thanks!"}],
            },
        )

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            mock_parsed = MagicMock()
            mock_parsed.verdict = None
            mock_parsed.applicable = False
            mock_parsed.reasoning = "This is a greeting, not a math problem"

            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.parsed = mock_parsed
            mock_client.beta.chat.completions.parse.return_value = mock_response

            result = await execute_llm_judge_activity(evaluation, event_data)

            assert result["verdict"] is None
            assert result["applicable"] is False
            assert result["reasoning"] == "This is a greeting, not a math problem"
            assert result["output_type"] == "boolean_with_na"

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_emit_evaluation_event_activity_boolean_with_na_applicable(self, setup_data):
        """Test emitting evaluation event for applicable boolean_with_na result"""
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
            "output_type": "boolean_with_na",
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
                assert call_kwargs["properties"]["$ai_evaluation_output_type"] == "boolean_with_na"

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_emit_evaluation_event_activity_boolean_with_na_not_applicable(self, setup_data):
        """Test emitting evaluation event for not applicable boolean_with_na result"""
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
            "output_type": "boolean_with_na",
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
                assert call_kwargs["properties"]["$ai_evaluation_output_type"] == "boolean_with_na"


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
