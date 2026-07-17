"""Per-team monthly hard cap for Replay Vision summaries.

Backstop against runaway LLM cost. One Redis counter per team per calendar
month; auto-resets on the 1st. A team can use up to 2x the cap across a month
boundary — fine for a backstop, not for billing.

Cap value: `DEFAULT_MAX_SUMMARIES_PER_PERIOD`, optionally lowered (never
raised) by `SignalSourceConfig.config["max_summaries_per_period"]`.

Importable from both DRF and Temporal activities — keep this module
dependency-light.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from redis.exceptions import ResponseError

from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# Bump in a deploy. Per-team lowering is allowed via SignalSourceConfig.
DEFAULT_MAX_SUMMARIES_PER_PERIOD = 2500

# JSON key on SignalSourceConfig.config.
CONFIG_KEY = "max_summaries_per_period"

_REDIS_KEY_PREFIX = "posthog/replay-summary-cap"

# 32 days — slightly longer than any month so the bucket outlives its read
# window. Redis GCs the key on its own.
_KEY_TTL_SECONDS = 32 * 24 * 60 * 60


@dataclass(frozen=True)
class CapDecision:
    allowed: bool
    used: int
    cap: int


def coerce_max_summaries_per_period(value: object) -> int:
    """Validate a raw cap override value. Anything malformed falls back to
    the default — admin JSON should never take down the summarize path.

    Bools are rejected explicitly because they inherit from int and would
    otherwise coerce to 0/1.
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
    """Return the effective per-team monthly cap.

    The override on `SignalSourceConfig.config` can only LOWER the default —
    never raise it. Project members can edit that config row via API, so
    treating it as a raise vector would be a privilege escalation around the
    backstop.
    """
    # Lazy import: this module is imported by Temporal activities that load
    # before Django apps.
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
    override = coerce_max_summaries_per_period(row.config.get(CONFIG_KEY))
    return min(override, DEFAULT_MAX_SUMMARIES_PER_PERIOD)


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
    children, otherwise a runaway sweep could starve interactive DRF users.
    """
    return max(0, get_cap_for_team(team_id) - current_usage(team_id, now=now))


def _incrby(client, key: str, n: int) -> int:
    """INCRBY with WRONGTYPE recovery. Returns the new counter value.

    Recovery: if somebody SET the key to a non-integer string, reset it and
    retry. Losing the (uncountable) prior usage is fine for a backstop.
    """
    try:
        return int(client.incrby(key, n))
    except ResponseError:
        logger.warning("replay_summary_cap.corrupt_counter_on_write", key=key)
        client.delete(key)
        return int(client.incrby(key, n))


def consume_summary_quota(team_id: int, n: int = 1, *, now: datetime | None = None) -> int:
    """Increment the counter by `n`. Sets TTL on first write. Returns the new
    value. No bound check — caller is responsible for that."""
    if n <= 0:
        return current_usage(team_id, now=now)
    key = _redis_key(team_id, now=now)
    client = get_client()
    new_value = _incrby(client, key, n)
    # First write of the month: set the TTL so abandoned keys GC themselves.
    if new_value == n:
        client.expire(key, _KEY_TTL_SECONDS)
    return new_value


def atomic_check_and_consume(team_id: int, *, requested: int = 1, now: datetime | None = None) -> CapDecision:
    """Reserve `requested` slots in one Redis round-trip. Returns the decision.

    If the new counter exceeds the cap, the reservation is rolled back and
    `allowed=False` is returned. This closes the TOCTOU window between a
    naive read-then-write check, so concurrent requests can't all pass and
    then collectively overshoot.

    Callers MUST `refund(team_id, n)` if they later decide not to do the
    work (e.g. `start_workflow` failed). The split between reservation and
    commit lives in the caller.
    """
    if requested < 0:
        raise ValueError(f"requested must be >= 0, got {requested}")
    if requested == 0:
        return CapDecision(allowed=True, used=current_usage(team_id, now=now), cap=get_cap_for_team(team_id))

    cap = get_cap_for_team(team_id)
    key = _redis_key(team_id, now=now)
    client = get_client()
    new_value = _incrby(client, key, requested)
    if new_value == requested:
        client.expire(key, _KEY_TTL_SECONDS)
    if new_value > cap:
        # Roll back: keep the counter at-or-below cap so a steady-state team
        # doesn't permanently look over.
        client.decrby(key, requested)
        return CapDecision(allowed=False, used=new_value - requested, cap=cap)
    return CapDecision(allowed=True, used=new_value, cap=cap)


def refund(team_id: int, n: int = 1, *, now: datetime | None = None) -> None:
    """Roll back a previous `atomic_check_and_consume(...n)` reservation.

    Best-effort: failures are logged, not raised. We don't want a Redis blip
    to fail a request that already succeeded (or failed) on its main path.
    """
    if n <= 0:
        return
    try:
        get_client().decrby(_redis_key(team_id, now=now), n)
    except Exception as e:
        logger.warning("replay_summary_cap.refund_failed", team_id=team_id, n=n, error=str(e))


def check_only(team_id: int, *, requested: int = 1, now: datetime | None = None) -> CapDecision:
    """Read-only: decide whether `requested` slots fit, without reserving.

    Use this when you can't tolerate the boundary effect of a reserve-then-
    refund cycle (e.g. health checks). For request-handling paths that may
    commit to LLM work, prefer `atomic_check_and_consume`.
    """
    if requested < 0:
        raise ValueError(f"requested must be >= 0, got {requested}")
    now = now or datetime.now(UTC)
    cap = get_cap_for_team(team_id)
    used = current_usage(team_id, now=now)
    return CapDecision(allowed=used + requested <= cap, used=used, cap=cap)
