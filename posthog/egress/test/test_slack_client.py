from typing import Any

from unittest.mock import patch

from prometheus_client import REGISTRY
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse
from slack_sdk.http_retry.state import RetryState

from posthog.egress.slack.client import SlackWebClient


class ImmediateRateLimitRetryHandler(RateLimitErrorRetryHandler):
    def prepare_for_next_attempt(
        self,
        *,
        state: RetryState,
        request: HttpRequest,
        response: HttpResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        state.next_attempt_requested = True
        state.increment_current_attempt()


def _request_count(status_code: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "slack_api_requests_total",
            {
                "workspace_id": "T123",
                "method": "POST",
                "endpoint": "conversations.history",
                "status_code": status_code,
                "source": "test",
            },
        )
        or 0
    )


def test_slack_web_client_records_each_retry_attempt() -> None:
    client = SlackWebClient(token="xoxb-test", source="test", workspace_id="T123", app_id="posthog")
    client.retry_handlers.append(ImmediateRateLimitRetryHandler(max_retry_count=1))
    responses: list[dict[str, Any]] = [
        {
            "status": 429,
            "headers": {"Retry-After": ["30"]},
            "body": '{"ok": false, "error": "ratelimited"}',
        },
        {"status": 200, "headers": {}, "body": '{"ok": true}'},
    ]
    success_before = _request_count("200")
    rate_limited_before = _request_count("429")

    with patch.object(client, "_perform_urllib_http_request_internal", side_effect=responses):
        assert client.conversations_history(channel="C123")["ok"] is True

    assert _request_count("200") == success_before + 1
    assert _request_count("429") == rate_limited_before + 1
    assert (
        REGISTRY.get_sample_value(
            "slack_api_rate_limit_reset_timestamp_seconds",
            {"workspace_id": "T123", "resource": "posthog:conversations.history"},
        )
        is not None
    )
