import json
import uuid
from datetime import datetime

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from products.llm_analytics.backend.models.evaluations import Evaluation

from .run_evaluation import (
    RunEvaluationInputs,
    emit_evaluation_event_activity,
    execute_llm_judge_activity,
    fetch_evaluation_activity,
    fetch_target_event_activity,
)


class TestRunEvaluationWorkflow(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            prompt="Is this response factually accurate?",
            enabled=True,
        )

    @pytest.mark.asyncio
    async def test_fetch_target_event_activity(self):
        """Test fetching target event from ClickHouse"""
        # Create a test event
        event_id = str(uuid.uuid4())

        with patch("posthog.temporal.llm_analytics.run_evaluation.sync_execute") as mock_execute:
            mock_execute.return_value = [
                (
                    event_id,
                    "$ai_generation",
                    json.dumps({"$ai_input": "test input", "$ai_output": "test output"}),
                    datetime.now(),
                    self.team.id,
                    "test-user",
                )
            ]

            inputs = RunEvaluationInputs(evaluation_id=str(self.evaluation.id), target_event_id=event_id)

            result = await fetch_target_event_activity(inputs)

            assert result["uuid"] == event_id
            assert result["event"] == "$ai_generation"
            assert result["team_id"] == self.team.id

    @pytest.mark.asyncio
    async def test_fetch_evaluation_activity(self):
        """Test fetching evaluation from database"""
        inputs = RunEvaluationInputs(evaluation_id=str(self.evaluation.id), target_event_id=str(uuid.uuid4()))

        result = await fetch_evaluation_activity(inputs)

        assert result["id"] == str(self.evaluation.id)
        assert result["name"] == "Test Evaluation"
        assert result["prompt"] == "Is this response factually accurate?"

    @pytest.mark.asyncio
    async def test_execute_llm_judge_activity(self):
        """Test LLM judge execution with realistic message array format"""
        evaluation = {
            "id": str(self.evaluation.id),
            "name": "Test Evaluation",
            "prompt": "Is this response factually accurate?",
            "team_id": self.team.id,
        }

        # Use realistic message array format like actual LLM events
        event_data = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "properties": {
                "$ai_input": [{"role": "user", "content": "What is 2+2?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "4"}],
            },
            "team_id": self.team.id,
        }

        # Mock OpenAI response
        with patch("posthog.temporal.llm_analytics.run_evaluation.openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = '{"verdict": true, "reasoning": "The answer is correct"}'
            mock_client.chat.completions.create.return_value = mock_response

            result = await execute_llm_judge_activity(evaluation, event_data)

            assert result["verdict"] is True
            assert result["reasoning"] == "The answer is correct"
            mock_client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_evaluation_event_activity(self):
        """Test emitting evaluation event"""
        evaluation = {
            "id": str(self.evaluation.id),
            "name": "Test Evaluation",
        }

        event_data = {
            "uuid": str(uuid.uuid4()),
            "event": "$ai_generation",
            "team_id": self.team.id,
            "distinct_id": "test-user",
        }

        result = {"verdict": True, "reasoning": "Test passed"}

        with patch("posthog.temporal.llm_analytics.run_evaluation.create_event") as mock_create:
            await emit_evaluation_event_activity(evaluation, event_data, result, start_time=datetime.now())

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["event"] == "$ai_evaluation"
            assert call_kwargs["properties"]["$ai_evaluation_result"] is True
