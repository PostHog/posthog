"""
Web Vitals → Signals emission helper.

Unlike CSP violations (which fan out per-request at ingest), web vitals fire from a
scheduled Temporal activity that aggregates p75 over a window. This module provides:

- Identity-keyed signal dataclasses (threshold crossing + sustained regression).
- The shared four-gate pattern matching `posthog/tasks/csp_signal.py`:
  ops kill switch → per-team opt-in (cached) → per-team daily cap → 24h dedup.
- State storage helpers for transition / streak detection (Redis with versioned prefix).
- A static description builder that mirrors a future on-demand "explain" LLM prompt —
  cheap, stable, embedding-friendly.

The helper itself is synchronous (calls `async_to_sync(emit_signal)`) so it can be
invoked from sync Temporal activities, sync tests, or any sync caller.
"""

import json
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from django.conf import settings
from django.core.cache import cache

import structlog
from asgiref.sync import async_to_sync
from prometheus_client import Counter

from posthog.models.team.team import Team
from posthog.redis import get_client

from products.signals.backend.api import emit_signal
from products.signals.backend.models import SignalSourceConfig

logger = structlog.get_logger(__name__)

WEB_VITALS_SIGNAL_SOURCE_PRODUCT = "web_analytics"
WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING = "web_vitals_threshold_crossing"
WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION = "web_vitals_regression"
WEB_VITALS_SIGNAL_WEIGHT = 0.5

WEB_VITALS_SIGNAL_DEDUP_TTL_SECONDS = 60 * 60 * 24
WEB_VITALS_SIGNAL_DEDUP_KEY_PREFIX = "web_vitals_signal_dedup:v1"
WEB_VITALS_SIGNAL_ENABLED_CACHE_TTL_SECONDS = 60
WEB_VITALS_SIGNAL_ENABLED_CACHE_KEY_PREFIX = "web_vitals_signal_enabled"
WEB_VITALS_SIGNAL_DAILY_COUNT_KEY_PREFIX = "web_vitals_signal_daily_count"
WEB_VITALS_SIGNAL_DAILY_COUNT_TTL_SECONDS = 60 * 60 * 25  # safe margin past UTC midnight

# Band state for the threshold-crossing detector. 7-day TTL gives a generous window for
# auto-resolve of bands that have been good for a long time.
WEB_VITALS_SIGNAL_BAND_STATE_KEY_PREFIX = "web_vitals_signal_band:v1"
WEB_VITALS_SIGNAL_BAND_STATE_TTL_SECONDS = 60 * 60 * 24 * 7

# Consecutive-regression counter. Pruned faster than the band state — 4h is enough to
# require two consecutive hourly evaluations, but short enough that intermittent recovery
# resets the streak.
WEB_VITALS_SIGNAL_STREAK_KEY_PREFIX = "web_vitals_signal_streak:v1"
WEB_VITALS_SIGNAL_STREAK_TTL_SECONDS = 60 * 60 * 4
WEB_VITALS_SIGNAL_REGRESSION_CONSECUTIVE_REQUIRED = 2

WEB_VITALS_FIELD_MAX_LENGTH = 2048

# Mirror of frontend/src/queries/nodes/WebVitals/definitions.ts. Single Python source of
# truth for backend detection so frontend/backend can't drift.
WebVitalsMetricName = Literal["LCP", "INP", "CLS", "FCP"]
WebVitalsBand = Literal["good", "needs_improvements", "poor"]
WebVitalsDeviceClass = Literal["Desktop", "Mobile", "Tablet", "unknown"]

WEB_VITALS_THRESHOLDS: dict[str, tuple[float, float]] = {
    "LCP": (2500.0, 4000.0),
    "INP": (200.0, 500.0),
    "CLS": (0.1, 0.25),
    "FCP": (1800.0, 3000.0),
}

# CLS is intentionally absent from regression detection (too bursty for delta-based
# detection — threshold crossing only for v1).
REGRESSION_METRICS: tuple[str, ...] = ("LCP", "INP", "FCP")

WEB_VITALS_SIGNAL_DROPPED_COUNTER = Counter(
    "web_vitals_signal_dropped_total",
    "Web-vitals signal emissions skipped before reaching the signals pipeline, tagged by reason.",
    labelnames=["reason"],
)

