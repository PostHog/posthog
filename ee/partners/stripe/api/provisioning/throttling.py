"""Rate limiting for the Stripe provisioning namespace.

Fixed-window counters with fixed per-endpoint limits from ``RATE_LIMIT_DEFAULTS``
- this namespace serves a single caller (Stripe), so the window is keyed on a
constant identity rather than any OAuthApplication field. A limit <= 0 disables
it. The caller can burst up to 2x the limit across a window boundary; switch to
a sliding window if that ever matters.
"""

from __future__ import annotations

import time
from typing import ClassVar

from django.core.cache import cache

import structlog
from rest_framework.request import Request
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from ee.partners.stripe.api.provisioning.analytics import capture_provisioning_event
from ee.partners.stripe.api.provisioning.constants import (
    RATE_LIMIT_CACHE_PREFIX,
    RATE_LIMIT_DEFAULTS,
    RATE_LIMIT_EVENT_NAMES,
    RATE_LIMIT_WINDOW_SECONDS,
)
from ee.partners.stripe.api.provisioning.exceptions import SpecError

logger = structlog.get_logger(__name__)

# Single-caller namespace: the rate-limit window is keyed on this constant, not
# on any per-app identity or config.
_STRIPE_RATE_LIMIT_KEY = "stripe"


class StripeFixedWindowThrottle(BaseThrottle):
    """Fixed-window counter keyed on the endpoint + window-of-epoch."""

    endpoint: ClassVar[str]

    def __init__(self) -> None:
        self.limit = RATE_LIMIT_DEFAULTS[self.endpoint]
        self.count = 0

    def allow_request(self, request: Request, view: APIView) -> bool:
        if self.limit <= 0:
            return True

        window_index = int(time.time()) // RATE_LIMIT_WINDOW_SECONDS
        cache_key = f"{RATE_LIMIT_CACHE_PREFIX}{self.endpoint}:{_STRIPE_RATE_LIMIT_KEY}:{window_index}"

        try:
            cache.add(cache_key, 0, timeout=RATE_LIMIT_WINDOW_SECONDS)
            self.count = cache.incr(cache_key)
        except (ValueError, ConnectionError, TimeoutError) as e:
            logger.warning("stripe_provisioning_rate_limit_cache_error", endpoint=self.endpoint, error=str(e))
            # cache.add preserves any counter a concurrent request already initialized,
            # so a transient cache error doesn't reset the window when at the limit.
            cache.add(cache_key, 1, timeout=RATE_LIMIT_WINDOW_SECONDS)
            self.count = 1

        return self.count <= self.limit

    def wait(self) -> float:
        return float(RATE_LIMIT_WINDOW_SECONDS - (int(time.time()) % RATE_LIMIT_WINDOW_SECONDS))


class AccountRequestsThrottle(StripeFixedWindowThrottle):
    endpoint = "account_requests"


class TokenExchangesThrottle(StripeFixedWindowThrottle):
    endpoint = "token_exchanges"


class ResourceCreatesThrottle(StripeFixedWindowThrottle):
    endpoint = "resource_creates"


def enforce_stripe_rate_limit(
    throttle_cls: type[StripeFixedWindowThrottle],
    request: Request,
    view: APIView,
    *,
    message: str | None = None,
    envelope: str | None = None,
) -> None:
    """Raise a spec ``rate_limited`` error when the caller is over budget.

    ``message``/``envelope`` default to the typed-envelope wording used by
    account_requests and the token endpoint; the resource endpoints pass their
    own status-envelope variants.
    """
    throttle = throttle_cls()
    if throttle.allow_request(request, view):
        return

    endpoint = throttle_cls.endpoint
    capture_provisioning_event(
        RATE_LIMIT_EVENT_NAMES[endpoint],
        "rate_limited",
        limit=throttle.limit,
        count=throttle.count,
    )
    raise SpecError(
        "rate_limited",
        message or f"Rate limit exceeded ({endpoint}). Try again later.",
        status=429,
        envelope=envelope or "typed",  # type: ignore[arg-type]
        retry_after=int(throttle.wait()),
    )
