import json
import asyncio

import pytest
from unittest.mock import patch

from django.test import override_settings

import httpx
from asgiref.sync import async_to_sync, sync_to_async

from posthog.clickhouse.query_tagging import get_query_tags
from posthog.llm import gateway_client
from posthog.llm.gateway_client import (
    AIGatewayConfig,
    AIGatewayHostError,
    GatewayNotConfiguredError,
    build_ai_gateway_openai_client,
    build_anthropic_client,
    build_async_anthropic_client,
    build_async_openai_client,
    build_gemini_client,
    build_openai_client,
    private_scout_gateway,
    resolve_ai_gateway_config,
    resolve_https_ai_gateway_config,
    team_trace_id,
    trace_id_from_seed,
)

AI_GATEWAY_URL = "https://ai-gateway.example/v1"
AI_GATEWAY_KEY = "phs_project_secret"
TEAM_42_TRACE_ID = "30a04c7a-98b4-5119-8597-8c696e44a270"


class TestResolveAIGatewayConfig:
    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    def test_returns_none_when_both_unset(self):
        assert resolve_ai_gateway_config() is None

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    def test_returns_pair_when_both_set(self):
        assert resolve_ai_gateway_config() == AIGatewayConfig(url=AI_GATEWAY_URL, api_key=AI_GATEWAY_KEY)

    @pytest.mark.parametrize(
        "url,key,reason",
        [
            (AI_GATEWAY_URL, "", "must be set together"),
            ("", AI_GATEWAY_KEY, "must be set together"),
            ("https://ai-gateway.example", AI_GATEWAY_KEY, "OpenAI base path"),
        ],
    )
    def test_misconfig_falls_back_to_none_and_logs(self, url, key, reason):
        # Radu review: a misconfig logs and returns None so callers fall back, never raises.
        with (
            override_settings(AI_GATEWAY_URL=url, AI_GATEWAY_API_KEY=key),
            patch("posthog.llm.gateway_client.logger") as mock_logger,
        ):
            assert resolve_ai_gateway_config() is None

        mock_logger.warning.assert_called_once()
        assert reason in str(mock_logger.warning.call_args)

    @pytest.mark.parametrize(
        "url,usable",
        [
            (AI_GATEWAY_URL, True),
            ("http://ai-gateway.example/v1", False),
            ("http://localhost:3308/v1", True),
            ("http://127.0.0.1:3308/v1", True),
            ("http://[::1]:3308/v1", True),
            ("http://localhost.example.com/v1", False),
        ],
    )
    def test_https_config_keeps_a_remote_key_off_plain_http(self, url, usable):
        with override_settings(AI_GATEWAY_URL=url, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY):
            config = resolve_https_ai_gateway_config()

        assert config == (AIGatewayConfig(url=url, api_key=AI_GATEWAY_KEY) if usable else None)


class TestBuildOpenAIClient:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.OpenAI")
    def test_gateway_mode_routes_to_slugless_go_gateway_with_ai_product(self, mock_openai, mock_httpx):
        result = build_openai_client(ai_product="aio_summarization")

        mock_httpx.assert_called_once_with(trust_env=False)
        mock_openai.assert_called_once_with(
            api_key=AI_GATEWAY_KEY,
            base_url=AI_GATEWAY_URL,
            default_headers={
                "X-PostHog-Properties": json.dumps({"ai_product": "aio_summarization"}),
                "X-PostHog-Product": "aio_summarization",
            },
            http_client=mock_httpx.return_value,
        )
        assert result is mock_openai.return_value