WEB_VITALS_SIGNAL_OUTCOME_COUNTER = Counter(
    "web_vitals_signal_outcome_total",
    "Per-team count of web-vitals signals embedded into the signals pipeline vs dropped.",
    labelnames=["team_id", "outcome"],
)


def _record_outcome(team_id: int, n: int, outcome: str) -> None:
    if n <= 0:
        return
    WEB_VITALS_SIGNAL_OUTCOME_COUNTER.labels(team_id=str(team_id), outcome=outcome).inc(n)


def _record_dropped(team_id: int, n: int, reason: str) -> None:
    if n <= 0:
        return
    WEB_VITALS_SIGNAL_DROPPED_COUNTER.labels(reason=reason).inc(n)
    _record_outcome(team_id, n, "dropped")


def _truncate(value: object) -> str:
    if value is None:
        return ""
    s = str(value)
    if len(s) > WEB_VITALS_FIELD_MAX_LENGTH:
        return s[:WEB_VITALS_FIELD_MAX_LENGTH]
    return s


def classify_band(metric: str, value: float) -> WebVitalsBand:
    good, poor = WEB_VITALS_THRESHOLDS[metric]
    if value <= good:
        return "good"
    if value <= poor:
        return "needs_improvements"
    return "poor"


def _format_value(metric: str, value: float) -> str:
    if metric == "CLS":
        return f"{value:.3f}"
    return f"{int(round(value))}ms"


def _format_route(route: str) -> str:
    return route if route else "(no path)"


def _format_device(device_class: str) -> str:
    return device_class.lower() if device_class and device_class != "unknown" else "all devices"


def _format_band(band: WebVitalsBand) -> str:
    return {"good": "good", "needs_improvements": "needs improvement", "poor": "poor"}[band]


