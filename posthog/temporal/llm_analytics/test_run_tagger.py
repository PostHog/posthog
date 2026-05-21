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
    build_tag_result_schema,
    build_tagger_system_prompt,
    disable_tagger_activity,
    emit_tagger_event_activity,
    execute_hog_tagger_activity,
    execute_tagger_activity,
    fetch_tagger_activity,
    run_hog_tagger,
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
    @pytest.mark.parametrize(
        "user_prompt,tags,min_tags,max_tags,expected_in,expected_not_in",
        [
            # Tag rendering
            (
                "Classify this",
                [{"name": "billing", "description": "Billing related"}, {"name": "analytics", "description": ""}],
                0,
                None,
                ["- billing: Billing related", "- analytics"],
                [],
            ),
            (
                "Test",
                [{"name": "billing"}, {"name": "analytics"}],
                0,
                None,
                ["- billing\n", "- analytics\n"],
                [],
            ),
            # Min / max constraint wording
            ("Test", [{"name": "a"}], 1, 3, ["at least 1", "at most 3"], []),
            ("Test", [{"name": "a"}], 2, None, ["at least 2"], ["at most"]),
            ("Test", [{"name": "a"}], 0, 5, ["at most 5"], ["at least"]),
            ("Test", [{"name": "a"}], 0, None, ["Select as many tags as apply"], []),
            # User prompt passthrough
            ("Which features are used?", [{"name": "a"}], 0, None, ["Which features are used?"], []),
        ],
    )
    def test_build_tagger_system_prompt(
        self,
        user_prompt: str,
        tags: list[dict],
        min_tags: int,
        max_tags: int | None,
        expected_in: list[str],
        expected_not_in: list[str],
    ):
        prompt = build_tagger_system_prompt(user_prompt, tags, min_tags, max_tags)
        for expected in expected_in:
            assert expected in prompt
        for excluded in expected_not_in:
            assert excluded not in prompt


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
    @pytest.mark.parametrize(
        "result,expected_tagger_type,llm_props_present",
        [
            (
                {
                    "tags": ["billing", "analytics"],
                    "reasoning": "Both billing and analytics were discussed",
                    "model": "gpt-5-mini",
                    "provider": "openai",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "is_byok": False,
                    "key_id": None,
                },
                "llm",
                True,
            ),
            (
                {
                    "tags": ["billing"],
                    "reasoning": "matched billing keyword",
                    "is_hog": True,
                },
                "hog",
                False,
            ),
        ],
    )
    async def test_emit_tagger_event_activity(
        self,
        setup_data,
        result: dict,
        expected_tagger_type: str,
        llm_props_present: bool,
    ):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
        }

        event_data = create_mock_event_data(team.id, properties={})

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
                assert props["$ai_tags"] == result["tags"]
                assert props["$ai_tag_count"] == len(result["tags"])
                assert props["$ai_tag_reasoning"] == result["reasoning"]
                assert props["$ai_tagger_name"] == "Feature Tagger"
                assert props["$ai_tagger_type"] == expected_tagger_type

                llm_keys = {
                    "$ai_model",
                    "$ai_provider",
                    "$ai_input_tokens",
                    "$ai_output_tokens",
                    "$ai_tagger_key_type",
                    "$ai_tagger_key_id",
                }
                if llm_props_present:
                    assert llm_keys <= set(props), f"missing LLM props: {llm_keys - set(props)}"
                    assert props["$ai_model"] == "gpt-5-mini"
                    assert props["$ai_provider"] == "openai"
                    assert props["$ai_input_tokens"] == 100
                    assert props["$ai_output_tokens"] == 20
                else:
                    assert llm_keys.isdisjoint(set(props)), (
                        f"Hog tagger event leaked LLM-only props: {llm_keys & set(props)}"
                    )

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_disable_tagger_activity(self, setup_data):
        from posthog.sync import database_sync_to_async

        tagger = setup_data["tagger"]
        team = setup_data["team"]

        assert tagger.enabled is True

        with patch("posthog.plugins.plugin_server_api.reload_taggers_on_workers"):
            await disable_tagger_activity(str(tagger.id), team.id)

        await database_sync_to_async(tagger.refresh_from_db)()
        assert tagger.enabled is False

    def test_parse_inputs(self):
        event_data = create_mock_event_data(team_id=1)
        inputs = ["tagger-123", json.dumps(event_data)]

        parsed = RunTaggerWorkflow.parse_inputs(inputs)

        assert parsed.tagger_id == "tagger-123"
        assert parsed.event_data == event_data