class TestBuildAsyncOpenAIClient:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.AsyncClient")
    @patch("posthog.llm.gateway_client.AsyncOpenAI")
    def test_gateway_mode_routes_to_slugless_go_gateway_with_ai_product(self, mock_async_openai, mock_httpx):
        result = build_async_openai_client(ai_product="aio_eval_summary")

        mock_httpx.assert_called_once_with(trust_env=False)
        mock_async_openai.assert_called_once_with(
            api_key=AI_GATEWAY_KEY,
            base_url=AI_GATEWAY_URL,
            default_headers={
                "X-PostHog-Properties": json.dumps({"ai_product": "aio_eval_summary"}),
                "X-PostHog-Product": "aio_eval_summary",
            },
            http_client=mock_httpx.return_value,
        )
        assert result is mock_async_openai.return_value

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.AsyncClient")
    @patch("posthog.llm.gateway_client.AsyncOpenAI")
    def test_gateway_mode_correlates_all_calls_in_a_trace_and_session(self, mock_async_openai, mock_httpx):
        result = build_async_openai_client(
            ai_product="aio_eval_summary",
            trace_id="a9f9e1dd-8332-4ad0-959b-36ea0a45734e",
            session_id="summary-session-1",
            properties={"team_id": "42", "evaluation_id": "evaluation-123"},
            distinct_id="user-123",
        )

        headers = mock_async_openai.call_args.kwargs["default_headers"]
        assert headers["X-PostHog-Trace-Id"] == "a9f9e1dd-8332-4ad0-959b-36ea0a45734e"
        assert headers["X-PostHog-Session-Id"] == "summary-session-1"
        assert headers["X-PostHog-Distinct-Id"] == "user-123"
        assert json.loads(headers["X-PostHog-Properties"]) == {
            "team_id": "42",
            "evaluation_id": "evaluation-123",
            "ai_product": "aio_eval_summary",
        }
        assert result is mock_async_openai.return_value


class TestOpenAIClientPrivacyMode:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @pytest.mark.parametrize(
        "builder,client_target",
        [(build_openai_client, "OpenAI"), (build_async_openai_client, "AsyncOpenAI")],
    )
    @pytest.mark.parametrize("privacy_mode", [True, False])
    def test_gateway_mode_sends_privacy_header_only_when_asked(self, builder, client_target, privacy_mode):
        with patch(f"posthog.llm.gateway_client.{client_target}") as mock_client:
            builder(ai_product="logs", privacy_mode=privacy_mode)

        headers = mock_client.call_args.kwargs["default_headers"]
        assert ("X-PostHog-Privacy-Mode" in headers) is privacy_mode
        if privacy_mode:
            assert headers["X-PostHog-Privacy-Mode"] == "true"


class TestTeamTraceId:
    # Expected ids are $ai_trace_id values observed on captured events, not recomputed from the
    # helper: recomputing would make the test agree with itself and miss a namespace change.
    @pytest.mark.parametrize(
        "team_id,expected",
        [
            (2, "aba5a277-3ba6-5682-a2da-f455d39e8aff"),
            (1589, "2e803550-d2e1-5dd7-9124-0fdd7e8c9518"),
            (169318, "92733d55-3d1e-5062-905b-0afa3b2e2a92"),
            (487950, "78c3f90a-d69e-5fe6-b2b2-3f22a4d7ebb1"),
        ],
    )
    def test_matches_captured_trace_ids(self, team_id: int, expected: str):
        assert team_trace_id(team_id) == expected

    def test_unattributed_call_has_no_trace_id(self):
        assert team_trace_id(None) is None

    def test_distinct_teams_do_not_share_a_trace(self):
        assert team_trace_id(2) != team_trace_id(3)


class TestTraceIdFromSeed:
    def test_distinct_seeds_do_not_share_a_trace(self):
        assert trace_id_from_seed("slack-thread-T1-1.1") != trace_id_from_seed("slack-thread-T1-1.2")


