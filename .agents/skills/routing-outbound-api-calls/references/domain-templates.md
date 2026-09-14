# Egress domain templates

Replace `acme` / `Acme` / `ACME` with the domain name.
The directory name must equal the limiter domain string, because `test_domains.py` resolves each domain's policy by its directory name.

## Gated sync domain

`posthog/egress/acme/limiter.py`:

```python
"""Acme egress budget.

State the identity and why Acme meters it, where the numbers come from (a documented Acme limit, or an
operator ceiling on spend), and which lanes the callers run on.

Importing this module registers the policy as a side effect.
"""

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, per_minute_and_hourly_policy, register_policy

ACME_DOMAIN = "acme"

register_policy(
    ACME_DOMAIN,
    per_minute_and_hourly_policy(
        per_minute_setting="ACME_EGRESS_PER_MINUTE_BUDGET",
        per_minute_default=60,
        hourly_setting="ACME_EGRESS_HOURLY_BUDGET",
        hourly_default=1_000,
    ),
)


def consume_acme_sync(scope: str, *, priority: Priority, source: str) -> bool:
    return get_outbound_rate_limiter().consume_sync(f"{ACME_DOMAIN}:account:{scope}", priority=priority, source=source)
```

A policy that does not fit per-minute plus hourly limits (a per-second limit, a tier read from response headers) registers its own provider that returns a `RatePolicy`.
It still gets the default reserve unless it passes `reserve={}`.

`posthog/egress/acme/observability.py`, for an API with no rate-limit headers:

```python
"""Acme outbound request telemetry.

Acme returns no rate-limit headers, so this domain declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

acme_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "acme_api_requests",
            "Outbound Acme API requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
    )
)
```

For an API that documents rate-limit headers, add only the gauges it reports and a parser:

```python
from collections.abc import Mapping

from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    float_header,
)

_metrics = EgressMetrics(
    request_counter=Counter(...),
    remaining_gauge=Gauge("acme_api_rate_limit_remaining", "...", labelnames=["scope", "resource"]),
    limit_gauge=Gauge("acme_api_rate_limit_limit", "...", labelnames=["scope", "resource"]),
)


def _parse_acme_rate_limit(headers: Mapping[str, str] | None, _url: str | None) -> RateLimitSnapshot:
    return RateLimitSnapshot(
        resource="account",
        remaining=float_header(headers, "X-Acme-RateLimit-Remaining"),
        limit=float_header(headers, "X-Acme-RateLimit-Limit"),
    )


acme_egress = EgressObservability(_metrics, _parse_acme_rate_limit)
```

The labels are positional: the counter is `(<scope>, method, endpoint, status_code, source)` and each gauge is `(<scope>, resource)`.
A URL with ids in its path needs `endpoint_normalizer=`, or the caller passes a curated `endpoint`.

`posthog/egress/acme/transport.py`:

```python
"""Gated, recorded transport for calls to the Acme API."""

from typing import Any

import requests

from posthog.egress.acme.limiter import consume_acme_sync
from posthog.egress.acme.observability import acme_egress
from posthog.egress.limiter.policies import Priority
from posthog.egress.transport.transport import EgressBudgetExhausted, EgressClient


class AcmeEgressBudgetExhausted(EgressBudgetExhausted):
    """A sheddable Acme call was denied by the egress limiter before it was sent."""


class AcmeClient(EgressClient):
    observability = acme_egress

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _consume(self, scope: str, priority: Priority, source: str, url: str) -> bool:
        return consume_acme_sync(scope, priority=priority, source=source)

    def _budget_exhausted_error(self, scope: str) -> AcmeEgressBudgetExhausted:
        return AcmeEgressBudgetExhausted("Acme egress budget exhausted")


_acme_client = AcmeClient()


def acme_request(
    method: str,
    url: str,
    *,
    api_key: str,
    account_id: str,
    source: str,
    endpoint: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] | None = None,
    **kwargs: Any,
) -> requests.Response:
    return _acme_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_key}"},
        scope=account_id,
        priority=priority,
        endpoint=endpoint,
        timeout=timeout,
        **kwargs,
    )
```

A scope of `None` or `""` skips the gate. A single-account domain therefore passes a constant scope such as `"default"`, or every call goes through ungated.

## Record-only domain

No `limiter.py`. The client subclasses `RecordedEgressClient` and has no gate hooks:

```python
from posthog.egress.acme.observability import acme_egress
from posthog.egress.observability.observability import scope_fingerprint
from posthog.egress.transport.transport import RecordedEgressClient


class AcmeClient(RecordedEgressClient):
    observability = acme_egress


def acme_request(method: str, url: str, *, api_token: str, source: str, endpoint: str, **kwargs: Any) -> requests.Response:
    return _acme_client.request(
        method,
        url,
        source=source,
        headers={"Authorization": f"Bearer {api_token}"},
        scope=scope_fingerprint(api_token),
        endpoint=endpoint,
        **kwargs,
    )
```

## Async domain

Subclass `AsyncEgressClient`. `_consume` is a coroutine that awaits the domain's `acquire_*` gate, and the caller passes its own `aiohttp.ClientSession`.
See `posthog/egress/harmonic/transport.py`.

## Vendor SDK

When callers go through a vendor SDK, hook the SDK so that every HTTP attempt is recorded, and ship a `<domain>_request` helper only for direct HTTP calls.
See `posthog/egress/slack/client.py`.

## Domain README

`posthog/egress/acme/README.md`:

```markdown
# Acme egress

## Identity

The budget owner in Acme's id space, the limiter key shape, and why Acme meters it that way.

## Budget

The settings, their defaults, and where the numbers come from: a documented Acme limit with a link, or an operator ceiling on spend.
A record-only domain says "None" and why no rate budget fits.

## Lanes and callers

The reserve (default or flat, with the reason), and each merged caller with its file path and lane.

## Rate-limit headers

The documented headers that feed gauges, or "none". The counter name and its labels.

## Auth

Which credential, where it comes from, and how it is sent.
```

Add sections such as "Typed client" or "Caveats" after these when the domain needs them.
