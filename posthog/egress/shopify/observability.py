"""Shopify egress telemetry.

Every Shopify call funnels through these recorders so request volume lands on one metric set,
attributed by the ``source`` label. We don't parse Shopify's GraphQL cost/throttle extensions yet, so
the parser returns an empty snapshot and the gauges stay unset — they exist because
:class:`EgressMetrics` requires the full instrument set, and they start reporting the moment a parser
is added.
"""

import requests
from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    register_egress_observability,
)

SHOPIFY_DOMAIN = "shopify"

_metrics = EgressMetrics(
    request_counter=Counter(
        "shopify_api_requests",
        "Number of Shopify API requests made through the Shopify egress client.",
        labelnames=["account", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "shopify_api_rate_limit_remaining",
        "Most recently observed Shopify rate limit remaining count (unset: cost extensions not parsed yet).",
        labelnames=["account", "resource"],
    ),
    limit_gauge=Gauge(
        "shopify_api_rate_limit_limit",
        "Most recently observed Shopify rate limit (unset: cost extensions not parsed yet).",
        labelnames=["account", "resource"],
    ),
    reset_gauge=Gauge(
        "shopify_api_rate_limit_reset_timestamp_seconds",
        "Most recently observed Shopify rate limit reset timestamp (unset: cost extensions not parsed yet).",
        labelnames=["account", "resource"],
    ),
)


def _parse_shopify_rate_limit(response: requests.Response) -> RateLimitSnapshot:
    return RateLimitSnapshot()


shopify_egress = EgressObservability(SHOPIFY_DOMAIN, _metrics, _parse_shopify_rate_limit)
register_egress_observability(shopify_egress)


def record_shopify_api_response(
    response: requests.Response,
    *,
    source: str,
    method: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Record one Shopify API response. The scope is always the instance's single merch store."""
    shopify_egress.record_response(response, source=source, scope="default", method=method, endpoint=endpoint)


def record_shopify_api_exception(
    *,
    source: str,
    method: str,
    endpoint: str | None = None,
    url: str | None = None,
) -> None:
    """Record a request that raised before a response (timeout, connection error)."""
    shopify_egress.record_exception(source=source, scope="default", method=method, endpoint=endpoint, url=url)
