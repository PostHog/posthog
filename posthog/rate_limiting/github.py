"""GitHub egress — the first consumer of the outbound rate limiter.

A GitHub App installation gets 15,000 REST requests/hour, shared across every PostHog
consumer of that installation (warehouse sources, Tasks, Code, Conversations, Visual
review). This module registers that budget as a policy keyed per installation and exposes
a thin gate other GitHub call sites can adopt one line at a time.

Importing this module registers the policy as a side effect — import it (directly or via
``acquire_github_installation``) before using a ``github:...`` limiter key.
"""

from django.conf import settings

from posthog.rate_limiting.outbound import get_outbound_rate_limiter
from posthog.rate_limiting.policies import RatePolicy, register_policy

GITHUB_DOMAIN = "github"

# Default under GitHub's real 15k/hr ceiling so the reactive backoff (GitHubRateLimitError in
# posthog/models/integration.py) absorbs drift between our local count and GitHub's actual
# counter — clock skew, multi-process races, and untracked PAT traffic on the same account.
_DEFAULT_HOURLY_BUDGET = 13_500

# A per-minute smoothing cap layered on top of the hourly budget. High enough that a normal
# failed run (a handful of jobs) never touches it, low enough that no single consumer can drain
# the shared hourly budget in seconds and that we stay clear of GitHub's secondary (per-minute
# abuse) limits. Under sustained pressure a flood drains at ~this rate, leaving budget for
# co-tenant consumers each minute (~hourly/30 — the hour can't empty faster than ~half an hour).
_DEFAULT_PER_MINUTE_BUDGET = 450


def _hourly_budget() -> int:
    return int(getattr(settings, "GITHUB_EGRESS_HOURLY_BUDGET", _DEFAULT_HOURLY_BUDGET))


def _per_minute_budget() -> int:
    return int(getattr(settings, "GITHUB_EGRESS_PER_MINUTE_BUDGET", _DEFAULT_PER_MINUTE_BUDGET))


# Both rates are enforced together — the per-minute rate smooths bursts, the hourly rate caps total
# spend. Registered as a provider so the budgets are read from settings at acquire time, not frozen
# at import (lets deploy-time config and test overrides take effect).
def _github_policy() -> RatePolicy:
    return RatePolicy(
        limits=((_per_minute_budget(), 60.0), (_hourly_budget(), 3600.0)),
        in_memory_divider=4,
    )


register_policy(GITHUB_DOMAIN, _github_policy)


def github_installation_key(installation_id: str | int) -> str:
    """Limiter key for one GitHub App installation — the unit GitHub's budget is scoped to."""
    return f"{GITHUB_DOMAIN}:installation:{installation_id}"


async def acquire_github_installation(installation_id: str | int, n: int = 1) -> bool:
    """Reserve ``n`` requests against an installation's hourly GitHub budget. Returns False when
    the budget is exhausted — back off and retry rather than calling GitHub."""
    return await get_outbound_rate_limiter().acquire(github_installation_key(installation_id), n)
