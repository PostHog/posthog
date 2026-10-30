"""Typed client for the Cloudflare endpoints PostHog calls: purging cached files by URL."""

from collections.abc import Sequence

import requests

from posthog.egress.cloudflare.transport import cloudflare_request
from posthog.egress.limiter.policies import Priority

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
PURGE_ENDPOINT = "/zones/{zone_id}/purge_cache"

# Cloudflare accepts at most 100 URLs in one purge request on every plan below Enterprise.
MAX_URLS_PER_PURGE = 100

DEFAULT_PURGE_TIMEOUT: tuple[float, float] = (5.0, 10.0)


class CloudflarePurgeFailed(Exception):
    """Cloudflare was reached but did not accept the purge (HTTP error or ``success: false``)."""


def _check_accepted(response: requests.Response) -> None:
    try:
        body: object = response.json()
    except ValueError as exc:
        raise CloudflarePurgeFailed(f"Cloudflare purge returned HTTP {response.status_code} and no JSON body") from exc
    if not response.ok or not isinstance(body, dict) or body.get("success") is not True:
        errors = body.get("errors") if isinstance(body, dict) else None
        raise CloudflarePurgeFailed(f"Cloudflare purge returned HTTP {response.status_code}: {errors}")


def purge_urls(
    urls: Sequence[str],
    *,
    zone_id: str,
    api_token: str,
    source: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_PURGE_TIMEOUT,
) -> None:
    """Purge cached copies of ``urls`` from every Cloudflare data center in the zone.

    Success means Cloudflare accepted the purge, not that every edge already dropped its copy.
    Raises :class:`CloudflarePurgeFailed` when Cloudflare rejects a request, and
    :class:`~posthog.egress.cloudflare.transport.CloudflareEgressBudgetExhausted` when our own egress
    budget sheds it.
    """
    for start in range(0, len(urls), MAX_URLS_PER_PURGE):
        response = cloudflare_request(
            "POST",
            f"{CLOUDFLARE_API_BASE}{PURGE_ENDPOINT.format(zone_id=zone_id)}",
            api_token=api_token,
            source=source,
            endpoint=PURGE_ENDPOINT,
            priority=priority,
            timeout=timeout,
            json={"files": list(urls[start : start + MAX_URLS_PER_PURGE])},
        )
        _check_accepted(response)
