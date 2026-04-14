import json
import uuid
from datetime import datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team

from products.llm_analytics.backend.models.taggers import Tagger

from .run_tagger import (
    EmitTaggerEventInputs,
    ExecuteTaggerInputs,
    RunTaggerInputs,
    RunTaggerWorkflow,
    TagResult,
    build_tagger_system_prompt,
    disable_tagger_activity,
    emit_tagger_event_activity,
    execute_tagger_activity,
    fetch_tagger_activity,
)


def create_mock_event_data(team_id: int, **overrides: Any) -> dict[str, Any]:
    defaults = {
        "uuid": str(uuid.uuid4()),
        "event": "$ai_generation",
        "properties": {"$ai_input": "test input", "$ai_output": "test output"},
        "timestamp": datetime.now().isoformat(),
        "team_id": team_id,
        "distinct_id": "test-user",
    }
    return {**defaults, **overrides}


def make_tagger_config():
    return {
        "prompt": "Which product features were discussed?",
        "tags": [
            {"name": "billing", "description": "Billing related"},
            {"name": "analytics", "description": "Analytics related"},
            {"name": "feature-flags", "description": "Feature flag related"},
        ],
        "min_tags": 0,
        "max_tags": 2,
    }


@pytest.fixture
def setup_data():
    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=organization, name="Test Team")
    tagger = Tagger.objects.create(
        team=team,
        name="Feature Tagger",
        tagger_config=make_tagger_config(),
        enabled=True,
    )
    return {"organization": organization, "team": team, "tagger": tagger}


class TestBuildTaggerSystemPrompt:
    def test_includes_all_tags(self):
        tags = [
            {"name": "billing", "description": "Billing related"},
            {"name": "analytics", "description": ""},
        ]
        prompt = build_tagger_system_prompt("Classify this", tags, 0, None)
        assert "- billing: Billing related" in prompt
        assert "- analytics" in prompt

    def test_includes_constraints_min_and_max(self):
        tags = [{"name": "a"}]
        prompt = build_tagger_system_prompt("Test", tags, 1, 3)
        assert "at least 1" in prompt
        assert "at most 3" in prompt

    def test_includes_constraint_min_only(self):
        tags = [{"name": "a"}]
        prompt = build_tagger_system_prompt("Test", tags, 2, None)
        assert "at least 2" in prompt
        assert "at most" not in prompt

    def test_includes_constraint_max_only(self):
        tags = [{"name": "a"}]
        prompt = build_tagger_system_prompt("Test", tags, 0, 5)
        assert "at most 5" in prompt
        assert "at least" not in prompt

    def test_no_constraints(self):
        tags = [{"name": "a"}]
        prompt = build_tagger_system_prompt("Test", tags, 0, None)
        assert "Select as many tags as apply" in prompt

    def test_includes_user_prompt(self):
        tags = [{"name": "a"}]
        prompt = build_tagger_system_prompt("Which features are used?", tags, 0, None)
        assert "Which features are used?" in prompt

    def test_tags_without_description(self):
        tags = [{"name": "billing"}, {"name": "analytics"}]
        prompt = build_tagger_system_prompt("Test", tags, 0, None)
        assert "- billing\n" in prompt
        assert "- analytics\n" in prompt


