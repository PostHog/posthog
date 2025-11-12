import json
import uuid
from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team

from products.llm_analytics.backend.models.evaluations import Evaluation

from .run_evaluation import (
    RunEvaluationInputs,
    emit_evaluation_event_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
    fetch_target_event_activity,
)


@pytest.fixture
def setup_data(db):
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
    async def test_fetch_target_event_activity(self, setup_data):
        """Test fetching target event from ClickHouse"""
        evaluation = setup_data["evaluation"]
        team = setup_data["team"]

        # Create a test event
        event_id = str(uuid.uuid4())

        with patch("posthog.temporal.llm_analytics.run_evaluation.sync_execute") as mock_execute:
            person_id = uuid.uuid4()
            mock_execute.return_value = [
                (
                    event_id,
                    "$ai_generation",
                    json.dumps({"$ai_input": "test input", "$ai_output": "test output"}),
                    datetime.now(),
                    team.id,
                    "test-user",
                    person_id,
                )
            ]

            timestamp = datetime.now().isoformat()
            inputs = RunEvaluationInputs(
                evaluation_id=str(evaluation.id), target_event_id=event_id, timestamp=timestamp
            )

            result = await fetch_target_event_activity(inputs, team.id)

            assert result["uuid"] == event_id
            assert result["event"] == "$ai_generation"
            assert result["team_id"] == team.id

            # Verify team_id was passed to the query
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            assert call_args[0][1]["team_id"] == team.id

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_fetch_evaluation_activity(self, setup_data):
        """Test fetching evaluation from database"""
        evaluation = setup_data["evaluation"]
        team = setup_data["team"]

        timestamp = datetime.now().isoformat()
        inputs = RunEvaluationInputs(
            evaluation_id=str(evaluation.id), target_event_id=str(uuid.uuid4()), timestamp=timestamp
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

        # Use realistic message array format like actual LLM events
        event_data = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "properties": {
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "4"}],
            },
            "team_id": team.id,
        }

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

        event_data = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "team_id": team.id,
            "distinct_id": "test-user",
            "properties": {},
            "person_id": str(uuid.uuid4()),
        }

        result = {"verdict": True, "reasoning": "Test passed"}

        with patch("posthog.temporal.llm_analytics.run_evaluation.Team.objects.get") as mock_team_get:
            with patch("posthog.temporal.llm_analytics.run_evaluation.create_event") as mock_create:
                mock_team_get.return_value = team

                await emit_evaluation_event_activity(evaluation, event_data, result, start_time=datetime.now())

                mock_create.assert_called_once()
                call_kwargs = mock_create.call_args[1]
                assert call_kwargs["event"] == "$ai_evaluation"
                assert call_kwargs["properties"]["$ai_evaluation_result"] is True
