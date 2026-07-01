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
from posthog.rate_limiting.policies import Priority, RatePolicy, register_policy

GITHUB_DOMAIN = "github"

# No reserves are active yet. A reserve only helps once a higher-priority lane actually gates through
# the limiter — and today the only callers are warehouse (BATCH) and the job-logs worker (NORMAL),
# both deferrable background jobs. The CRITICAL lane (auth, token refresh, webhook CRUD) still calls
# GitHub without acquiring, so reserving headroom for it would just hard-cap the two real callers
# below GitHub's actual budget with no beneficiary (and silently drop the job-logs ceiling). The
# priority *mechanism* is wired end to end (callers already declare BATCH/NORMAL), so activating
# reserves when CRITICAL is gated is a one-line change here — e.g. {Priority.BATCH: 0.30} to shed
# warehouse polling first. Until then the shared budget alone (13.5k under GitHub's 15k) is the guard.
_RESERVE: dict[Priority, float] = {}

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
        reserve=_RESERVE,
    )


register_policy(GITHUB_DOMAIN, _github_policy)


def github_installation_key(installation_id: str | int) -> str:
    """Limiter key for one GitHub App installation — the unit GitHub's budget is scoped to."""
    return f"{GITHUB_DOMAIN}:installation:{installation_id}"


async def acquire_github_installation(
    installation_id: str | int, n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown"
) -> bool:
    """Reserve ``n`` requests against an installation's hourly GitHub budget. Returns False when the
    budget (or this ``priority``'s reserved floor) is exhausted — back off and retry rather than
    calling GitHub."""
    return await get_outbound_rate_limiter().acquire(
        github_installation_key(installation_id), n, priority=priority, source=source
    )


def consume_github_installation_sync(
    installation_id: str | int, n: int = 1, *, priority: Priority = Priority.NORMAL, source: str = "unknown"
) -> bool:
    """Sync variant of :func:`acquire_github_installation` for callers outside an event loop (e.g. the
    warehouse source iterator, which runs in a thread pool)."""
    return get_outbound_rate_limiter().consume_sync(
        github_installation_key(installation_id), n, priority=priority, source=source
    )
