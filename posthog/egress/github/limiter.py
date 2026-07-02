"""GitHub egress — the first consumer of the outbound rate limiter.

A GitHub App installation gets 15,000 REST requests/hour, shared across every PostHog
consumer of that installation (warehouse sources, Tasks, Code, Conversations, Visual
review). This module registers that budget as a policy keyed per installation and exposes
a thin gate other GitHub call sites can adopt one line at a time.

Importing this module registers the policy as a side effect — import it (directly or via
``acquire_github_installation``) before using a ``github:...`` limiter key.
"""

from django.conf import settings
from django.core.cache import cache

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy

GITHUB_DOMAIN = "github"

# Reserved-floor ladder: BATCH calls are denied once 70% of a window is consumed, NORMAL at 90%,
# CRITICAL can use the full budget. Active now that deferrable callers declare their lane
# (code-workstreams polling and the job-logs worker at BATCH) — shedding them first is what keeps
# headroom for user-facing traffic as an installation's budget fills.
_RESERVE: dict[Priority, float] = {Priority.BATCH: 0.30, Priority.NORMAL: 0.10}

# Default under GitHub's real 15k/hr ceiling so the reactive backoff (GitHubRateLimitError in
# posthog/egress/github/transport.py) absorbs drift between our local count and GitHub's actual
# counter — clock skew, multi-process races, and untracked PAT traffic on the same account.
# When the installation's real limit has been observed from response headers, the budget scales
# down to that tier instead (see _tier_budgets) — most installations sit on GitHub's 5k tier,
# where this default would never fire.
_DEFAULT_HOURLY_BUDGET = 13_500

# A per-minute smoothing cap layered on top of the hourly budget, so no single consumer can drain
# the shared hourly budget in seconds and we stay clear of GitHub's secondary (per-minute abuse)
# limits. Tier-scaled alongside the hourly budget when the installation's limit is known.
_DEFAULT_PER_MINUTE_BUDGET = 450

# The installation's core-resource X-RateLimit-Limit, as last observed from a real response
# (written by posthog/egress/github/observability.py on every recorded response). Long TTL: the
# tier changes only when the customer's GitHub plan does, and any traffic refreshes it.
OBSERVED_CORE_LIMIT_TTL_SECONDS = 7 * 24 * 3600


def observed_core_limit_cache_key(installation_id: str) -> str:
    return f"github_egress:observed_core_limit:{installation_id}"


def _hourly_budget() -> int:
    return int(getattr(settings, "GITHUB_EGRESS_HOURLY_BUDGET", _DEFAULT_HOURLY_BUDGET))


def _per_minute_budget() -> int:
    return int(getattr(settings, "GITHUB_EGRESS_PER_MINUTE_BUDGET", _DEFAULT_PER_MINUTE_BUDGET))


def _tier_budgets(observed_limit: int | None) -> tuple[int, int]:
    """``(hourly, per_minute)`` for an installation, scaled to its observed core limit.

    Unobserved installations get the settings defaults (13.5k/450 — the pre-tier behavior, correct
    for the top tier and self-correcting after the first recorded response). Observed tiers budget
    90% of the real limit for the hour, and scale the minute cap as hourly/18 — the hour can't
    drain faster than ~18 minutes, and the 750 ceiling keeps a comfortable margin under GitHub's
    documented ~900 requests/min secondary limit. The 150 floor keeps tiny tiers usable in bursts.
    """
    hourly_default = _hourly_budget()
    if observed_limit is None or observed_limit <= 0:
        return hourly_default, _per_minute_budget()
    hourly = min(hourly_default, observed_limit * 9 // 10)
    per_minute = max(150, min(750, hourly // 18))
    return hourly, per_minute


# Both rates are enforced together — the per-minute rate smooths bursts, the hourly rate caps total
# spend. Registered as a provider so budgets are read at acquire time (settings + the observed tier
# for the key's installation), not frozen at import.
def _github_policy(key: str) -> RatePolicy:
    installation_id = key.rpartition(":")[2]
    observed: int | None = None
    if installation_id:
        try:
            cached = cache.get(observed_core_limit_cache_key(installation_id))
            observed = cached if isinstance(cached, int) else None
        except Exception:
            # The limiter must never take a request down with it — fall back to the defaults.
            observed = None
    hourly, per_minute = _tier_budgets(observed)
    return RatePolicy(
        limits=((per_minute, 60.0), (hourly, 3600.0)),
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