class TestBuildAsyncAnthropicClient:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.AsyncClient")
    @patch("posthog.llm.gateway_client.AsyncAnthropic")
    def test_gateway_mode_strips_v1_and_labels_product_stage_and_team(self, mock_anthropic, mock_httpx):
        result = build_async_anthropic_client(ai_product="signals_grouping", ai_stage="match", team_id=42)

        mock_httpx.assert_called_once_with(trust_env=False)
        mock_anthropic.assert_called_once()
        kwargs = mock_anthropic.call_args.kwargs
        assert kwargs["api_key"] == AI_GATEWAY_KEY
        assert kwargs["base_url"] == "https://ai-gateway.example"
        assert kwargs["http_client"] is mock_httpx.return_value
        headers = kwargs["default_headers"]
        assert json.loads(headers["X-PostHog-Properties"]) == {
            "ai_product": "signals_grouping",
            "ai_stage": "match",
            "team_id": "42",
        }
        assert headers["X-PostHog-Product"] == "signals_grouping"
        assert headers["X-PostHog-Trace-Id"] == TEAM_42_TRACE_ID
        assert result is mock_anthropic.return_value

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.AsyncClient")
    @patch("posthog.llm.gateway_client.AsyncAnthropic")
    def test_gateway_mode_uses_the_callers_trace_and_properties(self, mock_anthropic, mock_httpx):
        build_async_anthropic_client(
            ai_product="signals_safety",
            ai_stage="signal_safety",
            team_id=42,
            trace_id="decision-1",
            properties={"signals_decision_id": "decision-1", "source_product": "linear"},
        )

        _, kwargs = mock_anthropic.call_args
        headers = kwargs["default_headers"]
        assert headers["X-PostHog-Trace-Id"] == "decision-1"
        assert json.loads(headers["X-PostHog-Properties"]) == {
            "ai_product": "signals_safety",
            "ai_stage": "signal_safety",
            "signals_decision_id": "decision-1",
            "source_product": "linear",
            "team_id": "42",
        }

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.AsyncClient")
    @patch("posthog.llm.gateway_client.AsyncAnthropic")
    def test_gateway_mode_omits_trace_header_when_team_id_unset(self, mock_anthropic, mock_httpx):
        build_async_anthropic_client(ai_product="signals_grouping", ai_stage="match")

        _, kwargs = mock_anthropic.call_args
        assert "X-PostHog-Trace-Id" not in kwargs["default_headers"]

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.AsyncClient")
    @patch("posthog.llm.gateway_client.AsyncAnthropic")
    def test_gateway_mode_sends_trace_header_alongside_properties(self, mock_anthropic, mock_httpx):
        # The emission path replaces the properties blob per call and the gateway strips
        # $-prefixed keys, so the trace has to ride its own header.
        build_async_anthropic_client(team_id=42)

        _, kwargs = mock_anthropic.call_args
        assert kwargs["default_headers"] == {
            "X-PostHog-Properties": json.dumps({"team_id": "42"}),
            "X-PostHog-Trace-Id": TEAM_42_TRACE_ID,
        }

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.AsyncClient")
    @patch("posthog.llm.gateway_client.AsyncAnthropic")
    def test_gateway_mode_omits_stage_when_unset(self, mock_anthropic, mock_httpx):
        build_async_anthropic_client(ai_product="signals")

        _, kwargs = mock_anthropic.call_args
        assert kwargs["default_headers"] == {
            "X-PostHog-Properties": json.dumps({"ai_product": "signals"}),
            "X-PostHog-Product": "signals",
        }