@dataclass(frozen=True)
class WebVitalsThresholdCrossingSignal:
    """A p75 metric on (route, device) just transitioned between Google bands."""

    metric: str
    route: str
    device_class: str
    p75_value: float
    threshold_band: WebVitalsBand
    previous_band: WebVitalsBand | None
    sample_count: int
    window_hours: int

    def fingerprint(self) -> str:
        # Identity excludes the value itself — we want one signal per band entry, not
        # one per p75 sample. `previous_band` is part of the identity so a band reversal
        # (poor → needs_improvements → poor) emits a fresh signal.
        identity = json.dumps(
            [
                self.metric,
                self.route,
                self.device_class,
                self.threshold_band,
                self.previous_band or "",
            ],
            separators=(",", ":"),
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def source_id(self) -> str:
        return f"web_vitals_threshold:{self.fingerprint()}"

    def description(self) -> str:
        good, poor = WEB_VITALS_THRESHOLDS[self.metric]
        band_display = _format_band(self.threshold_band)
        threshold_value = poor if self.threshold_band == "poor" else good
        cause_lines = [
            "## What happened",
            f"p75 {self.metric} on `{_format_route(self.route)}` ({_format_device(self.device_class)}) "
            f"crossed into the **{band_display}** band over the last {self.window_hours}h "
            f"with {self.sample_count:,} pageviews. Current value: "
            f"{_format_value(self.metric, self.p75_value)} "
            f"(threshold: {_format_value(self.metric, threshold_value)}).",
        ]
        if self.previous_band:
            cause_lines.append(
                f"Previous band: **{_format_band(self.previous_band)}** "
                f"({_format_value(self.metric, good)} good / {_format_value(self.metric, poor)} poor)."
            )

        cause_section = _CAUSE_HINTS.get(self.metric, [])
        triage_lines = [
            "## Triage",
            "1. Open Web analytics → Web vitals, filter to this route and device class.",
            f"2. Inspect Chrome DevTools → Performance for representative pageviews on `{_format_route(self.route)}`.",
            "3. Correlate against recent deploys and third-party script changes.",
        ]

        return "\n".join([*cause_lines, "", "## Common causes", *cause_section, "", *triage_lines])

    def signal_extra(self) -> dict:
        good, poor = WEB_VITALS_THRESHOLDS[self.metric]
        return {
            "metric": self.metric,
            "route": self.route,
            "device_class": self.device_class,
            "p75_value": self.p75_value,
            "threshold_band": self.threshold_band,
            "previous_band": self.previous_band,
            "sample_count": self.sample_count,
            "window_hours": self.window_hours,
            "good_threshold": good,
            "poor_threshold": poor,
        }

    def to_signal_payload(self) -> dict:
        return {
            "source_id": self.source_id(),
            "description": self.description(),
            "extra": self.signal_extra(),
        }


@dataclass(frozen=True)
class WebVitalsRegressionSignal:
    """A p75 metric has sustainedly regressed vs its baseline."""

    metric: str
    route: str
    device_class: str
    current_p75: float
    baseline_p75: float
    sample_count: int
    baseline_sample_count: int
    window_hours: int
    baseline_window_days: int

    @property
    def pct_change(self) -> float:
        if self.baseline_p75 <= 0:
            return 0.0
        return ((self.current_p75 - self.baseline_p75) / self.baseline_p75) * 100.0

    def fingerprint(self) -> str:
        identity = json.dumps(
            [self.metric, self.route, self.device_class, "regression"],
            separators=(",", ":"),
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def source_id(self) -> str:
        return f"web_vitals_regression:{self.fingerprint()}"

    def description(self) -> str:
        delta = _format_value(self.metric, self.current_p75 - self.baseline_p75)
        cause_lines = [
            "## What happened",
            f"p75 {self.metric} on `{_format_route(self.route)}` ({_format_device(self.device_class)}) "
            f"regressed from {_format_value(self.metric, self.baseline_p75)} "
            f"(over the past {self.baseline_window_days}d) to "
            f"{_format_value(self.metric, self.current_p75)} "
            f"over the last {self.window_hours}h — a {self.pct_change:+.1f}% change ({delta}).",
            f"Sustained across {WEB_VITALS_SIGNAL_REGRESSION_CONSECUTIVE_REQUIRED} consecutive evaluations.",
            f"Samples: {self.sample_count:,} (current window) / {self.baseline_sample_count:,} (baseline).",
        ]
        cause_section = _CAUSE_HINTS.get(self.metric, [])
        triage_lines = [
            "## Triage",
            f"1. Check the deploy log for changes touching `{_format_route(self.route)}` in the last "
            f"{self.window_hours + 1}h.",
            "2. Compare the p75 trend in the Web vitals dashboard for this route and device class.",
            "3. Inspect Chrome DevTools → Performance → Interactions for the slowest sub-parts.",
        ]
        return "\n".join([*cause_lines, "", "## Common causes", *cause_section, "", *triage_lines])

    def signal_extra(self) -> dict:
        return {
            "metric": self.metric,
            "route": self.route,
            "device_class": self.device_class,
            "current_p75": self.current_p75,
            "baseline_p75": self.baseline_p75,
            "pct_change": self.pct_change,
            "sample_count": self.sample_count,
            "baseline_sample_count": self.baseline_sample_count,
            "window_hours": self.window_hours,
            "baseline_window_days": self.baseline_window_days,
        }

    def to_signal_payload(self) -> dict:
        return {
            "source_id": self.source_id(),
            "description": self.description(),
            "extra": self.signal_extra(),
        }


WebVitalsSignal = WebVitalsThresholdCrossingSignal | WebVitalsRegressionSignal


# Static cause hints per metric. Embedding-friendly + stable across runs.
_CAUSE_HINTS: dict[str, list[str]] = {
    "LCP": [
        "- Render-blocking resources (scripts, fonts, CSS in the critical path).",
        "- Slow server response time (high TTFB).",
        "- Large unoptimized images or video posters above the fold.",
        "- Third-party scripts delaying the largest paint.",
    ],
    "INP": [
        "- Heavy event handlers introduced in a recent deploy.",
        "- New blocking third-party scripts.",
        "- Long tasks during page interactions (>50ms).",
        "- Hydration cost on initial load for SSR/SSG frameworks.",
    ],
    "CLS": [
        "- Images without explicit `width`/`height` attributes.",
        "- Late-injected DOM (banners, ads, GDPR notices).",
        "- Font swap without `font-display: optional` or sized fallbacks.",
        "- Third-party widgets that resize after first paint.",
    ],
    "FCP": [
        "- Render-blocking CSS or JS in the document `<head>`.",
        "- Slow TTFB (server response time).",
        "- Web fonts loaded without `font-display: swap`.",
        "- Synchronous third-party scripts above the fold.",
    ],
}


def _dedup_key(team_id: int, source_type: str, fingerprint: str) -> str:
    return f"{WEB_VITALS_SIGNAL_DEDUP_KEY_PREFIX}:{team_id}:{source_type}:{fingerprint}"


def _enabled_cache_key(team_id: int, source_type: str) -> str:
    return f"{WEB_VITALS_SIGNAL_ENABLED_CACHE_KEY_PREFIX}:{team_id}:{source_type}"


def _daily_count_key(team_id: int) -> str:
    today = datetime.now(UTC).date().isoformat()
    return f"{WEB_VITALS_SIGNAL_DAILY_COUNT_KEY_PREFIX}:{team_id}:{today}"


def _is_web_vitals_signal_enabled(team_id: int, source_type: str) -> bool:
    cache_key = _enabled_cache_key(team_id, source_type)
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)
    enabled = SignalSourceConfig.is_source_enabled(team_id, WEB_VITALS_SIGNAL_SOURCE_PRODUCT, source_type)
    cache.set(cache_key, enabled, WEB_VITALS_SIGNAL_ENABLED_CACHE_TTL_SECONDS)
    return enabled


def _band_state_key(team_id: int, metric: str, route: str, device_class: str) -> str:
    return f"{WEB_VITALS_SIGNAL_BAND_STATE_KEY_PREFIX}:{team_id}:{metric}:{device_class}:{route}"


def _streak_key(team_id: int, metric: str, route: str, device_class: str) -> str:
    return f"{WEB_VITALS_SIGNAL_STREAK_KEY_PREFIX}:{team_id}:{metric}:{device_class}:{route}"


def get_last_band(team_id: int, metric: str, route: str, device_class: str) -> WebVitalsBand | None:
    """Read the previously-recorded band for a (team, metric, route, device). None means
    no record — treated as a first observation, so no signal emits until the band
    actually transitions."""
    try:
        raw = get_client().get(_band_state_key(team_id, metric, route, device_class))
    except Exception:
        logger.exception(
            "web_vitals_signal_band_state_read_failed",
            team_id=team_id,
            metric=metric,
            route=route,
            device_class=device_class,
        )
        return None
    if raw is None:
        return None
    band = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    if band == "good":
        return "good"
    if band == "needs_improvements":
        return "needs_improvements"
    if band == "poor":
        return "poor"
    return None


def set_last_band(team_id: int, metric: str, route: str, device_class: str, band: WebVitalsBand) -> None:
    try:
        get_client().set(
            _band_state_key(team_id, metric, route, device_class),
            band,
            ex=WEB_VITALS_SIGNAL_BAND_STATE_TTL_SECONDS,
        )
    except Exception:
        logger.exception(
            "web_vitals_signal_band_state_write_failed",
            team_id=team_id,
            metric=metric,
            route=route,
            device_class=device_class,
        )


def increment_regression_streak(team_id: int, metric: str, route: str, device_class: str) -> int:
    """Atomically increment the consecutive-regression counter and refresh its TTL.
    Returns 0 on Redis failure (caller should treat that as "do not fire")."""
    key = _streak_key(team_id, metric, route, device_class)
    try:
        client = get_client()
        new_value = client.incr(key)
        client.expire(key, WEB_VITALS_SIGNAL_STREAK_TTL_SECONDS)
        return int(new_value)
    except Exception:
        logger.exception(
            "web_vitals_signal_streak_incr_failed",
            team_id=team_id,
            metric=metric,
            route=route,
            device_class=device_class,
        )
        return 0


def reset_regression_streak(team_id: int, metric: str, route: str, device_class: str) -> None:
    try:
        get_client().delete(_streak_key(team_id, metric, route, device_class))
    except Exception:
        logger.exception(
            "web_vitals_signal_streak_reset_failed",
            team_id=team_id,
            metric=metric,
            route=route,
            device_class=device_class,
        )


def _release_slots(team_id: int, daily_key: str, n: int) -> None:
    if n <= 0:
        return
    try:
        get_client().decrby(daily_key, n)
    except Exception:
        logger.exception("web_vitals_signal_daily_count_release_failed", team_id=team_id, slots=n)


def enqueue_web_vitals_signals(team_id: int, signals: list[WebVitalsSignal]) -> int:
    """
    Run the four-gate pattern (kill switch → opt-in → daily cap → dedup) and emit any
    survivors via `emit_signal`. Returns the number of signals embedded.

    Mixed batches (threshold + regression) are supported — opt-in is checked per
    source_type. Daily cap is shared across both types per team, which matches the
    "embedder load attribution" framing of the metric.
    """
    total = len(signals)
    if total == 0:
        return 0

    if not settings.WEB_VITALS_SIGNAL_EMISSION_ENABLED:
        _record_dropped(team_id, total, reason="ops_kill_switch")
        return 0

    # Per-source-type opt-in. Drop the disabled ones up front so they don't consume cap.
    candidates: list[tuple[WebVitalsSignal, str]] = []
    for signal in signals:
        source_type = _source_type_for(signal)
        if _is_web_vitals_signal_enabled(team_id, source_type):
            candidates.append((signal, source_type))
        else:
            _record_dropped(team_id, 1, reason="source_disabled")
    if not candidates:
        return 0

    daily_key = _daily_count_key(team_id)
    cap = settings.WEB_VITALS_SIGNAL_DAILY_CAP_PER_TEAM
    client = get_client()
    try:
        new_count = client.incrby(daily_key, len(candidates))
        client.expire(daily_key, WEB_VITALS_SIGNAL_DAILY_COUNT_TTL_SECONDS)
    except Exception:
        logger.exception("web_vitals_signal_daily_count_reserve_failed", team_id=team_id)
        _record_dropped(team_id, len(candidates), reason="redis_count_error")
        return 0

    reserved = len(candidates)
    if new_count > cap:
        over = new_count - cap
        if over >= len(candidates):
            _release_slots(team_id, daily_key, len(candidates))
            _record_dropped(team_id, len(candidates), reason="daily_cap_reached")
            return 0
        reserved = len(candidates) - over
        _release_slots(team_id, daily_key, over)
        _record_dropped(team_id, over, reason="daily_cap_reached")

    acquired_keys: list[str] = []
    to_emit: list[tuple[WebVitalsSignal, str]] = []
    for signal, source_type in candidates[:reserved]:
        fingerprint = signal.fingerprint()
        key = _dedup_key(team_id, source_type, fingerprint)
        try:
            acquired = client.set(key, "1", nx=True, ex=WEB_VITALS_SIGNAL_DEDUP_TTL_SECONDS)
        except Exception:
            _record_dropped(team_id, 1, reason="redis_throttle_error")
            logger.exception(
                "web_vitals_signal_throttle_check_failed",
                team_id=team_id,
                fingerprint=fingerprint,
                source_type=source_type,
            )
            continue
        if not acquired:
            _record_dropped(team_id, 1, reason="duplicate")
            continue
        acquired_keys.append(key)
        to_emit.append((signal, source_type))

    unused = reserved - len(to_emit)
    _release_slots(team_id, daily_key, unused)

    if not to_emit:
        return 0

    # Resolve team once. Missing team is treated as a hard failure — return what we
    # can but log so the caller (scheduled workflow) sees it.
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        for key in acquired_keys:
            try:
                client.delete(key)
            except Exception:
                pass
        _release_slots(team_id, daily_key, len(to_emit))
        _record_dropped(team_id, len(to_emit), reason="missing_team")
        logger.warning("web_vitals_signal_emit_missing_team", team_id=team_id, signal_count=len(to_emit))
        return 0

    embedded = 0
    for (signal, source_type), key in zip(to_emit, acquired_keys):
        payload = signal.to_signal_payload()
        try:
            async_to_sync(emit_signal)(
                team=team,
                source_product=WEB_VITALS_SIGNAL_SOURCE_PRODUCT,
                source_type=source_type,
                source_id=payload["source_id"],
                description=payload["description"],
                weight=WEB_VITALS_SIGNAL_WEIGHT,
                extra=payload["extra"],
            )
            embedded += 1
        except Exception:
            # Release the dedup key so a retry next evaluation can re-emit.
            try:
                client.delete(key)
            except Exception:
                pass
            _release_slots(team_id, daily_key, 1)
            _record_dropped(team_id, 1, reason="emit_signal_failed")
            logger.exception(
                "web_vitals_signal_emit_failed",
                team_id=team_id,
                source_id=payload["source_id"],
                source_type=source_type,
            )

    _record_outcome(team_id, embedded, "embedded")
    return embedded


def _source_type_for(signal: WebVitalsSignal) -> str:
    if isinstance(signal, WebVitalsThresholdCrossingSignal):
        return WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING
    return WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION
