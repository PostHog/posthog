"""General-purpose outbound API egress rate limiting.

Shared, Redis-backed budgets for calls leaving PostHog to third-party APIs, so every worker
process draws from one limit. Consumers go through ``OutboundRateLimiter`` with a key like
``"github:installation:123"``; per-target budgets are declared as ``RatePolicy`` objects and
registered by each consumer's adapter (see ``posthog.rate_limiting.github``).

Distinct from ``posthog.rate_limit`` (inbound DRF request throttling) — this limits what we
send out, not what clients send us.
"""

from posthog.rate_limiting.outbound import OutboundRateLimiter, get_outbound_rate_limiter
from posthog.rate_limiting.policies import RatePolicy, register_policy

__all__ = [
    "OutboundRateLimiter",
    "get_outbound_rate_limiter",
    "RatePolicy",
    "register_policy",
]
