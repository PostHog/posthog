import json
import uuid
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

import pytest
from unittest.mock import MagicMock, patch

import httpx
from temporalio import activity
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.api.capture import CaptureInternalError
from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.posthog_client import EXPECTED_CONTROL_FLOW_ERROR_TYPES, is_expected_activity_failure

from products.ai_observability.backend.llm.errors import (
    ContentFilteredError,
    OutputTokenLimitError,
    ProviderRequestRejectedError,
    StructuredOutputParseError,
)
from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.ai_observability.backend.models.taggers import Tagger

from .run_tagger import (
    SKIPPED_RESULT_ERROR_TYPES,
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


def _mock_config_with_active_key(provider: str = "openai") -> MagicMock:
    """A mocked EvaluationConfig whose active key resolves via DefaultModelSpec (usable, right provider)."""
    key = MagicMock(provider=provider, state=LLMProviderKey.State.OK)
    return MagicMock(active_provider_key=key)


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


class SetupData(TypedDict):
    organization: Organization
    team: Team
    tagger: Tagger


@pytest.fixture
def setup_data() -> SetupData:
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
            # JSON contract for providers that do not enforce the response schema
            (
                "Test",
                [{"name": "a"}],
                0,
                None,
                ['"tags"', '"reasoning"', "Always include both keys"],
                [],
            ),
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

    @pytest.mark.django_db(transaction=True)
    def test_execute_tagger_activity(self, setup_data):
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

        with patch("posthog.temporal.ai_observability.run_tagger.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            mock_parsed = TagResult(tags=["billing"], reasoning="The conversation is about billing setup")

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=100, output_tokens=20, total_tokens=120)
            called_on_event_loop: list[bool] = []

            def complete(request: Any) -> Any:
                try:
                    asyncio.get_running_loop()
                    called_on_event_loop.append(True)
                except RuntimeError:
                    called_on_event_loop.append(False)
                return mock_response

            mock_client.complete.side_effect = complete

            with patch("posthog.temporal.ai_observability.model_resolution.EvaluationConfig") as mock_eval_config:
                mock_config = _mock_config_with_active_key()
                mock_eval_config.objects.get_or_create.return_value = (mock_config, False)

                result = execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

                assert result["tags"] == ["billing"]
                assert result["reasoning"] == "The conversation is about billing setup"
                assert result["input_tokens"] == 100
                assert result["output_tokens"] == 20
                assert called_on_event_loop == [False]

    @pytest.mark.django_db(transaction=True)
    def test_execute_tagger_strips_unknown_tags(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
            "tagger_config": make_tagger_config(),
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with patch("posthog.temporal.ai_observability.run_tagger.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # LLM returns an unknown tag
            mock_parsed = TagResult(tags=["billing", "unknown_tag", "analytics"], reasoning="Test")

            mock_response = MagicMock()
            mock_response.parsed = mock_parsed
            mock_response.usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=15)
            mock_client.complete.return_value = mock_response

            with patch("posthog.temporal.ai_observability.model_resolution.EvaluationConfig") as mock_eval_config:
                mock_config = _mock_config_with_active_key()
                mock_eval_config.objects.get_or_create.return_value = (mock_config, False)

                result = execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

                # "unknown_tag" should be stripped
                assert "unknown_tag" not in result["tags"]
                assert result["tags"] == ["billing", "analytics"]

    @pytest.mark.django_db(transaction=True)
    def test_execute_tagger_enforces_max_tags(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
            "tagger_config": make_tagger_config(),  # max_tags=2
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with patch("posthog.temporal.ai_observability.run_tagger.Client") as mock_client_class:
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

            with patch("posthog.temporal.ai_observability.model_resolution.EvaluationConfig") as mock_eval_config:
                mock_config = _mock_config_with_active_key()
                mock_eval_config.objects.get_or_create.return_value = (mock_config, False)

                result = execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

                assert len(result["tags"]) == 2
                assert result["tags"] == ["billing", "analytics"]

    @pytest.mark.django_db(transaction=True)
    def test_execute_tagger_terminal_team_requires_provider_key(self, setup_data):
        tagger_obj = setup_data["tagger"]
        team = setup_data["team"]

        tagger = {
            "id": str(tagger_obj.id),
            "name": "Feature Tagger",
            "tagger_config": make_tagger_config(),
            "team_id": team.id,
        }

        event_data = create_mock_event_data(team.id)

        with patch("posthog.temporal.ai_observability.model_resolution.EvaluationConfig") as mock_eval_config:
            mock_config = MagicMock()
            mock_config.active_provider_key = None
            mock_eval_config.objects.get_or_create.return_value = (mock_config, False)

            with pytest.raises(ApplicationError) as exc_info:
                execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

        assert exc_info.value.details[0]["error_type"] == "provider_key_required"
        assert exc_info.value.type == "tagger_provider_key_required"
        assert is_expected_activity_failure(exc_info.value)

    @pytest.mark.django_db(transaction=True)
    def test_execute_tagger_missing_prompt(self, setup_data):
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
            execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

    @pytest.mark.django_db(transaction=True)
    def test_execute_tagger_no_tags_defined(self, setup_data):
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
            execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=event_data))

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

        with patch("posthog.temporal.ai_observability.team_capture.get_team_api_token") as mock_team_get:
            with patch("posthog.temporal.ai_observability.team_capture.capture_ai_internal") as mock_capture:
                mock_team_get.return_value = team.api_token
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
    @pytest.mark.parametrize(
        "status_code,should_raise",
        [
            pytest.param(402, False, id="billing_limit_is_swallowed"),
            pytest.param(500, True, id="server_error_still_raises"),
        ],
    )
    async def test_emit_tagger_event_activity_billing_limit(self, setup_data, status_code: int, should_raise: bool):
        team = setup_data["team"]
        tagger = {"id": str(setup_data["tagger"].id), "name": "Feature Tagger"}
        event_data = create_mock_event_data(team.id, properties={})
        result = {"tags": ["billing"], "reasoning": "matched", "is_hog": True}

        capture_result = MagicMock(
            raise_for_status=MagicMock(side_effect=CaptureInternalError("boom", status_code=status_code))
        )
        inputs = EmitTaggerEventInputs(
            tagger=tagger, event_data=event_data, result=result, start_time=datetime(2024, 1, 1, 12, 0, 0)
        )

        with patch("posthog.temporal.ai_observability.team_capture.get_team_api_token", return_value=team.api_token):
            with patch(
                "posthog.temporal.ai_observability.team_capture.capture_ai_internal", return_value=capture_result
            ):
                if should_raise:
                    with pytest.raises(CaptureInternalError):
                        await emit_tagger_event_activity(inputs)
                else:
                    await emit_tagger_event_activity(inputs)

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

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.parametrize("activity", ["llm", "hog", "emit"])
    async def test_tagger_activities_hydrate_a_reference(self, setup_data, activity: str):
        team = setup_data["team"]
        full_event = create_mock_event_data(
            team.id,
            uuid="g1",
            properties={
                "$ai_input": [{"role": "user", "content": "How do I set up billing?"}],
                "$ai_output_choices": [{"role": "assistant", "content": "In the settings."}],
                "$ai_trace_id": "t1",
            },
        )
        reference = {"uuid": "g1", "team_id": team.id, "timestamp": full_event["timestamp"], "trace_id": "t1"}
        tagger = {
            "id": str(setup_data["tagger"].id),
            "name": "Feature Tagger",
            "tagger_config": make_tagger_config(),
            "team_id": team.id,
        }

        with patch(
            "posthog.temporal.ai_observability.evaluation_event_io.fetch_generation_event", return_value=full_event
        ) as mock_fetch:
            if activity == "llm":
                mock_response = MagicMock(
                    parsed=TagResult(tags=["billing"], reasoning="billing"),
                    usage=MagicMock(input_tokens=1, output_tokens=1, total_tokens=2),
                )
                with (
                    patch("posthog.temporal.ai_observability.run_tagger.Client") as mock_client_class,
                    patch("posthog.temporal.ai_observability.model_resolution.EvaluationConfig") as mock_eval_config,
                ):
                    mock_client_class.return_value.complete.return_value = mock_response
                    mock_eval_config.objects.get_or_create.return_value = (_mock_config_with_active_key(), False)
                    result = await database_sync_to_async(execute_tagger_activity)(
                        ExecuteTaggerInputs(tagger=tagger, event_data=reference)
                    )
                assert result["tags"] == ["billing"]
            elif activity == "hog":
                hog_tagger = make_hog_tagger_dict(team.id, source="return ['billing']")
                result = await execute_hog_tagger_activity(hog_tagger, reference)
                assert result["tags"] == ["billing"]
            else:
                with (
                    patch(
                        "posthog.temporal.ai_observability.team_capture.get_team_api_token",
                        return_value=team.api_token,
                    ),
                    patch("posthog.temporal.ai_observability.team_capture.capture_ai_internal") as mock_capture,
                ):
                    mock_capture.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
                    await emit_tagger_event_activity(
                        EmitTaggerEventInputs(
                            tagger=tagger,
                            event_data=reference,
                            result={"tags": ["billing"], "reasoning": "billing", "is_hog": True},
                            start_time=datetime(2024, 1, 1, 12, 0, 0),
                        )
                    )
                props = mock_capture.call_args[1]["properties"]
                assert props["$ai_target_event_id"] == "g1"
                assert props["$ai_trace_id"] == "t1"

        assert mock_fetch.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_the_hog_tagger_waits_for_a_live_reference_to_reach_clickhouse(self, setup_data):
        team = setup_data["team"]
        full_event = create_mock_event_data(team.id, uuid="g1", properties={"$ai_trace_id": "t1"})
        reference = {
            "uuid": "g1",
            "team_id": team.id,
            "timestamp": full_event["timestamp"],
            "trace_id": "t1",
            "awaiting_ingestion": True,
        }
        hog_tagger = make_hog_tagger_dict(team.id, source="return ['billing']")
        emitted: list[dict[str, Any]] = []

        @activity.defn(name="fetch_tagger_activity")
        async def mock_fetch_tagger(inputs: RunTaggerInputs) -> dict[str, Any]:
            return hog_tagger

        @activity.defn(name="emit_tagger_event_activity")
        async def mock_emit_tagger_event(inputs: EmitTaggerEventInputs) -> None:
            emitted.append(inputs.result)

        task_queue = str(uuid.uuid4())
        with patch(
            "posthog.temporal.ai_observability.evaluation_event_io.fetch_generation_event",
            side_effect=[None, full_event],
        ) as mock_fetch:
            async with await WorkflowEnvironment.start_time_skipping() as env:
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[RunTaggerWorkflow],
                    activities=[mock_fetch_tagger, execute_hog_tagger_activity, mock_emit_tagger_event],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ):
                    result = await env.client.execute_workflow(
                        RunTaggerWorkflow.run,
                        RunTaggerInputs(tagger_id=hog_tagger["id"], event_data=reference),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

        assert mock_fetch.call_count == 2
        assert result["tags"] == ["billing"]
        assert emitted[0]["tags"] == ["billing"]

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
        tagger = setup_data["tagger"]
        team = setup_data["team"]

        tagger.enabled = False
        await database_sync_to_async(tagger.save)(update_fields=["enabled"])

        inputs = RunTaggerInputs(tagger_id=str(tagger.id), event_data=create_mock_event_data(team.id))

        with pytest.raises(ApplicationError, match="disabled") as exc_info:
            await fetch_tagger_activity(inputs)

        assert exc_info.value.type == "tagger_disabled"
        assert is_expected_activity_failure(exc_info.value)


class TestSkippedResultsStayOutOfErrorTracking:
    def test_skipped_result_types_are_expected_control_flow(self) -> None:
        assert SKIPPED_RESULT_ERROR_TYPES <= EXPECTED_CONTROL_FLOW_ERROR_TYPES

    @pytest.mark.parametrize(
        "llm_error,error_type",
        [
            (OutputTokenLimitError("The model reached its output token limit."), "parse_error"),
            (StructuredOutputParseError("The reply did not match the schema."), "parse_error"),
            (ContentFilteredError("The request was rejected by the content filter."), "parse_error"),
            (ProviderRequestRejectedError("The response exceeds the limit."), "request_rejected"),
        ],
    )
    @pytest.mark.django_db(transaction=True)
    def test_unusable_reply_is_skipped_not_captured(
        self, setup_data: SetupData, llm_error: Exception, error_type: str
    ) -> None:
        team = setup_data["team"]
        tagger = {
            "id": str(setup_data["tagger"].id),
            "name": "Feature Tagger",
            "tagger_config": make_tagger_config(),
            "team_id": team.id,
        }

        with (
            patch("posthog.temporal.ai_observability.run_tagger.Client") as mock_client_class,
            patch("posthog.temporal.ai_observability.model_resolution.EvaluationConfig") as mock_eval_config,
            patch("posthoganalytics.capture_exception") as mock_capture_exception,
        ):
            mock_client_class.return_value.complete.side_effect = llm_error
            mock_eval_config.objects.get_or_create.return_value = (_mock_config_with_active_key(), False)

            with pytest.raises(ApplicationError) as exc_info:
                execute_tagger_activity(ExecuteTaggerInputs(tagger=tagger, event_data=create_mock_event_data(team.id)))

        assert exc_info.value.details[0]["error_type"] == error_type
        assert exc_info.value.type == f"tagger_{error_type}"
        assert is_expected_activity_failure(exc_info.value)
        mock_capture_exception.assert_not_called()

        activity_error = ActivityError(
            "Tagger activity failed",
            scheduled_event_id=1,
            started_event_id=2,
            identity="test-worker",
            activity_type="execute_tagger_activity",
            activity_id="test-activity",
            retry_state=None,
        )
        activity_error.__cause__ = exc_info.value
        with (
            patch("temporalio.workflow.deprecate_patch"),
            patch("temporalio.workflow.now", return_value=datetime(2026, 1, 1, tzinfo=UTC)),
            patch("temporalio.workflow.execute_activity", side_effect=[tagger, activity_error]),
        ):
            result = asyncio.run(
                RunTaggerWorkflow().run(
                    RunTaggerInputs(tagger_id=tagger["id"], event_data=create_mock_event_data(team.id))
                )
            )

        assert result == {
            "tags": [],
            "skipped": True,
            "skip_reason": error_type,
            "message": str(llm_error),
            "tagger_id": tagger["id"],
        }


@pytest.mark.parametrize("rate_limited", [False, True])
def test_custom_provider_tagger_uses_bounded_completion(rate_limited: bool) -> None:
    key = LLMProviderKey(
        id=uuid.uuid4(),
        provider="openai_compatible",
        state=LLMProviderKey.State.OK,
        encrypted_config={"api_key": "test-key", "base_url": "https://8.8.8.8/v1"},
    )
    payload = json.dumps(
        {
            "id": "fixture",
            "object": "chat.completion",
            "created": 0,
            "model": "some-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps({"tags": ["billing"], "reasoning": "Billing question"}),
                    },
                }
            ],
        }
    ).encode()
    responses = [httpx.Response(200, stream=httpx.ByteStream(payload))]
    if rate_limited:
        responses.insert(0, httpx.Response(429, headers={"Retry-After": "15"}, stream=httpx.ByteStream(b"")))
    inputs = ExecuteTaggerInputs(
        tagger={
            "id": "test-tagger",
            "team_id": 1,
            "tagger_config": make_tagger_config(),
            "model_configuration": {"provider": "openai_compatible", "model": "some-model"},
        },
        event_data=create_mock_event_data(1),
    )
    with (
        patch.object(key, "save"),
        patch("posthog.temporal.ai_observability.model_resolution.EvaluationConfig") as configs,
        patch(
            "httpx.AsyncHTTPTransport.handle_async_request",
            side_effect=responses,
        ) as transport,
    ):
        configs.objects.get_or_create.return_value = (MagicMock(active_provider_key=key), False)
        if rate_limited:
            with pytest.raises(ApplicationError) as error:
                execute_tagger_activity(inputs)
            assert not error.value.non_retryable
            assert error.value.next_retry_delay == timedelta(seconds=15)
            assert error.value.details == ({"error_type": "provider_unavailable", "provider": "openai_compatible"},)
            assert transport.call_count == 1
        result = execute_tagger_activity(inputs)
    assert result["tags"] == ["billing"]
    assert result["reasoning"] == "Billing question"
    assert key.state == LLMProviderKey.State.OK
    assert transport.call_count == (2 if rate_limited else 1)
