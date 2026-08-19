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


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered_name = name.lower()
    return next((value for key, value in headers.items() if key.lower() == lowered_name), None)


def _parse_slack_rate_limit(response: requests.Response) -> RateLimitSnapshot:
    retry_after = _header(response.headers, "Retry-After")
    if response.status_code != 429 or retry_after is None:
        return RateLimitSnapshot()
    try:
        reset_at = time.time() + float(retry_after)
    except (TypeError, ValueError):
        reset_at = None
    return RateLimitSnapshot(resource="retry_after", reset_at=reset_at)


slack_egress = EgressObservability(SLACK_DOMAIN, _metrics, _parse_slack_rate_limit)
register_egress_observability(slack_egress)


def record_slack_api_response(
    response: object,
    *,
    source: str,
    workspace_id: str | None,
    method: str,
    endpoint: str,
) -> None:
    slack_egress.record_response(
        cast(requests.Response, response),
        source=source,
        scope=workspace_id,
        method=method,
        endpoint=endpoint,
    )


def record_slack_api_exception(*, source: str, workspace_id: str | None, method: str, endpoint: str) -> None:
    slack_egress.record_exception(source=source, scope=workspace_id, method=method, endpoint=endpoint)
