"""Rate limiting for the Stripe provisioning namespace.

Token buckets (:mod:`posthog.token_bucket`) with budgets hardcoded inline: this
namespace serves a single caller (Stripe), so there are no tiers, no
per-partner overrides, and the bucket is keyed on a constant identity rather
than any OAuthApplication field. Burst equals the hourly rate, so the full
budget is available at once (matching the fixed window this replaced) while
the continuous refill removes the 2x window-boundary burst and gives a real
per-caller Retry-After.
"""

from __future__ import annotations

from typing import ClassVar

import structlog
from rest_framework.request import Request
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume

from ee.partners.stripe.api.provisioning.analytics import capture_provisioning_event
from ee.partners.stripe.api.provisioning.constants import RATE_LIMIT_EVENT_NAMES
from ee.partners.stripe.api.provisioning.exceptions import SpecError

logger = structlog.get_logger(__name__)

# Single-caller namespace: buckets are keyed on this constant, not on any
# per-app identity or config.
_STRIPE_RATE_LIMIT_KEY = "stripe"
BUCKET_KEY_PREFIX = "stripe_provisioning_bucket:"

# None disables the endpoint's limit.
BUDGETS: dict[str, Budget | None] = {
    "account_requests": Budget(burst=10, per_hour=10),
    "token_exchanges": Budget(burst=20, per_hour=20),
    "resource_creates": Budget(burst=20, per_hour=20),
}


class StripeBucketThrottle(BaseThrottle):
    """Token bucket keyed on the endpoint + the constant Stripe identity."""

    endpoint: ClassVar[str]

    def __init__(self) -> None:
        self.limit = 0
        self.decision: BucketDecision | None = None

    def allow_request(self, request: Request, view: APIView) -> bool:
        budget = BUDGETS[self.endpoint]
        if budget is None:
            return True
        self.limit = budget.per_hour

        decision = consume(f"{BUCKET_KEY_PREFIX}{self.endpoint}:{_STRIPE_RATE_LIMIT_KEY}", budget)
        if isinstance(decision, BucketUnavailable):
            # Fail open: an unreachable Redis must not take the namespace down.
            logger.warning("stripe_provisioning_rate_limit_unavailable", endpoint=self.endpoint)
            return True

        self.decision = decision
        return decision.allowed

    def wait(self) -> float:
        return float(self.decision.retry_after) if self.decision is not None else 0.0


class AccountRequestsThrottle(StripeBucketThrottle):
    endpoint = "account_requests"


class TokenExchangesThrottle(StripeBucketThrottle):
    endpoint = "token_exchanges"


class ResourceCreatesThrottle(StripeBucketThrottle):
    endpoint = "resource_creates"


def enforce_stripe_rate_limit(
    throttle_cls: type[StripeBucketThrottle],
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
        retry_after=int(throttle.wait()),
    )
    raise SpecError(
        "rate_limited",
        message or f"Rate limit exceeded ({endpoint}). Try again later.",
        status=429,
        envelope=envelope or "typed",  # type: ignore[arg-type]
        retry_after=int(throttle.wait()),
    )
