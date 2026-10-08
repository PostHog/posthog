import time
from collections.abc import Mapping
from typing import cast
from urllib.parse import urlparse

import requests
from prometheus_client import Counter, Gauge
from slack_sdk.http_retry.request import HttpRequest
from slack_sdk.http_retry.response import HttpResponse

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

slack_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "slack_api_requests",
            "Number of Slack API requests made through a Slack egress client.",
            labelnames=["workspace_id", "method", "endpoint", "status_code", "source"],
        ),
    )
)

# Slack returns no remaining-budget headers. Its only budget signal is the Retry-After on a 429,
# which applies to one app and one Web API method, so the resource label carries both.
# One-off: the SDK retry handler sets it on a 429, outside the header parse `EgressMetrics` runs.
# nosemgrep: shared-mechanisms-stay-out-of-egress-and-ingress-domains
_retry_at_gauge = Gauge(
    "slack_api_rate_limit_reset_timestamp_seconds",
    "Slack API retry timestamp after a rate-limited response.",
    labelnames=["workspace_id", "resource"],
)


def _header(headers: Mapping[str, object], name: str) -> str | None:
    lowered_name = name.lower()
    value = next((value for key, value in headers.items() if key.lower() == lowered_name), None)
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def slack_endpoint_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc == "files.slack.com" and parsed.path.startswith("/upload/v1/"):
        return "files.uploadExternal.data"
    return parsed.path.rstrip("/").rsplit("/", 1)[-1] or "unknown"


def record_slack_api_response(
    response: object,
    *,
    source: str,
    workspace_id: str | None,
    app_id: str,
    method: str,
    endpoint: str,
) -> None:
    normalized_workspace_id = workspace_id or None
    typed_response = cast(requests.Response, response)
    headers = typed_response.headers if isinstance(typed_response.headers, Mapping) else None
    slack_egress.record_response(
        typed_response.status_code,
        headers,
        source=source,
        scope=normalized_workspace_id,
        method=method,
        endpoint=endpoint,
    )
    retry_after = _header(typed_response.headers, "Retry-After")
    if normalized_workspace_id is None or typed_response.status_code != 429 or retry_after is None:
        return
    try:
        reset_at = time.time() + float(retry_after)
    except ValueError:
        return
    _retry_at_gauge.labels(normalized_workspace_id, f"{app_id}:{endpoint}").set(reset_at)


def record_slack_attempt(
    *,
    source: str,
    workspace_id: str | None,
    app_id: str,
    request: HttpRequest,
    response: HttpResponse | None,
) -> None:
    """Record one Slack SDK attempt. The SDK calls its retry handlers once per HTTP attempt, with no
    response when the attempt raised, so a retried call counts once per request it sent."""
    endpoint = slack_endpoint_from_url(request.url)
    if response is None:
        slack_egress.record_exception(source=source, scope=workspace_id, method=request.method, endpoint=endpoint)
        return
    record_slack_api_response(
        response,
        source=source,
        workspace_id=workspace_id,
        app_id=app_id,
        method=request.method,
        endpoint=endpoint,
    )
