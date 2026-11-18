"""Tests for clustering labeling client construction (ai-gateway vs direct OpenAI)."""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import httpx
import openai
from openai import APIStatusError, APITimeoutError, InternalServerError, RateLimitError
from temporalio.exceptions import ApplicationError

from posthog.llm.openai_flex import FLEX_CAPABLE_MODELS
from posthog.temporal.ai_observability.eval_reports.constants import EVAL_REPORT_AGENT_MODEL
from posthog.temporal.ai_observability.llm_endpoint import (
    AI_FEATURES_CLOUD_ONLY_ERROR_TYPE,
    FLEX_CALL_TIMEOUT,
    FLEX_REPROBE_COOLDOWN,
    STANDARD_CALL_TIMEOUT,
    FlexFirstChatOpenAI,
    build_flex_first_chat_client,
    build_langchain_callbacks,
    build_langchain_chat_client,
)
from posthog.temporal.ai_observability.trace_clustering.constants import LABELING_AGENT_MODEL
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
        with patch("posthog.temporal.ai_observability.llm_endpoint.FlexFirstChatOpenAI") as mock_chat:
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
        with patch("posthog.temporal.ai_observability.llm_endpoint.FlexFirstChatOpenAI") as mock_chat:
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

    @pytest.mark.parametrize(
        "service_tier,expected",
        [
            ("flex", "flex"),
            (None, None),
        ],
    )
    def test_service_tier_reaches_the_client_in_both_routing_modes(self, service_tier, expected):
        # Dropping the tier silently doubles the labeling bill, so pin the passthrough.
        for gateway_url, gateway_key in [(GATEWAY_URL, GATEWAY_KEY), (None, None)]:
            with (
                override_settings(DEBUG=True, AI_GATEWAY_URL=gateway_url, AI_GATEWAY_API_KEY=gateway_key),
                patch.dict("os.environ", {"OPENAI_API_KEY": "sk-direct"}, clear=False),
            ):
                client = build_langchain_chat_client("gpt-5.4", 600.0, service_tier=service_tier)
                assert client.service_tier == expected

    def test_responses_api_clients_never_store_and_carry_reasoning_in_both_routing_modes(self):
        for gateway_url, gateway_key in [(GATEWAY_URL, GATEWAY_KEY), (None, None)]:
            with (
                override_settings(DEBUG=True, AI_GATEWAY_URL=gateway_url, AI_GATEWAY_API_KEY=gateway_key),
                patch.dict("os.environ", {"OPENAI_API_KEY": "sk-direct"}, clear=False),
            ):
                client = build_langchain_chat_client("gpt-6.1-terra", 600.0, use_responses_api=True)
                assert client.use_responses_api is True
                assert client.store is False
                assert client.include == ["reasoning.encrypted_content"]
                assert client.output_version == "responses/v1"

    @pytest.mark.parametrize(
        "model,expected_tier",
        [
            ("gpt-5.4", "flex"),
            # OpenAI excludes pro tiers from flex, so the family prefix must not grant it.
            ("gpt-5.4-pro", None),
            # gpt-4.1 models reject the service_tier field, so a fallback to them must not send it.
            ("gpt-4.1-mini", None),
        ],
    )
    def test_labeling_llm_requests_flex_only_for_allowlisted_models(self, model, expected_tier):
        from posthog.temporal.ai_observability.clustering_agent import get_labeling_llm

        with (
            override_settings(DEBUG=True, AI_GATEWAY_URL=GATEWAY_URL, AI_GATEWAY_API_KEY=GATEWAY_KEY),
        ):
            client = get_labeling_llm(
                model,
                600.0,
                trace_id="t",
                session_id="s",
                properties={},
                distinct_id="d",
            )
            assert client.service_tier == expected_tier

    @pytest.mark.parametrize("model", [EVAL_REPORT_AGENT_MODEL, LABELING_AGENT_MODEL])
    def test_every_batch_agent_runs_a_flex_capable_model(self, model):
        # A model outside the allowlist keeps working and silently doubles that agent's bill.
        assert model in FLEX_CAPABLE_MODELS

    def test_labeling_clients_bound_every_call_inside_the_activity_budget(self):
        from posthog.temporal.ai_observability.clustering_agent import get_labeling_llm

        with override_settings(DEBUG=True, AI_GATEWAY_URL=GATEWAY_URL, AI_GATEWAY_API_KEY=GATEWAY_KEY):
            flex_client = get_labeling_llm(
                "gpt-5.4", 600.0, trace_id="t", session_id="s", properties={}, distinct_id="d"
            )
            standard_client = get_labeling_llm(
                "gpt-5.4", 600.0, trace_id="t", session_id="s", properties={}, distinct_id="d", flex=False
            )

        assert flex_client.request_timeout == STANDARD_CALL_TIMEOUT
        assert flex_client.max_retries == 1
        assert standard_client.service_tier is None
        assert standard_client.request_timeout == STANDARD_CALL_TIMEOUT
        assert standard_client.max_retries == 1