class TestRunTaggerWorkflow:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_fetch_tagger_activity(self, setup_data):
        tagger = setup_data["tagger"]
        team = setup_data["team"]

        inputs = RunTaggerInputs(
            tagger_id=str(tagger.id),
            event_data=create_mock_event_data(team.id),
        )

        result = await fetch_tagger_activity(inputs)

        assert result["id"] == str(tagger.id)
        assert result["name"] == "Feature Tagger"
        assert result["tagger_config"]["prompt"] == "Which product features were discussed?"
        assert len(result["tagger_config"]["tags"]) == 3
        assert result["team_id"] == team.id

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_fetch_tagger_activity_not_found(self, setup_data):
        team = setup_data["team"]

        inputs = RunTaggerInputs(
            tagger_id=str(uuid.uuid4()),
            event_data=create_mock_event_data(team.id),
        )

        with pytest.raises(ValueError, match="not found"):
            await fetch_tagger_activity(inputs)

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_tagger_activity(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
            "tagger_config": make_tagger_config(),
            "team_id": team.id,
        }

        event_data = create_mock_event_data(
            team.id,
            properties={
                "$ai_input": [{"role": "user", "content": "How do I set up billing?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "You can set up billing in the settings."}],
            },
        )

        with patch("posthog.temporal.llm_analytics.run_tagger.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_parsed = TagResult(tags=["billing"], reasoning="The conversation is about billing setup")

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=100, output_tokens=20, total_tokens=120)
            mock_client.complete.return_value = mock_response

            with patch("posthog.temporal.llm_analytics.run_tagger.EvaluationConfig") as mock_eval_config:
                mock_config = MagicMock()
                mock_config.trial_evals_used = 0
                mock_config.trial_eval_limit = 100
                mock_eval_config.objects.get_or_create.return_value = (mock_config, False)

                result = await execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

                assert result["tags"] == ["billing"]
                assert result["reasoning"] == "The conversation is about billing setup"
                assert result["input_tokens"] == 100
                assert result["output_tokens"] == 20
                mock_client.complete.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_tagger_strips_unknown_tags(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
            "tagger_config": make_tagger_config(),
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with patch("posthog.temporal.llm_analytics.run_tagger.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # LLM returns an unknown tag
            mock_parsed = TagResult(tags=["billing", "unknown_tag", "analytics"], reasoning="Test")

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            with patch("posthog.temporal.llm_analytics.run_tagger.EvaluationConfig") as mock_eval_config:
                mock_config = MagicMock()
                mock_config.trial_evals_used = 0
                mock_config.trial_eval_limit = 100
                mock_eval_config.objects.get_or_create.return_value = (mock_config, False)

                result = await execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

                # "unknown_tag" should be stripped
                assert "unknown_tag" not in result["tags"]
                assert result["tags"] == ["billing", "analytics"]

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_tagger_enforces_max_tags(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
            "tagger_config": make_tagger_config(),  # max_tags=2
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with patch("posthog.temporal.llm_analytics.run_tagger.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # LLM returns 3 valid tags but max_tags is 2
            mock_parsed = TagResult(
                tags=["billing", "analytics", "feature-flags"],
                reasoning="All three are discussed",
            )

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            with patch("posthog.temporal.llm_analytics.run_tagger.EvaluationConfig") as mock_eval_config:
                mock_config = MagicMock()
                mock_config.trial_evals_used = 0
                mock_config.trial_eval_limit = 100
                mock_eval_config.objects.get_or_create.return_value = (mock_config, False)

                result = await execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

                assert len(result["tags"]) == 2
                assert result["tags"] == ["billing", "analytics"]

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_tagger_trial_limit_reached(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
            "tagger_config": make_tagger_config(),
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with patch("posthog.temporal.llm_analytics.run_tagger.EvaluationConfig") as mock_eval_config:
            mock_config = MagicMock()
            mock_config.trial_evals_used = 100
            mock_config.trial_eval_limit = 100
            mock_eval_config.objects.get_or_create.return_value = (mock_config, False)

            with pytest.raises(ApplicationError, match="Trial limit"):
                await execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_tagger_missing_prompt(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
            "tagger_config": {"tags": [{"name": "billing"}]},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with pytest.raises(ApplicationError, match="Missing prompt"):
            await execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_execute_tagger_no_tags_defined(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
            "tagger_config": {"prompt": "Test", "tags": []},
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with pytest.raises(ApplicationError, match="No tags defined"):
            await execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_emit_tagger_event_activity(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
        }

        event_data = create_mock_event_data(team.id, properties={})

        result = {
            "tags": ["billing", "analytics"],
            "reasoning": "Both billing and analytics were discussed",
            "model": "gpt-5-mini",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 20,
        }

        with patch("posthog.temporal.llm_analytics.run_tagger.Team.objects.get") as mock_team_get:
            with patch("posthog.temporal.llm_analytics.run_tagger.capture_internal") as mock_capture:
                mock_team_get.return_value = team
                mock_capture.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

                await emit_tagger_event_activity(
                    EmitTaggerEventInputs(
                        tagger=tagger,
                        event_data=event_data,
                        result=result,
                        start_time=datetime(2024, 1, 1, 12, 0, 0),
                    )
                )

                mock_capture.assert_called_once()
                call_kwargs = mock_capture.call_args[1]
                assert call_kwargs["event_name"] == "$ai_tag"
                assert call_kwargs["token"] == team.api_token
                assert call_kwargs["process_person_profile"] is True
                props = call_kwargs["properties"]
                assert props["$ai_tags"] == ["billing", "analytics"]
                assert props["$ai_tag_count"] == 2
                assert props["$ai_tag_reasoning"] == "Both billing and analytics were discussed"
                assert props["$ai_tagger_name"] == "Feature Tagger"
                assert props["$ai_model"] == "gpt-5-mini"
                assert props["$ai_provider"] == "openai"
                assert props["$ai_input_tokens"] == 100
                assert props["$ai_output_tokens"] == 20

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_disable_tagger_activity(self, setup_data):
        tagger = setup_data["tagger"]
        team = setup_data["team"]

        assert tagger.enabled is True

        await disable_tagger_activity(str(tagger.id), team.id)

        tagger.refresh_from_db()
        assert tagger.enabled is False

    def test_parse_inputs(self):
        event_data = create_mock_event_data(team_id=1)
        inputs = ["tagger-123", json.dumps(event_data)]

        parsed = RunTaggerWorkflow.parse_inputs(inputs)

        assert parsed.tagger_id == "tagger-123"
        assert parsed.event_data == event_data
