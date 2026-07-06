"""GitHub egress — the first consumer of the outbound rate limiter.

A GitHub App installation gets 5,000–15,000 REST requests/hour depending on the account's
plan tier, shared across every PostHog consumer of that installation (warehouse sources,
Tasks, Code, Conversations, Visual review). This module budgets each installation to its
observed tier and registers that budget as a policy keyed per installation. The budget is
one shared envelope across GitHub's resources (REST core, GraphQL, …) — deliberately
conservative rather than modeling each resource's separate meter.

Importing this module registers the policy as a side effect — import it (directly or via
``acquire_github_installation``) before using a ``github:...`` limiter key.
"""

import time
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache

if TYPE_CHECKING:
    import requests

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
# the shared hourly budget in seconds and we stay clear of GitHub's documented ~900 requests/min
# secondary limit (750 keeps a comfortable margin under it). Both settings are operator ceilings:
# tier scaling can only lower them, never exceed them.
_DEFAULT_PER_MINUTE_BUDGET = 750

# The installation's core-resource X-RateLimit-Limit, as last observed from a successful
# installation-token response (written by GitHubIntegrationBase.api_request via
# remember_observed_core_limit). Long TTL: the tier changes only when the customer's GitHub plan
# does, and any traffic refreshes it.
OBSERVED_CORE_LIMIT_TTL_SECONDS = 7 * 24 * 3600

# Below GitHub's smallest real app tier (5,000). Rejects junk observations — an unauthenticated
# 60-limit, a bool, a tiny garbage value — that would otherwise clamp or crash the budget math.
_SANE_MIN_OBSERVED_LIMIT = 1_000

# Process-local memos so the hot paths stay off Redis: the gate would otherwise pay one extra
# (event-loop-blocking, on async callers) GET per acquire, and the recorder one SET per response,
# for a value that changes only when a customer's GitHub plan does.
_OBSERVED_MEMO_TTL_SECONDS = 60.0
_observed_memo: dict[str, tuple[int | None, float]] = {}
# Rewrite the shared cache at least hourly even when the value is unchanged: a long-lived process
# skipping every write would otherwise never repair an evicted/flushed cache entry, silently
# reverting every other worker to the default budget until a deploy.
_REWRITE_INTERVAL_SECONDS = 3600.0
_last_written: dict[str, tuple[int, float]] = {}


def observed_core_limit_cache_key(installation_id: str) -> str:
    return f"github_egress:observed_core_limit:{installation_id}"


def installation_id_from_key(key: str) -> str:
    """Inverse of :func:`github_installation_key` — the key shape lives in this pair only."""
    return key.rpartition(":")[2]


def get_observed_core_limit(installation_id: str) -> int | None:
    """The installation's observed core limit, or ``None`` when unobserved or implausible.

    Best-effort by construction: cache failures and junk values fall back to ``None`` (the settings
    defaults) — the limiter must never take a request down with it.
    """
    now = time.monotonic()
    memoized = _observed_memo.get(installation_id)
    if memoized is not None and now - memoized[1] < _OBSERVED_MEMO_TTL_SECONDS:
        return memoized[0]
    try:
        cached = cache.get(observed_core_limit_cache_key(installation_id))
    except Exception:
        cached = None
    observed = (
        cached
        if isinstance(cached, int) and not isinstance(cached, bool) and cached >= _SANE_MIN_OBSERVED_LIMIT
        else None
    )
    _observed_memo[installation_id] = (observed, now)
    return observed


def remember_observed_core_limit(installation_id: str | None, response: "requests.Response") -> None:
    """Persist the tier from a *successful installation-token* response's headers.

    Called from ``GitHubIntegrationBase.api_request`` — the one place that knows the response was
    metered against the installation. Responses from other principals sharing the installation id
    (App-JWT refreshes on the App's budget, user-to-server calls on the user's 5k budget) and
    error responses (a 401 reports the unauthenticated 60-limit) must never feed the budget, so
    only 2xx ``core`` observations above the sanity floor count.
    """
    if not installation_id or not (200 <= response.status_code < 300):
        return
    headers = response.headers
    # Require the explicit header — a response missing it is no proof the limits are core's.
    if headers.get("x-ratelimit-resource") != "core":
        return
    try:
        limit = int(headers.get("x-ratelimit-limit", ""))
    except (TypeError, ValueError):
        return
    if limit < _SANE_MIN_OBSERVED_LIMIT:
        return
    now = time.monotonic()
    _observed_memo[installation_id] = (limit, now)
    written = _last_written.get(installation_id)
    if written is not None and written[0] == limit and now - written[1] < _REWRITE_INTERVAL_SECONDS:
        return
    try:
        cache.set(observed_core_limit_cache_key(installation_id), limit, OBSERVED_CORE_LIMIT_TTL_SECONDS)
        _last_written[installation_id] = (limit, now)
    except Exception:
        pass


def _hourly_budget() -> int:
    return int(getattr(settings, "GITHUB_EGRESS_HOURLY_BUDGET", _DEFAULT_HOURLY_BUDGET))


def _per_minute_budget() -> int:
    return int(getattr(settings, "GITHUB_EGRESS_PER_MINUTE_BUDGET", _DEFAULT_PER_MINUTE_BUDGET))


def _tier_budgets(observed_limit: int | None) -> tuple[int, int]:
    """``(hourly, per_minute)`` for an installation, scaled to its observed core limit.

    The settings are operator ceilings honored for every installation; the observed tier can only
    lower the hourly budget below them (budgeting *over* the provider's real limit would defeat the
    limiter). 90% of the observed limit leaves room for drift; the minute cap scales as hourly/18
    so the hour can't drain faster than ~18 minutes, with a 150 floor so small tiers stay usable
    in bursts.
    """
    hourly = _hourly_budget()
    if observed_limit is not None and observed_limit > 0:
        hourly = min(hourly, int(observed_limit * 0.9))
    per_minute = max(150, min(_per_minute_budget(), hourly // 18))
    return hourly, per_minute


# Both rates are enforced together — the per-minute rate smooths bursts, the hourly rate caps total
# spend. Registered as a provider so budgets are read at acquire time (settings + the observed tier
# for the key's installation), not frozen at import.
def _github_policy(key: str) -> RatePolicy:
    hourly, per_minute = _tier_budgets(get_observed_core_limit(installation_id_from_key(key)))
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
