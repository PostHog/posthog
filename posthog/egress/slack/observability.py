import time
from collections.abc import Mapping
from typing import cast

import requests
from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    register_egress_observability,
)

SLACK_DOMAIN = "slack"


_metrics = EgressMetrics(
    request_counter=Counter(
        "slack_api_requests",
        "Number of Slack API requests made through a Slack egress client.",
        labelnames=["workspace_id", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "slack_api_rate_limit_remaining",
        "Slack API rate limit remaining count when reported by Slack.",
        labelnames=["workspace_id", "resource"],
    ),
    limit_gauge=Gauge(
        "slack_api_rate_limit_limit",
        "Slack API rate limit when reported by Slack.",
        labelnames=["workspace_id", "resource"],
    ),
    reset_gauge=Gauge(
        "slack_api_rate_limit_reset_timestamp_seconds",
        "Slack API retry timestamp after a rate-limited response.",
        labelnames=["workspace_id", "resource"],
    ),
)


def _header(headers: Mapping[str, object], name: str) -> str | None:
    lowered_name = name.lower()
    value = next((value for key, value in headers.items() if key.lower() == lowered_name), None)
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def _parse_slack_rate_limit(response: requests.Response) -> RateLimitSnapshot:
    return RateLimitSnapshot()


slack_egress = EgressObservability(SLACK_DOMAIN, _metrics, _parse_slack_rate_limit)
register_egress_observability(slack_egress)


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
    slack_egress.record_response(
        typed_response,
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
    _metrics.reset_gauge.labels(normalized_workspace_id, f"{app_id}:{endpoint}").set(reset_at)


def record_slack_api_exception(*, source: str, workspace_id: str | None, method: str, endpoint: str) -> None:
    slack_egress.record_exception(source=source, scope=workspace_id or None, method=method, endpoint=endpoint)