_FLEX_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")

_COMPLETION = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-5.4",
    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "labeled"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


_RESPONSE = openai.types.responses.Response.model_validate(
    {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": "gpt-6.1-terra",
        "status": "completed",
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "reported", "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
)


def _flex_client(service_tier: str | None = "flex") -> FlexFirstChatOpenAI:
    return FlexFirstChatOpenAI(
        model="gpt-5.4",
        api_key="sk-test",
        max_retries=0,
        service_tier=service_tier,
    )


def _mock_create(*results: object) -> MagicMock:
    """Mock client.with_raw_response.create: raise exceptions as-is, wrap dicts as raw responses."""

    def to_side_effect(result: object) -> object:
        if isinstance(result, Exception):
            return result
        raw = MagicMock()
        raw.parse.return_value = result
        raw.headers = {}
        return raw

    create = MagicMock(side_effect=[to_side_effect(result) for result in results])
    client = MagicMock()
    client.with_raw_response.create = create
    return client


def _mock_stream(is_async: bool = False) -> MagicMock:
    """Mock client.create for a streamed completion: one content chunk, then a stop."""
    chunks = [
        {
            "id": "1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "gpt-5.4",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": "labeled"}, "finish_reason": None}],
        },
        {
            "id": "1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "gpt-5.4",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]

    class _Stream:
        def __enter__(self):
            return iter(chunks)

        def __exit__(self, *_):
            return False

        async def __aenter__(self):
            async def gen():
                for chunk in chunks:
                    yield chunk

            return gen()

        async def __aexit__(self, *_):
            return False

    client = MagicMock()
    client.create = AsyncMock(return_value=_Stream()) if is_async else MagicMock(return_value=_Stream())
    return client


class TestFlexFirstChatOpenAI:
    @pytest.mark.parametrize("use_responses_api", [False, True])
    @pytest.mark.parametrize("is_async", [False, True])
    @pytest.mark.parametrize("standard_recovers", [False, True])
    @pytest.mark.parametrize("capacity_refused", [False, True])
    async def test_flex_recovery_bounds_attempts_per_call(
        self, use_responses_api: bool, is_async: bool, standard_recovers: bool, capacity_refused: bool
    ) -> None:
        requests: list[tuple[str, float]] = []
        clock = {"now": 0.0}

        def handle(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert "timeout" not in payload
            assert "max_retries" not in payload
            requests.append((payload["service_tier"], request.extensions["timeout"]["read"]))
            if len(requests) == 1 and capacity_refused:
                return httpx.Response(429, json={"error": {"message": "capacity refused"}})
            if len(requests) in (1, 3) or (len(requests) == 2 and not standard_recovers):
                raise httpx.ReadTimeout("stalled request", request=request)
            return httpx.Response(200, json=_RESPONSE.model_dump() if use_responses_api else _COMPLETION)

        transport = httpx.MockTransport(handle)
        with (
            override_settings(DEBUG=True, AI_GATEWAY_URL="", AI_GATEWAY_API_KEY=""),
            patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}),
            patch("openai._base_client.time.sleep"),
            patch("openai._base_client.anyio.sleep", new_callable=AsyncMock),
            patch("posthog.temporal.ai_observability.llm_endpoint.time.monotonic", lambda: clock["now"]),
            httpx.Client(transport=transport) as sync_http,
        ):
            async with httpx.AsyncClient(transport=transport) as async_http:
                llm = build_flex_first_chat_client(
                    "gpt-6.1-terra" if use_responses_api else "gpt-5.4",
                    600.0,
                    ai_product="aio_eval_reports",
                    trace_id="test-trace",
                    session_id="test-session",
                    properties={},
                    distinct_id="test-user",
                    use_responses_api=use_responses_api,
                )
                llm.root_client = llm.root_client.with_options(http_client=sync_http)
                llm.client = llm.root_client.chat.completions
                llm.root_async_client = llm.root_async_client.with_options(http_client=async_http)
                llm.async_client = llm.root_async_client.chat.completions

                if standard_recovers:
                    result = await llm.ainvoke("label the clusters") if is_async else llm.invoke("label the clusters")
                    assert result.text() == ("reported" if use_responses_api else "labeled")
                else:
                    with pytest.raises(APITimeoutError):
                        if is_async:
                            await llm.ainvoke("label the clusters")
                        else:
                            llm.invoke("label the clusters")

                assert requests == [("flex", FLEX_CALL_TIMEOUT), ("default", STANDARD_CALL_TIMEOUT)]
                if capacity_refused and standard_recovers:
                    clock["now"] = FLEX_REPROBE_COOLDOWN + 1
                result = (
                    await llm.ainvoke("label the next cluster") if is_async else llm.invoke("label the next cluster")
                )
                assert result.text() == ("reported" if use_responses_api else "labeled")

        next_attempt = (
            ("flex", FLEX_CALL_TIMEOUT)
            if capacity_refused and standard_recovers
            else ("default", STANDARD_CALL_TIMEOUT)
        )
        assert requests == [
            ("flex", FLEX_CALL_TIMEOUT),
            ("default", STANDARD_CALL_TIMEOUT),
            next_attempt,
            ("default", STANDARD_CALL_TIMEOUT),
        ]

    @pytest.mark.parametrize("is_async,use_responses_api", [(False, False), (True, True)])
    async def test_streamed_invoke_propagates_failure_without_fallback(
        self, is_async: bool, use_responses_api: bool
    ) -> None:
        tiers: list[str] = []

        def handle(request: httpx.Request) -> httpx.Response:
            tiers.append(json.loads(request.content)["service_tier"])
            raise httpx.ReadTimeout("stalled stream", request=request)

        transport = httpx.MockTransport(handle)
        with (
            patch("openai._base_client.time.sleep"),
            patch("openai._base_client.anyio.sleep", new_callable=AsyncMock),
            httpx.Client(transport=transport) as sync_http,
        ):
            async with httpx.AsyncClient(transport=transport) as async_http:
                llm = FlexFirstChatOpenAI(
                    model="gpt-6.1-terra" if use_responses_api else "gpt-5.4",
                    api_key="sk-test",
                    service_tier="flex",
                    timeout=STANDARD_CALL_TIMEOUT,
                    max_retries=1,
                    streaming=True,
                    http_client=sync_http,
                    http_async_client=async_http,
                    use_responses_api=use_responses_api,
                )
                with pytest.raises(APITimeoutError):
                    if is_async:
                        await llm.ainvoke("label the clusters")
                    else:
                        llm.invoke("label the clusters")

        assert tiers == ["flex"]

    @pytest.mark.parametrize(
        "error",
        [
            RateLimitError("capacity refused", response=httpx.Response(429, request=_FLEX_REQUEST), body=None),
            APIStatusError("flex timeout", response=httpx.Response(408, request=_FLEX_REQUEST), body=None),
            InternalServerError("gateway 504", response=httpx.Response(504, request=_FLEX_REQUEST), body=None),
            APITimeoutError(request=_FLEX_REQUEST),
            APIStatusError("conflict", response=httpx.Response(409, request=_FLEX_REQUEST), body=None),
        ],
    )
    def test_recoverable_flex_failure_retries_that_call_on_standard(self, error):
        llm = _flex_client()
        llm.client = _mock_create(error, _COMPLETION)

        result = llm.invoke("label the clusters")

        assert result.content == "labeled"
        first, second = llm.client.with_raw_response.create.call_args_list
        assert first.kwargs["service_tier"] == "flex"
        assert second.kwargs["service_tier"] == "default"

    def test_responses_api_flex_failure_retries_that_call_on_standard(self):
        llm = FlexFirstChatOpenAI(
            model="gpt-6.1-terra",
            api_key="sk-test",
            max_retries=0,
            service_tier="flex",
            use_responses_api=True,
            store=False,
            include=["reasoning.encrypted_content"],
            output_version="responses/v1",
        )
        refusal = RateLimitError("capacity refused", response=httpx.Response(429, request=_FLEX_REQUEST), body=None)
        create = _mock_create(refusal, _RESPONSE).with_raw_response.create
        llm.root_client = MagicMock()
        llm.root_client.responses.with_raw_response.create = create

        result = llm.invoke("write the report")

        assert result.text() == "reported"
        first, second = create.call_args_list
        assert first.kwargs["service_tier"] == "flex"
        assert second.kwargs["service_tier"] == "default"

    def test_non_recoverable_error_propagates_without_fallback(self):
        llm = _flex_client()
        llm.client = _mock_create(
            openai.BadRequestError("bad request", response=httpx.Response(400, request=_FLEX_REQUEST), body=None)
        )

        with pytest.raises(openai.BadRequestError):
            llm.invoke("label the clusters")

        assert llm.client.with_raw_response.create.call_count == 1

    def test_a_refusal_holds_the_client_on_standard_inside_the_cooldown(self):
        llm = _flex_client()
        llm.client = _mock_create(
            RateLimitError("capacity refused", response=httpx.Response(429, request=_FLEX_REQUEST), body=None),
            _COMPLETION,
            _COMPLETION,
        )

        llm.invoke("label the clusters")
        llm.invoke("label the next cluster")

        third = llm.client.with_raw_response.create.call_args_list[2]
        assert third.kwargs["service_tier"] == "default"

    @pytest.mark.parametrize(
        "error,tier_after_cooldown",
        [
            (
                RateLimitError("capacity refused", response=httpx.Response(429, request=_FLEX_REQUEST), body=None),
                "flex",
            ),
            (APITimeoutError(request=_FLEX_REQUEST), "default"),
        ],
    )
    def test_flex_returns_after_a_refusal_but_stays_off_after_a_stall(self, error, tier_after_cooldown):
        llm = _flex_client()
        llm.client = _mock_create(error, _COMPLETION, _COMPLETION)
        clock = {"now": 0.0}

        with patch("posthog.temporal.ai_observability.llm_endpoint.time.monotonic", lambda: clock["now"]):
            llm.invoke("label the clusters")
            clock["now"] = FLEX_REPROBE_COOLDOWN + 1
            llm.invoke("label the next cluster")

        third = llm.client.with_raw_response.create.call_args_list[2]
        assert third.kwargs["service_tier"] == tier_after_cooldown

    @pytest.mark.parametrize("latched,expected", [(False, "flex"), (True, "default")])
    def test_streaming_asks_for_the_same_tier_as_a_buffered_call(self, latched, expected):
        llm = _flex_client()
        llm._flex_latched = latched
        llm.client = _mock_stream()

        list(llm.stream("label the clusters"))

        assert llm.client.create.call_args.kwargs["service_tier"] == expected

    async def test_async_streaming_asks_for_flex_too(self):
        llm = _flex_client()
        llm.async_client = _mock_stream(is_async=True)

        async for _ in llm.astream("label the clusters"):
            pass

        assert llm.async_client.create.call_args.kwargs["service_tier"] == "flex"

    def test_a_caller_cannot_override_the_tier_the_client_chose(self):
        llm = _flex_client()
        llm.client = _mock_create(_COMPLETION)

        llm.invoke("label the clusters", service_tier="default")

        assert llm.client.with_raw_response.create.call_args.kwargs["service_tier"] == "flex"

    def test_standard_client_never_falls_back(self):
        llm = _flex_client(service_tier=None)
        llm.client = _mock_create(
            RateLimitError("rate limited", response=httpx.Response(429, request=_FLEX_REQUEST), body=None)
        )

        with pytest.raises(RateLimitError):
            llm.invoke("label the clusters")

        assert llm.client.with_raw_response.create.call_count == 1

    @pytest.mark.asyncio
    async def test_async_path_falls_back_too(self):
        llm = _flex_client()
        flex_raw = RateLimitError("capacity refused", response=httpx.Response(429, request=_FLEX_REQUEST), body=None)
        standard_raw = MagicMock()
        standard_raw.parse.return_value = _COMPLETION
        standard_raw.headers = {}
        create = AsyncMock(side_effect=[flex_raw, standard_raw])
        llm.async_client = MagicMock()
        llm.async_client.with_raw_response.create = create

        result = await llm.ainvoke("label the clusters")

        assert result.content == "labeled"
        assert create.call_args_list[1].kwargs["service_tier"] == "default"