class TestBuildAnthropicClient:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.Anthropic")
    def test_gateway_mode_uses_native_messages_base_and_preserves_attribution(self, mock_anthropic, mock_httpx):
        result = build_anthropic_client(
            ai_product="posthog_ai",
            trace_id="notebook-widget-job-1",
            properties={"source_product": "notebook_widget"},
            distinct_id="team-42",
            team_id=42,
        )

        kwargs = mock_anthropic.call_args.kwargs
        assert kwargs["api_key"] == AI_GATEWAY_KEY
        assert kwargs["base_url"] == "https://ai-gateway.example"
        assert kwargs["http_client"] is mock_httpx.return_value
        headers = kwargs["default_headers"]
        assert headers["X-PostHog-Trace-Id"] == "notebook-widget-job-1"
        assert headers["X-PostHog-Distinct-Id"] == "team-42"
        assert headers["X-PostHog-Product"] == "posthog_ai"
        assert json.loads(headers["X-PostHog-Properties"]) == {
            "ai_product": "posthog_ai",
            "source_product": "notebook_widget",
            "team_id": "42",
        }
        assert result is mock_anthropic.return_value

    @pytest.mark.parametrize("privacy_mode", [True, False])
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.Anthropic")
    def test_builds_the_go_gateway_client_with_attribution(self, mock_anthropic, mock_httpx, privacy_mode):
        result = build_anthropic_client(
            ai_product="aio_stamphog",
            properties={"source_product": "stamphog_digest"},
            distinct_id="team-42",
            team_id=42,
            privacy_mode=privacy_mode,
        )

        kwargs = mock_anthropic.call_args.kwargs
        assert kwargs["api_key"] == AI_GATEWAY_KEY
        assert kwargs["base_url"] == "https://ai-gateway.example"
        assert kwargs["http_client"] is mock_httpx.return_value
        headers = kwargs["default_headers"]
        assert headers["X-PostHog-Trace-Id"] == TEAM_42_TRACE_ID
        assert headers["X-PostHog-Distinct-Id"] == "team-42"
        assert json.loads(headers["X-PostHog-Properties"]) == {
            "ai_product": "aio_stamphog",
            "source_product": "stamphog_digest",
            "team_id": "42",
        }
        assert headers.get("X-PostHog-Privacy-Mode") == ("true" if privacy_mode else None)
        assert result is mock_anthropic.return_value


class TestBuildersRequireGoGateway:
    @pytest.mark.parametrize(
        "builder",
        [build_openai_client, build_async_openai_client, build_anthropic_client, build_async_anthropic_client],
        ids=["openai", "async_openai", "anthropic", "async_anthropic"],
    )
    @pytest.mark.parametrize(
        ("url", "api_key", "message"),
        [
            ("", "", "AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured.*bin/setup-gateway-e2e"),
            (AI_GATEWAY_URL, "", "AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be set together"),
            ("https://ai-gateway.example", AI_GATEWAY_KEY, "AI_GATEWAY_URL must include the OpenAI base path"),
        ],
        ids=["unset", "half_applied", "missing_v1"],
    )
    def test_raises_when_the_gateway_is_unset_or_misconfigured(self, builder, url, api_key, message):
        with override_settings(AI_GATEWAY_URL=url, AI_GATEWAY_API_KEY=api_key):
            with pytest.raises(GatewayNotConfiguredError, match=message):
                builder()


class TestBuildAIGatewayOpenAIClient:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.httpx.Client")
    @patch("posthog.llm.gateway_client.OpenAI")
    def test_uses_the_callers_credential_instead_of_the_shared_key(self, mock_openai, mock_httpx):
        result = build_ai_gateway_openai_client(
            api_key="pha_user_token",
            ai_product="custom_image_scans",
            session_id="session-42",
            properties={"team_id": "42"},
            distinct_id="team-42",
        )

        kwargs = mock_openai.call_args.kwargs
        assert kwargs["api_key"] == "pha_user_token"
        assert kwargs["base_url"] == AI_GATEWAY_URL
        assert kwargs["http_client"] is mock_httpx.return_value
        headers = kwargs["default_headers"]
        assert headers["X-PostHog-Product"] == "custom_image_scans"
        assert headers["X-PostHog-Distinct-Id"] == "team-42"
        assert headers["X-PostHog-Session-Id"] == "session-42"
        assert json.loads(headers["X-PostHog-Properties"]) == {"ai_product": "custom_image_scans", "team_id": "42"}
        assert result is mock_openai.return_value

    @pytest.mark.parametrize(
        ("url", "api_key", "message"),
        [
            ("", "pha_user_token", "AI_GATEWAY_URL is not set"),
            ("https://ai-gateway.example", "pha_user_token", "AI_GATEWAY_URL must end with /v1"),
            (AI_GATEWAY_URL, "", "api_key is required"),
        ],
    )
    def test_raises_when_the_gateway_is_not_configured(self, url, api_key, message):
        with override_settings(AI_GATEWAY_URL=url):
            with pytest.raises(GatewayNotConfiguredError, match=message):
                build_ai_gateway_openai_client(api_key=api_key, ai_product="custom_image_scans")


