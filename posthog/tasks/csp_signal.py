import json
import math
import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import Counter

from posthog.models.scoping import with_team_scope
from posthog.models.team.team import Team
from posthog.redis import get_client

from products.signals.backend.models import SignalSourceConfig

logger = structlog.get_logger(__name__)

CSP_SIGNAL_SOURCE_PRODUCT = "csp_reporting"
CSP_SIGNAL_SOURCE_TYPE = "violation"
CSP_SIGNAL_WEIGHT = 0.5
CSP_SIGNAL_DEDUP_TTL_SECONDS = 60 * 60 * 24
CSP_SIGNAL_DEDUP_KEY_PREFIX = "csp_signal_dedup:v1"
CSP_SIGNAL_ENABLED_CACHE_TTL_SECONDS = 60
CSP_SIGNAL_ENABLED_CACHE_KEY_PREFIX = "csp_signal_enabled"
CSP_SIGNAL_TASK_SOFT_TIME_LIMIT_SECONDS = 15
CSP_SIGNAL_TASK_TIME_LIMIT_SECONDS = 30
CSP_SIGNAL_DAILY_COUNT_KEY_PREFIX = "csp_signal_daily_count"
CSP_SIGNAL_DAILY_COUNT_TTL_SECONDS = 60 * 60 * 25  # 25h, safe margin past UTC midnight
# Cap on the length of any single attacker-controlled CSP field before it lands in the signal
# description / extra / fingerprint input. Bounds Celery payload size and request-thread CPU
# regardless of how large the browser-supplied value is.
CSP_SIGNAL_FIELD_MAX_LENGTH = 2048

CSP_SIGNAL_DROPPED_COUNTER = Counter(
    "csp_signal_dropped_total",
    "CSP signal emissions skipped before reaching the signals pipeline, tagged by reason.",
    labelnames=["reason"],
)

CSP_SIGNAL_OUTCOME_COUNTER = Counter(
    "csp_signal_outcome_total",
    "Per-team count of CSP signals embedded into the signals pipeline vs dropped.",
    labelnames=["team_id", "outcome"],
)


def _record_outcome(team_id: int, n: int, outcome: str) -> None:
    if n <= 0:
        return
    CSP_SIGNAL_OUTCOME_COUNTER.labels(team_id=str(team_id), outcome=outcome).inc(n)


def _record_dropped(team_id: int, n: int, reason: str) -> None:
    if n <= 0:
        return
    CSP_SIGNAL_DROPPED_COUNTER.labels(reason=reason).inc(n)
    _record_outcome(team_id, n, "dropped")


def _stringify(value: object) -> str:
    if value is None:
        return ""
    s = str(value)
    if len(s) > CSP_SIGNAL_FIELD_MAX_LENGTH:
        return s[:CSP_SIGNAL_FIELD_MAX_LENGTH]
    return s


def _csp_property(properties: dict, key: str) -> Any:
    return properties.get(f"$csp_{key}")


def _fingerprint(properties: dict) -> str:
    fingerprint_input = json.dumps(
        [
            _stringify(_csp_property(properties, key))
            for key in ("violated_directive", "blocked_url", "document_url", "source_file")
        ],
        separators=(",", ":"),
    )
    return hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()


def _dedup_key(team_id: int, fingerprint: str) -> str:
    return f"{CSP_SIGNAL_DEDUP_KEY_PREFIX}:{team_id}:{fingerprint}"


def _source_id(fingerprint: str) -> str:
    return f"csp:{fingerprint}"


def _enabled_cache_key(team_id: int) -> str:
    return f"{CSP_SIGNAL_ENABLED_CACHE_KEY_PREFIX}:{team_id}"


def _daily_count_key(team_id: int) -> str:
    today = datetime.now(UTC).date().isoformat()
    return f"{CSP_SIGNAL_DAILY_COUNT_KEY_PREFIX}:{team_id}:{today}"


def _is_csp_signal_enabled(team_id: int) -> bool:
    """
    Cached check for whether the team has opted into CSP signal emission via SignalSourceConfig.
    Cached for `CSP_SIGNAL_ENABLED_CACHE_TTL_SECONDS` so flipping the toggle takes effect within
    that window without hammering Postgres on every CSP report.
    """
    cache_key = _enabled_cache_key(team_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)
    enabled = SignalSourceConfig.is_source_enabled(team_id, CSP_SIGNAL_SOURCE_PRODUCT, CSP_SIGNAL_SOURCE_TYPE)
    cache.set(cache_key, enabled, CSP_SIGNAL_ENABLED_CACHE_TTL_SECONDS)
    return enabled


