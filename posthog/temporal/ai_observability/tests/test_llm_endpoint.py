"""Tests for clustering labeling client construction (ai-gateway vs direct OpenAI)."""

import json

import pytest
from unittest.mock import patch

from django.test import override_settings

from temporalio.exceptions import ApplicationError

from posthog.temporal.ai_observability.llm_endpoint import (
    AI_FEATURES_CLOUD_ONLY_ERROR_TYPE,
    build_langchain_callbacks,
    build_langchain_chat_client,
)
from posthog.temporal.common.posthog_client import EXPECTED_CONTROL_FLOW_ERROR_TYPES

GATEWAY_URL = "https://gateway.example/v1"
GATEWAY_KEY = "phs_project_secret"


class TestBuildOpenAIChatClient:
    @override_settings(DEBUG=False)
    @patch("posthog.temporal.ai_observability.llm_endpoint.is_cloud", return_value=False)
    def test_non_cloud_guard_raises_non_retryable_non_reportable_error(self, _mock_is_cloud):
        # A non-cloud, non-DEBUG deployment has no AI gateway, so the guard must stop the activity
        # without a retry and without filing an error tracking issue.
        with pytest.raises(ApplicationError) as exc_info:
            build_langchain_chat_client("gpt-5.4", 600.0)

        assert exc_info.value.non_retryable is True
        assert exc_info.value.type == AI_FEATURES_CLOUD_ONLY_ERROR_TYPE
        assert AI_FEATURES_CLOUD_ONLY_ERROR_TYPE in EXPECTED_CONTROL_FLOW_ERROR_TYPES

    @pytest.mark.parametrize(
        "gateway_url,gateway_key,expected_base,expected_key,custom_http_client",
        [
            (GATEWAY_URL, GATEWAY_KEY, GATEWAY_URL, GATEWAY_KEY, True),
            (None, None, None, "sk-direct", False),
        ],
    )
    def test_routing_resolves_endpoint_and_credentials(
        self, gateway_url, gateway_key, expected_base, expected_key, custom_http_client
    ):
        with (
            override_settings(DEBUG=True, AI_GATEWAY_URL=gateway_url, AI_GATEWAY_API_KEY=gateway_key),
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-direct"}, clear=False),
        ):
            client = build_langchain_chat_client("gpt-5.4", 600.0)

        assert client.openai_api_base == expected_base
        api_key = client.openai_api_key
        assert api_key is not None
        assert api_key.get_secret_value() == expected_key
        # Gateway mode injects a trust_env=False http client; direct mode uses the SDK default.
        if custom_http_client:
            assert client.http_client is not None
            assert client.http_async_client is not None
        else:
            assert client.http_client is None

    @pytest.mark.parametrize(
        "gateway_url,gateway_key,reason",
        [
            (GATEWAY_URL, None, "must be set together"),
            (None, GATEWAY_KEY, "must be set together"),
            ("https://gateway.example", GATEWAY_KEY, "OpenAI base path"),
        ],
    )
    def test_misconfigured_gateway_falls_back_to_direct_and_logs(self, gateway_url, gateway_key, reason):
        # Radu review: a half-applied / malformed gateway config falls back to the direct provider
        # rather than failing the call, and logs loudly so a broken rollout config is visible.
        with (
            override_settings(DEBUG=True, AI_GATEWAY_URL=gateway_url, AI_GATEWAY_API_KEY=gateway_key),
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-direct"}, clear=False),
            # the shared resolver in gateway_client owns the misconfig warning
            patch("posthog.llm.gateway_client.logger") as mock_logger,
        ):
            client = build_langchain_chat_client("gpt-5.4", 600.0)

        assert client.openai_api_base is None
        api_key = client.openai_api_key
        assert api_key is not None
        assert api_key.get_secret_value() == "sk-direct"
        mock_logger.warning.assert_called_once()
        assert reason in str(mock_logger.warning.call_args)

    @override_settings(DEBUG=True, AI_GATEWAY_URL=GATEWAY_URL, AI_GATEWAY_API_KEY=GATEWAY_KEY)
    def test_gateway_mode_tags_ai_product_via_posthog_properties_header(self):
        with patch("posthog.temporal.ai_observability.llm_endpoint.ChatOpenAI") as mock_chat:
            build_langchain_chat_client(
                "gpt-5.4",
                600.0,
                ai_product="aio_clustering",
                trace_id="clustering-run-1",
                session_id="clustering-run-1:session",
                properties={"team_id": "42", "analysis_level": "trace", "clustering_job_id": "job-1"},
                distinct_id="42",
            )

        headers = mock_chat.call_args.kwargs["default_headers"]
        assert headers == {
            "X-PostHog-Product": "aio_clustering",
            "X-PostHog-Properties": json.dumps(
                {
                    "team_id": "42",
                    "analysis_level": "trace",
                    "clustering_job_id": "job-1",
                    "ai_product": "aio_clustering",
                }
            ),
            "X-PostHog-Trace-Id": "clustering-run-1",
            "X-PostHog-Session-Id": "clustering-run-1:session",
            "X-PostHog-Distinct-Id": "42",
        }

    @override_settings(DEBUG=True, AI_GATEWAY_URL=GATEWAY_URL, AI_GATEWAY_API_KEY=GATEWAY_KEY)
    def test_gateway_mode_without_ai_product_omits_header(self):
        with patch("posthog.temporal.ai_observability.llm_endpoint.ChatOpenAI") as mock_chat:
            build_langchain_chat_client("gpt-5.4", 600.0)

        assert mock_chat.call_args.kwargs["default_headers"] is None

    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    @patch("posthog.temporal.ai_observability.llm_endpoint.CallbackHandler")
    @patch("posthog.temporal.ai_observability.llm_endpoint.posthoganalytics")
    def test_direct_mode_callback_preserves_trace_and_session(self, mock_posthoganalytics, mock_callback):
        mock_posthoganalytics.default_client = object()

        callbacks = build_langchain_callbacks(
            distinct_id="42",
            trace_id="clustering-run-1",
            session_id="clustering-run-1:session",
            ai_product="aio_clustering",
            properties={"analysis_level": "trace"},
        )

        assert callbacks == [mock_callback.return_value]
        mock_callback.assert_called_once_with(
            mock_posthoganalytics.default_client,
            distinct_id="42",
            trace_id="clustering-run-1",
            properties={
                "analysis_level": "trace",
                "ai_product": "aio_clustering",
                "$ai_session_id": "clustering-run-1:session",
            },
        )

    @override_settings(DEBUG=True, AI_GATEWAY_URL=GATEWAY_URL, AI_GATEWAY_API_KEY=GATEWAY_KEY)
    @patch("posthog.temporal.ai_observability.llm_endpoint.CallbackHandler")
    @patch("posthog.temporal.ai_observability.llm_endpoint.posthoganalytics")
    def test_gateway_mode_omits_callback_to_avoid_duplicate_generations(self, mock_posthoganalytics, mock_callback):
        mock_posthoganalytics.default_client = object()

        callbacks = build_langchain_callbacks(
            distinct_id="42",
            trace_id="clustering-run-1",
            session_id="clustering-run-1:session",
            ai_product="aio_clustering",
        )

        assert callbacks == []
        mock_callback.assert_not_called()