class TestBuildGeminiClient:
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @patch("posthog.llm.gateway_client.genai.Client")
    def test_gateway_mode_omits_privacy_header_unless_asked(self, mock_genai):
        build_gemini_client(ai_product="replay_vision")

        assert "X-PostHog-Privacy-Mode" not in mock_genai.call_args.kwargs["http_options"].headers

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    def test_real_client_sends_the_key_and_headers_to_the_native_route(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}]})

        client = build_gemini_client(ai_product="replay_vision", privacy_mode=True)
        assert client is not None
        sync_client, async_client = client._api_client._httpx_client, client._api_client._async_httpx_client
        assert sync_client is not None and sync_client.trust_env is False
        assert async_client is not None and async_client.trust_env is False
        client._api_client._httpx_client = httpx.Client(transport=httpx.MockTransport(handler))

        client.models.generate_content(model="models/gemini-test", contents="hi")

        assert str(seen[0].url) == "https://ai-gateway.example/v1beta/models/gemini-test:generateContent"
        assert seen[0].headers["x-goog-api-key"] == AI_GATEWAY_KEY
        assert seen[0].headers["x-posthog-product"] == "replay_vision"
        assert seen[0].headers["x-posthog-privacy-mode"] == "true"

    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    @pytest.mark.parametrize(
        "url",
        [
            "https://generativelanguage.googleapis.com/upload/v1beta/files",
            "http://ai-gateway.example/v1beta/files",
            "http://ai-gateway.example:443/v1beta/files",
            "https://ai-gateway.example:8443/v1beta/files",
        ],
    )
    def test_both_transports_refuse_any_origin_but_the_gateway(self, url):
        seen: list[httpx.Request] = []
        client = build_gemini_client(ai_product="replay_vision")
        assert client is not None
        sync_client = client._api_client._httpx_client
        async_client = client._api_client._async_httpx_client
        assert sync_client is not None and async_client is not None

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        sync_client._transport = httpx.MockTransport(handler)
        async_client._transport = httpx.MockTransport(handler)

        with pytest.raises(AIGatewayHostError):
            sync_client.post(url)
        with pytest.raises(AIGatewayHostError):
            asyncio.run(async_client.post(url))
        sync_client.get("https://ai-gateway.example/v1beta/files/abc")
        asyncio.run(async_client.get("https://ai-gateway.example/v1beta/files/abc"))

        assert [str(r.url) for r in seen] == ["https://ai-gateway.example/v1beta/files/abc"] * 2

    @pytest.mark.parametrize(
        ("url", "api_key"),
        [("", ""), (AI_GATEWAY_URL, ""), ("", AI_GATEWAY_KEY), ("https://ai-gateway.example", AI_GATEWAY_KEY)],
    )
    @patch("posthog.llm.gateway_client.genai.Client")
    def test_unset_or_misconfigured_returns_none_so_the_caller_stays_direct(self, mock_genai, url, api_key):
        with override_settings(AI_GATEWAY_URL=url, AI_GATEWAY_API_KEY=api_key):
            assert build_gemini_client(ai_product="replay_vision") is None
        mock_genai.assert_not_called()


class TestPrivateScoutGateway:
    @pytest.mark.parametrize(
        ("builder", "sdk", "suffix"),
        [
            ("build_openai_client", "OpenAI", "/v1"),
            ("build_async_openai_client", "AsyncOpenAI", "/v1"),
            ("build_anthropic_client", "Anthropic", ""),
            ("build_async_anthropic_client", "AsyncAnthropic", ""),
        ],
    )
    @override_settings(
        SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True,
        AI_GATEWAY_URL=AI_GATEWAY_URL,
        AI_GATEWAY_API_KEY=AI_GATEWAY_KEY,
    )
    def test_every_builder_uses_scoped_go_token_instead_of_shared_key(
        self, builder: str, sdk: str, suffix: str
    ) -> None:
        with patch.object(gateway_client, sdk) as client, private_scout_gateway("phe_trial_credential"):
            getattr(gateway_client, builder)()
        assert client.call_args.kwargs["base_url"] == f"https://ai-gateway.example{suffix}"
        assert client.call_args.kwargs["api_key"] == "phe_trial_credential"

    @pytest.mark.parametrize(
        ("enabled", "url", "token"),
        [
            (False, AI_GATEWAY_URL, "phe_trial_credential"),
            (True, "", "phe_trial_credential"),
            (True, "https://ai-gateway.example", "phe_trial_credential"),
            (True, AI_GATEWAY_URL, ""),
            (True, AI_GATEWAY_URL, "pha_trial_credential"),
            (True, AI_GATEWAY_URL, AI_GATEWAY_KEY),
        ],
    )
    @override_settings(AI_GATEWAY_URL=AI_GATEWAY_URL, AI_GATEWAY_API_KEY=AI_GATEWAY_KEY)
    def test_invalid_private_config_fails_before_building_any_client(self, enabled: bool, url: str, token: str) -> None:
        with (
            override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=enabled, AI_GATEWAY_URL=url),
            patch.object(gateway_client, "OpenAI") as client,
        ):
            with pytest.raises(GatewayNotConfiguredError), private_scout_gateway(token):
                build_openai_client()
        client.assert_not_called()
        assert resolve_ai_gateway_config() == AIGatewayConfig(url=AI_GATEWAY_URL, api_key=AI_GATEWAY_KEY)

    @override_settings(
        SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True,
        AI_GATEWAY_URL=AI_GATEWAY_URL,
        AI_GATEWAY_API_KEY=AI_GATEWAY_KEY,
    )
    def test_context_crosses_async_bridges_and_isolates_concurrent_calls(self) -> None:
        def read_credential() -> str:
            with build_openai_client() as client:
                return client.api_key

        async def read_config() -> tuple[AIGatewayConfig | None, str]:
            await asyncio.sleep(0)
            return await sync_to_async(resolve_ai_gateway_config)(), await sync_to_async(read_credential)()

        async def run_concurrently() -> None:
            async def trial(credential: str) -> tuple[AIGatewayConfig | None, str]:
                with private_scout_gateway(credential):
                    assert await sync_to_async(lambda: get_query_tags().is_scout_experiment)() is True
                    return await read_config()

            first, second, ordinary = await asyncio.gather(
                trial("phe_first_credential"), trial("phe_second_credential"), read_config()
            )
            assert first == (
                AIGatewayConfig(url=AI_GATEWAY_URL, api_key="phe_first_credential"),
                "phe_first_credential",
            )
            assert second == (
                AIGatewayConfig(url=AI_GATEWAY_URL, api_key="phe_second_credential"),
                "phe_second_credential",
            )
            assert ordinary == (AIGatewayConfig(url=AI_GATEWAY_URL, api_key=AI_GATEWAY_KEY), AI_GATEWAY_KEY)

        async_to_sync(run_concurrently)()
        with pytest.raises(RuntimeError), private_scout_gateway("phe_trial_credential"):
            with private_scout_gateway("phe_nested_credential"):
                assert async_to_sync(read_config)() == (
                    AIGatewayConfig(url=AI_GATEWAY_URL, api_key="phe_nested_credential"),
                    "phe_nested_credential",
                )
            assert resolve_ai_gateway_config() == AIGatewayConfig(url=AI_GATEWAY_URL, api_key="phe_trial_credential")
            assert read_credential() == "phe_trial_credential"
            raise RuntimeError("validation failed")
        assert resolve_ai_gateway_config() == AIGatewayConfig(url=AI_GATEWAY_URL, api_key=AI_GATEWAY_KEY)
        assert read_credential() == AI_GATEWAY_KEY
        assert get_query_tags().is_scout_experiment is not True

    @override_settings(
        SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True,
        AI_GATEWAY_URL=AI_GATEWAY_URL,
        AI_GATEWAY_API_KEY=AI_GATEWAY_KEY,
    )
    def test_go_only_client_uses_private_context(self) -> None:
        with patch.object(gateway_client, "Anthropic") as client, private_scout_gateway("phe_trial_credential"):
            build_anthropic_client()
        assert client.call_args.kwargs["api_key"] == "phe_trial_credential"