def _suggested_origin(blocked_url: str) -> str | None:
    """Return scheme://host for use in a suggested CSP directive snippet, or None."""
    if not blocked_url:
        return None
    try:
        parsed = urlparse(blocked_url)
    except ValueError:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_description(properties: dict) -> str:
    """
    Build a static, embedding-friendly description of a CSP violation. Mirrors the structure
    of the on-demand `csp_reporting.explain` LLM prompt — cause, suggested fix, triage — but
    without calling an LLM, so it stays cheap and stable for vector grouping.
    """
    violated_directive = _stringify(_csp_property(properties, "violated_directive"))
    effective_directive = _stringify(_csp_property(properties, "effective_directive"))
    blocked_url = _stringify(_csp_property(properties, "blocked_url"))
    document_url = _stringify(_csp_property(properties, "document_url"))
    disposition = _stringify(_csp_property(properties, "disposition")) or "unknown"
    source_file = _stringify(_csp_property(properties, "source_file"))
    line_number = _stringify(_csp_property(properties, "line_number"))
    column_number = _stringify(_csp_property(properties, "column_number"))
    user_agent = _stringify(_csp_property(properties, "user_agent"))

    directive_display = violated_directive or "unknown directive"
    blocked_display = blocked_url or "unknown resource"
    page_display = document_url or "unknown page"

    location = source_file
    if location and line_number:
        location = f"{source_file}:{line_number}"
        if column_number:
            location = f"{location}:{column_number}"

    cause_lines = [
        "## Cause",
        f"The `{directive_display}` directive on `{page_display}` blocked the resource `{blocked_display}`.",
        f"Disposition: {disposition}.",
    ]
    if location:
        cause_lines.append(f"Source location: `{location}`.")
    if user_agent:
        cause_lines.append(f"Browser: `{user_agent}`.")

    fix_directive = effective_directive or violated_directive
    fix_origin = _suggested_origin(blocked_url)
    fix_lines = ["## Suggested fix"]
    if fix_origin and fix_directive:
        fix_lines.append(
            f"If `{fix_origin}` is a legitimate resource, allow it by adding it to the `{fix_directive}` directive:"
        )
        fix_lines.append(f"`{fix_directive} 'self' {fix_origin};`")
    else:
        fix_lines.append(
            "Decide whether the blocked resource is legitimate. If yes, add its origin to the violated directive. "
            "If no, investigate where the request to it came from."
        )

    triage_lines = [
        "## Triage",
        "Three things to rule out:",
        "1. The blocked resource is legitimate and the CSP policy needs widening.",
        "2. The blocked resource is an injected or compromised script — a security incident.",
        "3. The blocked resource is a third-party script the team should remove.",
    ]

    return "\n".join([*cause_lines, "", *fix_lines, "", *triage_lines])


def _build_extra(properties: dict) -> dict:
    def get_str(key: str) -> str | None:
        value = _csp_property(properties, key)
        if value is None:
            return None
        s = str(value)
        if len(s) > CSP_SIGNAL_FIELD_MAX_LENGTH:
            return s[:CSP_SIGNAL_FIELD_MAX_LENGTH]
        return s

    def get_number(key: str) -> float | None:
        value = _csp_property(properties, key)
        if value is None or value == "":
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(result):
            return None
        return result

    return {
        "document_url": get_str("document_url"),
        "violated_directive": get_str("violated_directive"),
        "effective_directive": get_str("effective_directive"),
        "original_policy": get_str("original_policy"),
        "blocked_url": get_str("blocked_url"),
        "source_file": get_str("source_file"),
        "line_number": get_number("line_number"),
        "column_number": get_number("column_number"),
        "disposition": get_str("disposition"),
        "referrer": get_str("referrer"),
        "user_agent": get_str("user_agent"),
    }


