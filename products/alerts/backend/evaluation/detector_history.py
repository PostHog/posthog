"""Serve a SQL detector alert's older history from cached hourly buckets.

A detector needs its whole window of bucketed values on every check, and every bucket except the
most recent few is a closed hour whose value the previous check already computed. This module
keeps those values, asks ``events_recent`` which buckets received late rows, and narrows each
check's scan to exactly the buckets that can have changed.

Every step falls back to the full scan rather than guessing: an unrecognized query, a changed
query, missing probe bookkeeping, a gap the cache cannot prove it covers, or too few points for
the detector all lead back to today's behavior, and the cache is rebuilt from that scan.
"""

import json
import random
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone as django_timezone

from posthog.schema import HogQLAlertConfig, HogQLAlertEvaluation, HogQLQueryModifiers

from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen
from posthog.hogql_queries.paginators import get_query_limit
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.team.event_retention import events_retention_months_for_team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false, ph_background_capture

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.alerts.backend.evaluation.detector_history_eligibility import (
    DetectorSeriesQuery,
    match_detector_series_query,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.models.alert_series_point import AlertSeriesPoint, AlertSeriesState
from products.product_analytics.backend.facade.models import Insight

INCREMENTAL_DETECTOR_HISTORY_FLAG = "alerts-incremental-detector-history"

# Rescanned on every check even when the probe reports nothing, so the scored row is always fresh.
DEFAULT_MARGIN_HOURS = 3
# Buckets survive this long past the window so a widened gap scan can reuse them after missed
# checks; mirrors lazy_computation's 48h retention buffer.
PRUNE_EXTRA_HOURS = 48
# App clock vs warehouse clock slack, same caution as data_freshness.py's skew ceiling.
_CLOCK_SKEW_HOURS = 1
# Bounds the drift no insert signal reveals (person merges, dedup collapses, partition attaches).
RESEED_INTERVAL_HOURS = 24
# One day inside events_recent's 9-day TTL, so the probe never trusts a horizon it cannot see.
_PROBE_HORIZON_HOURS = 8 * 24

# One result row: the bucket cell rendered in the team timezone, then the value.
_Row = list[Any]
RunQuery = Callable[..., tuple[list, list[str] | None]]


@frozen
class _CheckContext:
    """Everything one admitted check reasons with, resolved once."""

    alert: AlertConfiguration
    team: Team
    team_id: int
    matched: DetectorSeriesQuery
    fingerprint: str
    now: datetime
    anchor: datetime
    min_samples: int
    run_query: RunQuery

    @property
    def window_hours(self) -> int:
        return self.matched.window_hours

    @property
    def window_start(self) -> datetime:
        return self.anchor - timedelta(hours=self.window_hours)


class _BucketSeries:
    """Hourly values keyed by UTC instant — the one place timezone conversion happens.

    The query returns cells in the team timezone and Postgres returns UTC; both normalize to
    UTC keys here, and ``window_rows`` renders cells back in the team timezone, which is
    exactly the form the full scan returns them in.
    """

    def __init__(self, team: Team, values: dict[datetime, float]) -> None:
        self.team = team
        self.values = values

    @classmethod
    def parse(cls, team: Team, rows: list) -> "_BucketSeries | None":
        """Index query rows by bucket instant, or None when a row is not a (bucket, value) pair."""
        values: dict[datetime, float] = {}
        for row in rows:
            if not isinstance(row, list | tuple) or len(row) != 2:
                return None
            bucket, raw = row
            if not isinstance(bucket, datetime):
                return None
            if raw is None:
                value = 0.0
            elif isinstance(raw, bool) or not isinstance(raw, int | float | Decimal):
                return None
            else:
                value = float(raw)
            values[cls._to_utc(bucket, team)] = value
        return cls(team, values)

    @staticmethod
    def _to_utc(bucket: datetime, team: Team) -> datetime:
        if bucket.tzinfo is None:
            return bucket.replace(tzinfo=team.timezone_info).astimezone(UTC)
        return bucket.astimezone(UTC)

    def __len__(self) -> int:
        return len(self.values)

    def newest(self) -> datetime:
        return max(self.values)

    def replaced_by(self, scanned: "_BucketSeries", within: set[datetime]) -> "_BucketSeries":
        """This series with every bucket the scan was authoritative for taken from the scan."""
        merged = {bucket: value for bucket, value in self.values.items() if bucket not in within}
        merged.update(scanned.values)
        return _BucketSeries(self.team, merged)

    def window_rows(self, anchor: datetime, window_hours: int) -> list[_Row]:
        """The newest ``window_hours`` in-window buckets, oldest first, cells in the team timezone."""
        in_window = sorted(bucket for bucket in self.values if bucket >= anchor - timedelta(hours=window_hours))
        return [
            [bucket.astimezone(self.team.timezone_info), self.values[bucket]] for bucket in in_window[-window_hours:]
        ]


def detector_rows_from_history(
    *,
    alert: AlertConfiguration,
    insight: Insight,
    config: HogQLAlertConfig,
    min_samples: int,
    run_query: RunQuery,
) -> tuple[list[_Row], list[str]] | None:
    """Return the detector's (bucket, value) rows, or None when this alert is not served here.

    None means the caller should run the query the way it always has. Any other outcome,
    including a full scan this function ran itself, comes back as rows.

    ``insight`` is the one the caller is about to run, which the dispatcher may have upgraded,
    so the matcher and the fingerprint read the query that actually executes.
    """
    ctx = _admitted(alert=alert, insight=insight, config=config, min_samples=min_samples, run_query=run_query)
    if ctx is None:
        return None
    if _window_spans_backward_dst_transition(ctx.anchor, ctx.window_hours, ctx.team):
        # A backward fold gives two instants one local label, which an instant-keyed cache
        # cannot tell apart.
        _capture_outcome(ctx.alert, "dst_fold_full_scan", window_hours=ctx.window_hours)
        return None

    cached = _load_cached(ctx)
    if len(cached) < ctx.min_samples:
        return _reseed(ctx, "short_cache")
    state = _load_state(ctx)
    if state is None:
        return _reseed(ctx, "no_watermark")
    staleness = _state_staleness(ctx, state)
    if staleness is not None:
        return _reseed(ctx, staleness)

    probed = _changed_buckets(ctx, state.watermark)
    scan = _scan_buckets(ctx, newest_cached=cached.newest(), probed=probed)
    if len(scan) >= ctx.window_hours:
        return _reseed(ctx, "wide_scan")

    scanned_rows, _ = ctx.run_query(
        query_override=ctx.matched.narrowed_to_buckets(sorted(scan), at=ctx.now, tz=ctx.team.timezone)
    )
    scanned = _BucketSeries.parse(ctx.team, scanned_rows)
    if scanned is None:
        return _reseed(ctx, "unparsable_tail")

    _write(
        ctx,
        scanned=scanned,
        authoritative=scan,
        # A failed probe holds the watermark, so the next check re-detects the same interval.
        watermark=None if probed is None else ctx.now - timedelta(hours=_CLOCK_SKEW_HOURS),
    )

    rows = cached.replaced_by(scanned, within=scan).window_rows(ctx.anchor, ctx.window_hours)
    if len(rows) < ctx.min_samples:
        return _reseed(ctx, "short_assembly")
    if _assembly_reached_query_limit(ctx, rows):
        return _reseed(ctx, "beyond_limit")

    shadow = _shadow_compare(ctx, rows)
    _capture_outcome(
        ctx.alert,
        "cache_hit",
        scanned_buckets=len(scan),
        probed_buckets=0 if probed is None else len(probed),
        probe_failed=probed is None,
        window_hours=ctx.window_hours,
        **shadow,
    )
    return rows, ctx.matched.column_names


def _admitted(
    *,
    alert: AlertConfiguration,
    insight: Insight,
    config: HogQLAlertConfig,
    min_samples: int,
    run_query: RunQuery,
) -> _CheckContext | None:
    """The check's context when the cache may serve this alert at all, else None."""
    team = alert.team
    if not _flag_enabled(team):
        return None
    if config.evaluation != HogQLAlertEvaluation.LAST_ROW:
        # first_row scores the head of the window, which a tail refresh never re-reads.
        _capture_outcome(alert, "ineligible_evaluation")
        return None
    matched = match_detector_series_query(insight.query, column=config.column)
    if matched is None:
        _capture_outcome(alert, "ineligible_query")
        return None
    now = django_timezone.now()
    return _CheckContext(
        alert=alert,
        team=team,
        team_id=resolve_effective_team_id(alert.team_id),
        matched=matched,
        fingerprint=_fingerprint(matched, config, team, alert.created_by),
        now=now,
        anchor=_hour_floor(now, team),
        min_samples=min_samples,
        run_query=run_query,
    )


def _state_staleness(ctx: _CheckContext, state: AlertSeriesState) -> str | None:
    if ctx.now - state.seeded_at >= timedelta(hours=RESEED_INTERVAL_HOURS):
        return "scheduled_reseed"
    if ctx.now - state.watermark >= timedelta(hours=_PROBE_HORIZON_HOURS):
        return "stale_watermark"
    return None


def _scan_buckets(ctx: _CheckContext, *, newest_cached: datetime, probed: list[datetime] | None) -> set[datetime]:
    """The buckets this check must re-read: the margin, any coverage gap, and what the probe found."""
    scan = {ctx.anchor - timedelta(hours=back) for back in range(1, DEFAULT_MARGIN_HOURS + 1)}
    hour = newest_cached - timedelta(hours=_CLOCK_SKEW_HOURS)
    while hour < ctx.anchor:
        scan.add(hour)
        hour += timedelta(hours=1)
    if probed:
        scan.update(probed)
    return {bucket for bucket in scan if ctx.window_start <= bucket < ctx.anchor}


def _assembly_reached_query_limit(ctx: _CheckContext, rows: list[_Row]) -> bool:
    """Tail scans never trip the query's own LIMIT, so at the limit only the full scan's
    completeness guard can say whether the result is truncated."""
    explicit_limit = get_query_limit(ctx.matched.parsed)
    return explicit_limit is not None and len(rows) >= explicit_limit


def _reseed(ctx: _CheckContext, reason: str) -> tuple[list[_Row], list[str]]:
    """Run the query in full, replace the cache with what it returned, and hand back its rows."""
    _capture_outcome(ctx.alert, "full_seed", reason=reason, window_hours=ctx.window_hours)
    rows, column_names = ctx.run_query(query_override=ctx.matched.prepared(at=ctx.now, tz=ctx.team.timezone))
    parsed = _BucketSeries.parse(ctx.team, rows)
    if parsed is not None:
        window = [ctx.anchor - timedelta(hours=back) for back in range(1, ctx.window_hours + 1)]
        _write(
            ctx,
            scanned=parsed,
            authoritative=window,
            watermark=ctx.now - timedelta(hours=_CLOCK_SKEW_HOURS),
            seeded_at=ctx.now,
        )
    return rows, column_names or ctx.matched.column_names


def _shadow_compare(ctx: _CheckContext, rows: list[_Row]) -> dict[str, object]:
    """Sampled, observe-only: does the cache-served series match a full scan right now?

    Divergence is reported, never raised — it is the measurement of accepted identity drift.
    """
    rate = settings.ALERTS_DETECTOR_HISTORY_SHADOW_SAMPLE
    if not rate or random.random() >= rate:
        return {}
    try:
        full_rows, _ = ctx.run_query()
    except Exception:
        return {"shadow_compared": False, "shadow_query_failed": True}
    full = _BucketSeries.parse(ctx.team, full_rows)
    if full is None:
        return {"shadow_compared": True, "shadow_parse_failed": True}
    expected = full.window_rows(ctx.anchor, ctx.window_hours)
    diverging = sum(1 for a, b in zip(expected, rows) if a != b) + abs(len(expected) - len(rows))
    return {"shadow_compared": True, "shadow_equal": diverging == 0, "shadow_diverging_rows": diverging}


def _capture_outcome(alert: AlertConfiguration, outcome: str, **props: object) -> None:
    """One event per flagged check: the rollout's cache-engagement funnel."""
    ph_background_capture()(
        distinct_id=str(alert.id),
        event="alert detector cache outcome",
        properties={"team_id": alert.team_id, "alert_id": str(alert.id), "outcome": outcome, **props},
    )


def _points(team_id: int, alert_id: Any) -> QuerySet[AlertSeriesPoint]:
    return AlertSeriesPoint.objects.for_team(team_id, canonical=True).filter(alert_config_id=alert_id)


def _flag_enabled(team: Team) -> bool:
    return feature_enabled_or_false(
        INCREMENTAL_DETECTOR_HISTORY_FLAG,
        str(team.pk),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def _fingerprint(matched: DetectorSeriesQuery, config: HogQLAlertConfig, team: Team, user: User | None) -> str:
    """Tie cached values to what produced them, so an edit cannot mix two series together."""
    source = matched.source
    inner = source.get("source") if source.get("kind") == "DataVisualizationNode" else source
    restricted = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.id)
    raw_modifiers = inner.get("modifiers") if isinstance(inner, dict) else None
    modifiers = create_default_modifiers_for_team(
        team, HogQLQueryModifiers(**raw_modifiers) if isinstance(raw_modifiers, dict) else None
    )
    payload = json.dumps(
        {
            "query": inner.get("query") if isinstance(inner, dict) else None,
            "column": config.column,
            "evaluation": config.evaluation.value,
            "window_hours": matched.window_hours,
            # Bucket instants render through the team timezone, so a change re-aligns them.
            "timezone": team.timezone,
            # The query executes as the alert creator, and property access control masks values
            # per user.
            "restricted_properties": sorted(
                (r.name, str(r.property_type), -1 if r.group_type_index is None else r.group_type_index)
                for r in restricted
            ),
            # Both change results without a SQL edit, same reason they sit in the HogQL cache key.
            "hogql_modifiers": modifiers.model_dump(mode="json"),
            "events_retention_floor_months": events_retention_months_for_team(team, team.pk),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_cached(ctx: _CheckContext) -> _BucketSeries:
    """Cached in-window buckets, at most ``window_hours`` of them, so a clock straddling an hour
    boundary can only drop the extra oldest bucket — never keep one the full scan dropped."""
    rows = (
        _points(ctx.team_id, ctx.alert.id)
        .filter(fingerprint=ctx.fingerprint, bucket__gte=ctx.window_start)
        .order_by("-bucket")
        .values_list("bucket", "value")[: ctx.window_hours]
    )
    return _BucketSeries(ctx.team, dict(rows))


def _hour_floor(now: datetime, team: Team) -> datetime:
    """The hour the query's toStartOfHour(now()) bounds anchor on: HogQL evaluates now() in the
    team timezone, where a fractional-hour offset shifts the boundary off the UTC one."""
    local = now.astimezone(team.timezone_info)
    return local.replace(minute=0, second=0, microsecond=0).astimezone(UTC)


def _window_spans_backward_dst_transition(anchor: datetime, window_hours: int, team: Team) -> bool:
    offsets: list[timedelta] = []
    for hours in range(window_hours + 1, -1, -1):
        offset = (anchor - timedelta(hours=hours)).astimezone(team.timezone_info).utcoffset()
        offsets.append(offset if offset is not None else timedelta(0))
    return any(later < earlier for earlier, later in zip(offsets, offsets[1:]))


def _load_state(ctx: _CheckContext) -> AlertSeriesState | None:
    """The alert's probe bookkeeping, or None when it is missing or describes another series."""
    state = AlertSeriesState.objects.for_team(ctx.team_id).filter(alert_config_id=ctx.alert.id).first()
    if state is None or state.fingerprint != ctx.fingerprint:
        return None
    return state


def _changed_buckets(ctx: _CheckContext, watermark: datetime) -> list[datetime] | None:
    """Event-hours in the window that received rows after ``watermark``, from events_recent.

    That table sees every insert (a materialized view off the events table) keyed by insert
    time, so lateness of any age is visible at megabytes of read instead of the full window.
    None on error: a probe outage degrades to the margin scan, never fails the check.
    """
    try:
        rows = sync_execute(
            """
            SELECT DISTINCT toStartOfHour(toTimeZone(timestamp, %(tz)s)) AS bucket
            FROM events_recent
            WHERE team_id = %(team_id)s
              AND inserted_at > %(watermark)s
              AND timestamp >= %(window_start)s
              AND timestamp < %(anchor)s
            """,
            {
                "tz": ctx.team.timezone,
                "team_id": ctx.team_id,
                "watermark": watermark,
                "window_start": ctx.window_start,
                "anchor": ctx.anchor,
            },
            team_id=ctx.team_id,
        )
    except Exception:
        return None
    return [_BucketSeries._to_utc(bucket, ctx.team) for (bucket,) in rows]


def _write(
    ctx: _CheckContext,
    *,
    scanned: _BucketSeries,
    authoritative: "set[datetime] | list[datetime]",
    watermark: datetime | None = None,
    seeded_at: datetime | None = None,
) -> None:
    """Store what the scan read, drop what it proved gone, prune what aged out.

    A scanned bucket the scan did not return has no rows any more, so its cached value goes
    (never a zero — the full scan omits it too). The watermark advances in the same
    transaction as the buckets it vouches for: a crash re-detects, never skips.
    """
    prune_before = ctx.now - timedelta(hours=ctx.window_hours + PRUNE_EXTRA_HOURS)
    with transaction.atomic():
        _points(ctx.team_id, ctx.alert.id).filter(bucket__lt=prune_before).delete()
        _points(ctx.team_id, ctx.alert.id).exclude(fingerprint=ctx.fingerprint).delete()
        _points(ctx.team_id, ctx.alert.id).filter(bucket__in=list(authoritative)).exclude(
            bucket__in=list(scanned.values)
        ).delete()
        if watermark is not None:
            updates: dict[str, Any] = {"fingerprint": ctx.fingerprint, "watermark": watermark, "team_id": ctx.team_id}
            if seeded_at is not None:
                updates["seeded_at"] = seeded_at
            AlertSeriesState.objects.for_team(ctx.team_id, canonical=True).update_or_create(
                alert_config_id=ctx.alert.id, defaults=updates
            )
        if scanned.values:
            AlertSeriesPoint.objects.for_team(ctx.team_id, canonical=True).bulk_create(
                [
                    AlertSeriesPoint(
                        team_id=ctx.team_id,
                        alert_config_id=ctx.alert.id,
                        bucket=bucket,
                        value=value,
                        fingerprint=ctx.fingerprint,
                    )
                    for bucket, value in scanned.values.items()
                ],
                update_conflicts=True,
                update_fields=["value", "fingerprint", "computed_at"],
                unique_fields=["alert_config", "bucket"],
            )
