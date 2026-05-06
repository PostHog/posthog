"""Per-team monthly hard cap for Replay Vision summaries.

A backstop against runaway LLM cost. Cap is read from
`SignalSourceConfig(SESSION_REPLAY, SESSION_ANALYSIS_CLUSTER).config["max_summaries_per_period"]`
when present, otherwise falls back to a constant default. Mirrors the
`coerce_sample_rate` pattern from the sampling work in PR #56921.

Counter is a Redis key per team per calendar month — auto-resets on the 1st,
no sliding-window bookkeeping. Boundary effect (a team can use up to 2x the
cap across a month boundary) is acceptable for a backstop, not for billing.

Importable from both DRF (`session_recording_api`) and Temporal activities —
keep this module dependency-light (no DRF / Temporal imports).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from redis.exceptions import ResponseError

from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# Tweak with billing team. Intentionally a code constant — easy to bump in a deploy,
# easy to override per-team via SignalSourceConfig for ops cases.
DEFAULT_MAX_SUMMARIES_PER_PERIOD = 4 * 1000

# JSON key on SignalSourceConfig.config. Mirrors the `sample_rate` key from PR #56921.
CONFIG_KEY = "max_summaries_per_period"

# Redis key prefix. One key per team per month, auto-expires.
_REDIS_KEY_PREFIX = "posthog/replay-summary-cap"

# 32 days — slightly longer than any month so the bucket survives until it would naturally
# stop being read. Redis GCs it on its own; we never have to clean up.
_KEY_TTL_SECONDS = 32 * 24 * 60 * 60


@dataclass(frozen=True)
class CapDecision:
    allowed: bool
    used: int
    cap: int


def coerce_max_summaries_per_period(value: object) -> int:
    """Validate a raw cap value (e.g. `config.config.get("max_summaries_per_period")`).

    Mirrors the `coerce_sample_rate` pattern from PR #56921 — takes the raw
    value rather than the whole dict, so callers that already loaded the config
    don't pay for a second read. Anything malformed (None, wrong type,
    non-positive) silently falls back to the default — admin JSON should never
    take down the summarize path. Bools are rejected explicitly because they
    inherit from int and would otherwise coerce to 0/1.
    """
    if value is None or isinstance(value, bool):
        return DEFAULT_MAX_SUMMARIES_PER_PERIOD
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        return DEFAULT_MAX_SUMMARIES_PER_PERIOD
    try:
        cap = int(value)
    except (ValueError, OverflowError):
        return DEFAULT_MAX_SUMMARIES_PER_PERIOD
    if cap <= 0:
        return DEFAULT_MAX_SUMMARIES_PER_PERIOD
    return cap


def get_cap_for_team(team_id: int) -> int:
    """Look up the team's `SignalSourceConfig` row for the autonomous summarization
    cluster and read the cap override from its `config` dict. Falls back to the
    default for teams without a row (which is most teams — the row is only
    created when a team opts into the autonomous sweep).

    Used by callers that don't already have the config loaded (DRF entrypoint).
    Sweep activities should prefer `coerce_max_summaries_per_period(config.config.get(CONFIG_KEY))`
    directly to avoid a second DB hit once PR #56921's config preload lands.
    """
    # Imported lazily to avoid pulling Django app loading into module import time
    # (this module is imported by Temporal activities that load before Django apps).
    from products.signals.backend.models import SignalSourceConfig

    row = (
        SignalSourceConfig.objects.filter(
            team_id=team_id,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        )
        .only("config")
        .first()
    )
    if row is None or not isinstance(row.config, dict):
        return DEFAULT_MAX_SUMMARIES_PER_PERIOD
    return coerce_max_summaries_per_period(row.config.get(CONFIG_KEY))


def _redis_key(team_id: int, *, now: datetime | None = None) -> str:
    bucket = (now or datetime.now(UTC)).strftime("%Y-%m")
    return f"{_REDIS_KEY_PREFIX}:{team_id}:{bucket}"


def current_usage(team_id: int, *, now: datetime | None = None) -> int:
    raw = get_client().get(_redis_key(team_id, now=now))
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        # Corrupt key — log and treat as zero so summaries don't break.
        logger.warning("replay_summary_cap.corrupt_counter", team_id=team_id, raw=raw)
        return 0


def headroom(team_id: int, *, now: datetime | None = None) -> int:
    """Remaining quota for the team this month. Never negative.

    Used by the autonomous sweep to slice its dispatch list before starting
    children — the cap is otherwise only enforced on the DRF entrypoint, which
    would let a runaway sweep starve interactive users.
    """
    return max(0, get_cap_for_team(team_id) - current_usage(team_id, now=now))


def consume_summary_quota(team_id: int, n: int = 1, *, now: datetime | None = None) -> int:
    """Increment the team's monthly counter by `n`. Sets a TTL on first write
    so abandoned keys GC themselves. Returns the new counter value.

    No bound check — callers that want to enforce the cap should use
    `check_and_consume` instead.
    """
    if n <= 0:
        return current_usage(team_id, now=now)
    key = _redis_key(team_id, now=now)
    client = get_client()
    try:
        new_value = client.incrby(key, n)
    except ResponseError:
        # WRONGTYPE: somebody SET the key to a non-integer string. Reset and
        # retry — losing the (uncountable) prior usage is fine for a backstop,
        # and crashing the summarize path would be worse.
        logger.warning("replay_summary_cap.corrupt_counter_on_write", team_id=team_id)
        client.delete(key)
        new_value = client.incrby(key, n)
    # Set TTL only when this is the first write of the month. INCRBY returning
    # exactly `n` is a tight enough proxy (collision requires the key to have
    # been GCed and re-incremented in the same race — fine for a backstop).
    if int(new_value) == n:
        client.expire(key, _KEY_TTL_SECONDS)
    return int(new_value)


def check_only(team_id: int, *, requested: int = 1, now: datetime | None = None) -> CapDecision:
    """Read the cap and current usage, return a decision, but do NOT increment.

    Use at request entry (DRF) when you want to fail fast without burning quota
    on no-op paths (cache hits, dedup branches that won't issue LLM calls). Pair
    with a later `consume_summary_quota(team_id, n)` once the caller has
    committed to actual LLM work.

    `requested` must be non-negative — a negative value here would mean "give
    me a refund preview", which is almost never what a caller wants; surface
    it loudly.
    """
    if requested < 0:
        raise ValueError(f"requested must be >= 0, got {requested}")
    now = now or datetime.now(UTC)
    cap = get_cap_for_team(team_id)
    used = current_usage(team_id, now=now)
    return CapDecision(allowed=used + requested <= cap, used=used, cap=cap)


def check_and_consume(team_id: int, *, requested: int = 1, now: datetime | None = None) -> CapDecision:
    """GET-then-conditional-INCRBY. The race window between read and write
    allows ~maxConcurrentCalls overshoot (sub-cap concurrent requests can all
    pass the read, then all increment past the cap). Acceptable for a backstop;
    do not use this for billing.

    Prefer `check_only` + a later `consume_summary_quota` when the caller has
    no-op short-circuits between entry and LLM dispatch — `check_and_consume`
    will burn quota on those.

    `requested` must be non-negative. A negative value would silently "refund"
    quota under the previous implementation, which is almost never what a
    caller wants — surface it loudly instead.
    """
    now = now or datetime.now(UTC)
    decision = check_only(team_id, requested=requested, now=now)
    if not decision.allowed:
        return decision
    new_used = consume_summary_quota(team_id, requested, now=now)
    return CapDecision(allowed=True, used=new_used, cap=decision.cap)