def enqueue_csp_violation_signals(team_id: int, properties_list: list[dict]) -> int:
    """
    Check the team's opt-in once (cached), then for each unique-per-24h violation in
    `properties_list` build a signal payload and enqueue them all in a single Celery task.
    Returns the number of signals queued.

    Per-violation throttling uses Redis SET NX EX so duplicates across web workers do not
    emit twice. Signal emission itself is best-effort: if it fails, the violation event has
    already been captured through the normal ingestion path.
    """
    total = len(properties_list)
    if total == 0:
        return 0

    if not settings.CSP_SIGNAL_EMISSION_ENABLED:
        _record_dropped(team_id, total, reason="ops_kill_switch")
        return 0

    if not _is_csp_signal_enabled(team_id):
        _record_dropped(team_id, total, reason="source_disabled")
        return 0

    client = get_client()
    daily_key = _daily_count_key(team_id)
    cap = settings.CSP_SIGNAL_DAILY_CAP_PER_TEAM

    # Reserve `total` slots atomically up front, then roll back any unused slots
    # (duplicates, cap overflow, broker failure). INCRBY is atomic across workers
    # so concurrent callers can't both claim the last N slots.
    try:
        new_count = client.incrby(daily_key, total)
        # Idempotent TTL — covers cold key, eviction, or manual admin set.
        client.expire(daily_key, CSP_SIGNAL_DAILY_COUNT_TTL_SECONDS)
    except Exception:
        logger.exception("csp_signal_daily_count_reserve_failed", team_id=team_id)
        _record_dropped(team_id, total, reason="redis_count_error")
        return 0

    def _release_slots(n: int) -> None:
        if n <= 0:
            return
        try:
            client.decrby(daily_key, n)
        except Exception:
            logger.exception("csp_signal_daily_count_release_failed", team_id=team_id, slots=n)

    reserved = total
    if new_count > cap:
        over = new_count - cap
        if over >= total:
            _release_slots(total)
            _record_dropped(team_id, total, reason="daily_cap_reached")
            return 0
        reserved = total - over
        _release_slots(over)
        _record_dropped(team_id, over, reason="daily_cap_reached")

    signals_to_emit: list[dict] = []
    acquired_keys: list[str] = []
    for properties in properties_list[:reserved]:
        fingerprint = _fingerprint(properties)
        key = _dedup_key(team_id, fingerprint)
        try:
            acquired = client.set(key, "1", nx=True, ex=CSP_SIGNAL_DEDUP_TTL_SECONDS)
        except Exception:
            _record_dropped(team_id, 1, reason="redis_throttle_error")
            logger.exception("csp_signal_throttle_check_failed", team_id=team_id, fingerprint=fingerprint)
            continue
        if not acquired:
            _record_dropped(team_id, 1, reason="duplicate")
            continue
        acquired_keys.append(key)
        signals_to_emit.append(
            {
                "source_id": _source_id(fingerprint),
                "description": _build_description(properties),
                "extra": _build_extra(properties),
            }
        )

    # Release reserved slots we didn't actually fill (dedup misses, redis errors).
    unused = reserved - len(signals_to_emit)
    _release_slots(unused)

    if not signals_to_emit:
        return 0

    try:
        emit_csp_violation_signals_task.delay(team_id=team_id, signals=signals_to_emit)
    except Exception:
        # Release dedup keys and the reservation together so the next request can retry.
        for key in acquired_keys:
            try:
                client.delete(key)
            except Exception:
                pass
        _release_slots(len(signals_to_emit))
        _record_dropped(team_id, len(signals_to_emit), reason="celery_enqueue_failed")
        logger.exception("csp_signal_celery_enqueue_failed", team_id=team_id, signal_count=len(signals_to_emit))
        return 0

    _record_outcome(team_id, len(signals_to_emit), "embedded")
    return len(signals_to_emit)


@shared_task(
    ignore_result=True,
    max_retries=0,
    soft_time_limit=CSP_SIGNAL_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=CSP_SIGNAL_TASK_TIME_LIMIT_SECONDS,
)
@with_team_scope()
def emit_csp_violation_signals_task(team_id: int, signals: list[dict]) -> None:
    from products.signals.backend.api import emit_signal

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        CSP_SIGNAL_DROPPED_COUNTER.labels(reason="missing_team").inc()
        logger.warning("csp_signal_emit_missing_team", team_id=team_id, signal_count=len(signals))
        return

    for i, signal in enumerate(signals):
        source_id = signal.get("source_id", "")
        try:
            async_to_sync(emit_signal)(
                team=team,
                source_product=CSP_SIGNAL_SOURCE_PRODUCT,
                source_type=CSP_SIGNAL_SOURCE_TYPE,
                source_id=source_id,
                description=signal["description"],
                weight=CSP_SIGNAL_WEIGHT,
                extra=signal.get("extra") or {},
            )
        except SoftTimeLimitExceeded:
            # Soft-time-limit is the graceful-stop signal from Celery. Let it propagate
            # so the worker actually stops iterating instead of silently swallowing it
            # via the broad-except below (SoftTimeLimitExceeded inherits from Exception).
            CSP_SIGNAL_DROPPED_COUNTER.labels(reason="soft_time_limit").inc()
            logger.warning(
                "csp_signal_task_soft_time_limit",
                team_id=team_id,
                emitted_so_far=i,
                remaining=len(signals) - i,
            )
            raise
        except Exception:
            CSP_SIGNAL_DROPPED_COUNTER.labels(reason="emit_signal_failed").inc()
            logger.exception("csp_signal_emit_failed", team_id=team_id, source_id=source_id)
