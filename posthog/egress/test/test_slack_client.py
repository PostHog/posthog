from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from prometheus_client import REGISTRY
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.web.slack_response import SlackResponse

from posthog.egress.slack.client import SlackWebClient


def _request_count(status_code: str, source: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "slack_api_requests_total",
            {
                "workspace_id": "T123",
                "method": "POST",
                "endpoint": "conversations.history",
                "status_code": status_code,
                "source": source,
            },
        )
        or 0
    )


def test_slack_web_client_records_successful_and_api_error_responses() -> None:
    client = SlackWebClient(token="xoxb-test", source="test", workspace_id="T123")
    success = cast(SlackResponse, SimpleNamespace(status_code=200, headers={}))
    rate_limited = cast(SlackResponse, SimpleNamespace(status_code=429, headers={"Retry-After": "30"}))
    success_before = _request_count("200", "test")
    error_before = _request_count("429", "test")

    with patch.object(WebClient, "api_call", return_value=success):
        assert client.api_call("conversations.history") is success

    with patch.object(
        WebClient,
        "api_call",
        side_effect=SlackApiError("rate_limited", rate_limited),
    ):
        try:
            client.api_call("conversations.history")
        except SlackApiError:
            pass
        else:
            raise AssertionError("SlackApiError was not raised")

    assert _request_count("200", "test") == success_before + 1
    assert _request_count("429", "test") == error_before + 1