def make_hog_tagger_dict(team_id: int, source: str, tags: list[dict] | None = None) -> dict:
    """Build the tagger payload that the workflow passes to the Hog activity."""
    from posthog.cdp.validation import compile_hog

    bytecode = compile_hog(source, "tagger")
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        "name": "Hog Tagger",
        "tagger_type": "hog",
        "tagger_config": {
            "source": source,
            "bytecode": bytecode,
            "tags": tags or [{"name": "billing"}, {"name": "analytics"}],
        },
        "team_id": team_id,
    }


class TestRunHogTagger:
    """Direct tests of run_hog_tagger — covers HogVM error branches without
    needing the Django DB or Temporal scaffolding."""

    @staticmethod
    def _event_data() -> dict[str, Any]:
        return create_mock_event_data(team_id=1)

    def test_returns_list_of_strings(self):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return ['billing']", "tagger")

        result = run_hog_tagger(bytecode, self._event_data(), valid_tag_names={"billing", "analytics"})

        assert result["tags"] == ["billing"]
        assert result["error"] is None

    def test_filters_unknown_tags_against_whitelist(self):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return ['billing', 'unknown', 'analytics']", "tagger")

        result = run_hog_tagger(bytecode, self._event_data(), valid_tag_names={"billing", "analytics"})

        assert result["tags"] == ["billing", "analytics"]
        assert "unknown" not in result["tags"]
        assert result["error"] is None

    def test_empty_whitelist_accepts_any_tag(self):
        """When tagger_config['tags'] is empty (Hog-only freeform), the source's
        return value is taken at face value — this is the documented behavior
        for Hog taggers without a tag whitelist."""
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return ['anything', 'goes']", "tagger")

        result = run_hog_tagger(bytecode, self._event_data(), valid_tag_names=set())

        assert result["tags"] == ["anything", "goes"]
        assert result["error"] is None

    def test_string_return_is_promoted_to_single_tag_list(self):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return 'billing'", "tagger")

        result = run_hog_tagger(bytecode, self._event_data(), valid_tag_names={"billing"})

        assert result["tags"] == ["billing"]
        assert result["error"] is None

    def test_non_list_return_type_surfaces_error(self):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return 42", "tagger")

        result = run_hog_tagger(bytecode, self._event_data(), valid_tag_names={"billing"})

        assert result["tags"] == []
        assert result["error"] is not None
        assert "Must return a list of tag names" in result["error"]

    def test_null_return_yields_empty_tags_no_error(self):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("return null", "tagger")

        result = run_hog_tagger(bytecode, self._event_data(), valid_tag_names={"billing"})

        assert result["tags"] == []
        assert result["error"] is None

    def test_print_output_captured_as_reasoning(self):
        from posthog.cdp.validation import compile_hog

        bytecode = compile_hog("print('inspecting input'); return ['billing']", "tagger")

        result = run_hog_tagger(bytecode, self._event_data(), valid_tag_names={"billing"})

        assert result["tags"] == ["billing"]
        assert "inspecting input" in result["reasoning"]

    def test_runtime_timeout_returns_typed_error(self):
        from common.hogvm.python.utils import HogVMRuntimeExceededException

        with patch(
            "common.hogvm.python.execute.execute_bytecode", side_effect=HogVMRuntimeExceededException(5.0, 1000)
        ):
            result = run_hog_tagger(["dummy"], self._event_data(), valid_tag_names={"billing"})

        assert result["tags"] == []
        assert "timed out" in (result["error"] or "").lower()

    def test_memory_exceeded_returns_typed_error(self):
        from common.hogvm.python.utils import HogVMMemoryExceededException

        with patch(
            "common.hogvm.python.execute.execute_bytecode",
            side_effect=HogVMMemoryExceededException(1024, 4096),
        ):
            result = run_hog_tagger(["dummy"], self._event_data(), valid_tag_names={"billing"})

        assert result["tags"] == []
        assert "memory" in (result["error"] or "").lower()

    def test_unexpected_exception_is_caught_and_logged(self):
        with patch(
            "common.hogvm.python.execute.execute_bytecode",
            side_effect=RuntimeError("kaboom"),
        ):
            result = run_hog_tagger(["dummy"], self._event_data(), valid_tag_names={"billing"})

        assert result["tags"] == []
        assert result["error"] is not None
        assert "Unexpected error" in result["error"]


class TestExecuteHogTaggerActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_happy_path_returns_is_hog_marker(self, setup_data):
        team = setup_data["team"]
        tagger = make_hog_tagger_dict(
            team.id,
            source="return ['billing']",
            tags=[{"name": "billing"}, {"name": "analytics"}],
        )

        result = await execute_hog_tagger_activity(tagger, create_mock_event_data(team.id))

        assert result["tags"] == ["billing"]
        assert result["is_hog"] is True

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_filters_unknown_tags(self, setup_data):
        team = setup_data["team"]
        tagger = make_hog_tagger_dict(
            team.id,
            source="return ['billing', 'unknown', 'analytics']",
            tags=[{"name": "billing"}, {"name": "analytics"}],
        )

        result = await execute_hog_tagger_activity(tagger, create_mock_event_data(team.id))

        assert result["tags"] == ["billing", "analytics"]
        assert "unknown" not in result["tags"]

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_missing_bytecode_raises(self, setup_data):
        team = setup_data["team"]
        tagger = {
            "id": "00000000-0000-0000-0000-000000000000",
            "name": "Hog Tagger",
            "tagger_type": "hog",
            "tagger_config": {"source": "return ['billing']", "tags": [{"name": "billing"}]},
            "team_id": team.id,
        }

        with pytest.raises(ApplicationError, match="Missing bytecode"):
            await execute_hog_tagger_activity(tagger, create_mock_event_data(team.id))

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_wrong_tagger_type_raises(self, setup_data):
        team = setup_data["team"]
        tagger = {
            "id": "00000000-0000-0000-0000-000000000000",
            "name": "LLM Tagger",
            "tagger_type": "llm",
            "tagger_config": {},
            "team_id": team.id,
        }

        with pytest.raises(ApplicationError, match="Unsupported tagger type"):
            await execute_hog_tagger_activity(tagger, create_mock_event_data(team.id))

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_non_list_return_raises_application_error(self, setup_data):
        team = setup_data["team"]
        tagger = make_hog_tagger_dict(
            team.id,
            source="return 42",
            tags=[{"name": "billing"}],
        )

        with pytest.raises(ApplicationError, match="Must return a list"):
            await execute_hog_tagger_activity(tagger, create_mock_event_data(team.id))

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_timeout_raises_application_error(self, setup_data):
        from common.hogvm.python.utils import HogVMRuntimeExceededException

        team = setup_data["team"]
        tagger = make_hog_tagger_dict(
            team.id,
            source="return ['billing']",
            tags=[{"name": "billing"}],
        )

        with patch(
            "common.hogvm.python.execute.execute_bytecode",
            side_effect=HogVMRuntimeExceededException(5.0, 1000),
        ):
            with pytest.raises(ApplicationError, match="timed out"):
                await execute_hog_tagger_activity(tagger, create_mock_event_data(team.id))

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_memory_exceeded_raises_application_error(self, setup_data):
        from common.hogvm.python.utils import HogVMMemoryExceededException

        team = setup_data["team"]
        tagger = make_hog_tagger_dict(
            team.id,
            source="return ['billing']",
            tags=[{"name": "billing"}],
        )

        with patch(
            "common.hogvm.python.execute.execute_bytecode",
            side_effect=HogVMMemoryExceededException(1024, 4096),
        ):
            with pytest.raises(ApplicationError, match="Memory limit"):
                await execute_hog_tagger_activity(tagger, create_mock_event_data(team.id))


class TestBuildTagResultSchema:
    @pytest.mark.parametrize(
        "tags,min_tags,max_tags,expected_substrings,forbidden_substrings",
        [
            (["a", "b"], 0, None, ["Valid values:", "Can be empty"], []),
            (["a", "b"], 1, None, ["Minimum 1"], ["Can be empty"]),
            (["a", "b"], 1, 2, ["Minimum 1", "Maximum 2"], ["Can be empty"]),
            (["a", "b"], 0, 2, ["Maximum 2", "Can be empty"], ["Minimum"]),
        ],
    )
    def test_description_reflects_constraints(
        self,
        tags: list[str],
        min_tags: int,
        max_tags: int | None,
        expected_substrings: list[str],
        forbidden_substrings: list[str],
    ):
        schema = build_tag_result_schema(tags, min_tags=min_tags, max_tags=max_tags)
        # FieldInfo.description holds the description we built
        description = schema.model_fields["tags"].description or ""
        for needle in expected_substrings:
            assert needle in description
        for needle in forbidden_substrings:
            assert needle not in description


class TestFetchTaggerActivityDisabled:
    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_short_circuits_when_tagger_disabled(self, setup_data):
        from posthog.sync import database_sync_to_async

        tagger = setup_data["tagger"]
        team = setup_data["team"]

        tagger.enabled = False
        await database_sync_to_async(tagger.save)(update_fields=["enabled"])

        inputs = RunTaggerInputs(tagger_id=str(tagger.id), event_data=create_mock_event_data(team.id))

        with pytest.raises(ApplicationError, match="disabled"):
            await fetch_tagger_activity(inputs)
