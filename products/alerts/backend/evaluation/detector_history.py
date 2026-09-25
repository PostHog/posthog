"""Serve a SQL detector alert's older history from cached hourly buckets.

A detector needs its whole window of bucketed values on every check, and every bucket except the
most recent few is a closed hour whose value the previous check already computed. This module
keeps those values and narrows each check's scan to the recent tail.

Every step falls back to the full scan rather than guessing: an unrecognized query, a changed
query, a gap the cache cannot prove it covers, or too few points for the detector all lead back
to today's behavior, and the cache is rebuilt from that scan.
"""

import json
import random
import hashlib
from collections.abc import Callable, Iterable
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

# How far back every check re-reads, so an event that arrives late still reaches its bucket.
DEFAULT_MARGIN_HOURS = 3
# Buckets older than the window plus this are dropped on write, so the table stays a fixed size
# per alert while leaving headroom for a window that grows.
# Two days of headroom past the window, so buckets a widened gap scan could still reuse
# survive missed checks; mirrors lazy_computation's 48h retention buffer.
PRUNE_EXTRA_HOURS = 48

# The app clock and the ClickHouse clock can disagree. An hour of headroom on the narrowed scan
# means a disagreement makes that scan slightly wider, never leaves a bucket unread.
# App clock vs warehouse clock slack, same caution as data_freshness.py's skew ceiling.
_CLOCK_SKEW_HOURS = 1
# Bounds the drift no insert signal reveals (person merges, dedup collapses, partition
# attaches). The whole cache path, this included, goes away with the feature flag.
RESEED_INTERVAL_HOURS = 24
# One day inside events_recent's 9-day TTL, so the probe never trusts a horizon it cannot see.
_PROBE_HORIZON_HOURS = 8 * 24

# One result row: the bucket cell as the query returned it, then the value.
_Row = list[Any]
# Bucket instant in UTC -> (bucket cell as returned, value).
_Buckets = dict[datetime, tuple[Any, float]]
RunQuery = Callable[..., tuple[list, list[str] | None]]


def _shadow_compare(
    rows: list[_Row], matched: DetectorSeriesQuery, team: Team, anchor: datetime, run_query: RunQuery
) -> dict[str, object]:
    """Sampled, observe-only: does the cache-served series match a full scan right now?

    Divergence is reported, never raised — it is the measurement of accepted identity drift.
    """
    rate = settings.ALERTS_DETECTOR_HISTORY_SHADOW_SAMPLE
    if not rate or random.random() >= rate:
        return {}
    try:
        full_rows, _ = run_query()
    except Exception:
        # Observe-only means a failing comparison scan can never fail a check that already
        # has valid cache-served rows.
        return {"shadow_compared": False, "shadow_query_failed": True}
    full = _parse_rows(full_rows, team)
    if full is None:
        return {"shadow_compared": True, "shadow_parse_failed": True}
    expected = _assemble(full, matched, anchor)
    diverging = sum(1 for a, b in zip(expected, rows) if a != b) + abs(len(expected) - len(rows))
    return {"shadow_compared": True, "shadow_equal": diverging == 0, "shadow_diverging_rows": diverging}


def _capture_outcome(alert: AlertConfiguration, outcome: str, **props: object) -> None:
    """One event per flagged check: the rollout's cache-engagement funnel."""
    ph_background_capture()(
        distinct_id=str(alert.id),
        event="alert detector cache outcome",
        properties={"team_id": alert.team_id, "alert_id": str(alert.id), "outcome": outcome, **props},
    )


def detector_rows_from_history(
    *,
    alert: AlertConfiguration,
    insight: Insight,
    config: HogQLAlertConfig,
    min_samples: int,
    run_query: RunQuery,
) -> tuple[list[_Row], list[str]] | None:
    """Return the detector's (bucket, value) rows, or None when this alert is not served here.

    None means the caller should run the query the way it always has. Any other outcome, including
    a full scan this function ran itself, comes back as rows.

    ``insight`` is the one the caller is about to run, which the dispatcher may have upgraded, so
    the matcher and the fingerprint read the query that actually executes.
    """
    team = alert.team
    if not _flag_enabled(team):
        return None
    if config.evaluation != HogQLAlertEvaluation.LAST_ROW:
        # first_row scores the head of the window, which the tail refresh never re-reads.
        _capture_outcome(alert, "ineligible_evaluation")
        return None
    matched = match_detector_series_query(insight.query, column=config.column)
    if matched is None:
        _capture_outcome(alert, "ineligible_query")
        return None

    team_id = resolve_effective_team_id(alert.team_id)
    fingerprint = _fingerprint(matched, config, team, alert.created_by)
    now = django_timezone.now()

    def rebuild(reason: str) -> tuple[list[_Row], list[str]]:
        _capture_outcome(alert, "full_seed", reason=reason, window_hours=matched.window_hours)
        return _rebuild(
            alert=alert,
            team_id=team_id,
            matched=matched,
            fingerprint=fingerprint,
            run_query=run_query,
            now=now,
        )

    anchor = _hour_floor(now, team)
    if _window_spans_backward_dst_transition(anchor, matched.window_hours, team):
        # Clocks going back give two bucket instants one local label, and the query returns
        # buckets by label, so a cache keyed by instant cannot tell them apart. Fall back to
        # full scans for as long as the fold sits inside the window.
        _capture_outcome(alert, "dst_fold_full_scan", window_hours=matched.window_hours)
        return None
    cached = _load_cached(team_id, alert.id, fingerprint, matched, anchor)
    if not cached or len(cached) < min_samples:
        # Even a perfect tail scan could not fill the detector's window from here.
        return rebuild("short_cache")

    state = _load_state(team_id, alert.id, fingerprint)
    if state is None:
        # Cached buckets without probe bookkeeping cannot prove they saw every late insert.
        return rebuild("no_watermark")
    if now - state.seeded_at >= timedelta(hours=RESEED_INTERVAL_HOURS):
        return rebuild("scheduled_reseed")
    if now - state.watermark >= timedelta(hours=_PROBE_HORIZON_HOURS):
        # events_recent only holds ~9 days; a watermark older than that could have missed
        # inserts the probe can no longer see.
        return rebuild("stale_watermark")

    window_start = anchor - timedelta(hours=matched.window_hours)
    probed = _changed_buckets(team, team_id, state.watermark, window_start, anchor)

    scan_set: set[datetime] = {anchor - timedelta(hours=back) for back in range(1, DEFAULT_MARGIN_HOURS + 1)}
    hour = max(cached) - timedelta(hours=_CLOCK_SKEW_HOURS)
    while hour < anchor:
        scan_set.add(hour)
        hour += timedelta(hours=1)
    if probed:
        scan_set.update(probed)
    scan_set = {bucket for bucket in scan_set if window_start <= bucket < anchor}
    if len(scan_set) >= matched.window_hours:
        return rebuild("wide_scan")

    scanned_rows, _ = run_query(query_override=matched.narrowed_to_buckets(sorted(scan_set), at=now, tz=team.timezone))
    scanned = _parse_rows(scanned_rows, team)
    if scanned is None:
        return rebuild("unparsable_tail")

    _write(
        team_id=team_id,
        alert_id=alert.id,
        fingerprint=fingerprint,
        scanned=scanned,
        authoritative_buckets=scan_set,
        prune_before=now - timedelta(hours=matched.window_hours + PRUNE_EXTRA_HOURS),
        # A failed probe leaves the watermark where it was, so the next check re-detects from
        # the same point instead of silently skipping the interval.
        watermark=None if probed is None else now - timedelta(hours=_CLOCK_SKEW_HOURS),
    )

    # Cached cells are stored as UTC instants, but the query returns team-local datetimes, and
    # the assembled rows must render exactly as a full scan's would.
    merged: _Buckets = {bucket: (bucket.astimezone(team.timezone_info), value) for bucket, value in cached.items()}
    for bucket in list(merged):
        if bucket in scan_set:
            del merged[bucket]
    merged.update(scanned)

    rows = _assemble(merged, matched, anchor)
    if len(rows) < min_samples:
        return rebuild("short_assembly")
    explicit_limit = get_query_limit(matched.parsed)
    if explicit_limit is not None and len(rows) >= explicit_limit:
        # Tail scans never trip the query's own LIMIT, so an assembly at it may hold rows a
        # full run would report as truncated. The full scan's completeness guard decides.
        return rebuild("beyond_limit")
    shadow = _shadow_compare(rows, matched, team, anchor, run_query)
    _capture_outcome(
        alert,
        "cache_hit",
        scanned_buckets=len(scan_set),
        probed_buckets=0 if probed is None else len(probed),
        probe_failed=probed is None,
        window_hours=matched.window_hours,
        **shadow,
    )
    return rows, matched.column_names


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
            # Bucket instants are read back through the team timezone, so a change re-aligns them.
            "timezone": team.timezone,
            # The query executes as the alert creator, and property access control masks values per
            # user, so a restriction change makes old and new buckets disagree.
            "restricted_properties": sorted(
                (r.name, str(r.property_type), -1 if r.group_type_index is None else r.group_type_index)
                for r in restricted
            ),
            # Effective modifiers change results without a SQL edit — persons-on-events mode is
            # flag-driven — and the retention floor silently narrows what a full scan reads. Both
            # sit in the HogQL cache key for the same reason.
            "hogql_modifiers": modifiers.model_dump(mode="json"),
            "events_retention_floor_months": events_retention_months_for_team(team, team.pk),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_cached(
    team_id: int, alert_id: Any, fingerprint: str, matched: DetectorSeriesQuery, anchor: datetime
) -> dict[datetime, float]:
    """Cached buckets still inside the window, at most ``window_hours`` of them, newest first.

    The cutoff is the window bound the query itself anchors on, so the cached set is exactly the
    full scan's. The newest-first slice caps the result at ``window_hours`` buckets, so even a
    clock straddling an hour boundary can only drop the extra oldest bucket — never keep one the
    full scan dropped.
    """
    rows = (
        _points(team_id, alert_id)
        .filter(fingerprint=fingerprint, bucket__gte=anchor - timedelta(hours=matched.window_hours))
        .order_by("-bucket")
        .values_list("bucket", "value")[: matched.window_hours]
    )
    return dict(rows)


def _hour_floor(now: datetime, team: Team) -> datetime:
    """The hour the query's toStartOfHour(now()) bounds anchor on, in the team timezone.

    The narrowed query pins its clock to the same ``now``, so the scan and the cache bookkeeping
    share one anchor by construction. HogQL evaluates now() in the team timezone, where a
    fractional-hour offset shifts the hour boundary off the UTC one.
    """
    local = now.astimezone(team.timezone_info)
    return local.replace(minute=0, second=0, microsecond=0).astimezone(UTC)


def _window_spans_backward_dst_transition(anchor: datetime, window_hours: int, team: Team) -> bool:
    offsets: list[timedelta] = []
    for hours in range(window_hours + 1, -1, -1):
        offset = (anchor - timedelta(hours=hours)).astimezone(team.timezone_info).utcoffset()
        offsets.append(offset if offset is not None else timedelta(0))
    return any(later < earlier for earlier, later in zip(offsets, offsets[1:]))


def _load_state(team_id: int, alert_id: Any, fingerprint: str) -> AlertSeriesState | None:
    """The alert's probe bookkeeping, or None when it is missing or describes another series."""
    state = AlertSeriesState.objects.for_team(team_id).filter(alert_config_id=alert_id).first()
    if state is None or state.fingerprint != fingerprint:
        return None
    return state


def _changed_buckets(
    team: Team, team_id: int, watermark: datetime, window_start: datetime, anchor: datetime
) -> list[datetime] | None:
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
                "tz": team.timezone,
                "team_id": team_id,
                "watermark": watermark,
                "window_start": window_start,
                "anchor": anchor,
            },
            team_id=team_id,
        )
    except Exception:
        return None
    return [_to_utc(bucket, team) for (bucket,) in rows]


def _parse_rows(rows: list, team: Team) -> _Buckets | None:
    """Index query rows by bucket instant, or None when a row is not a (bucket, value) pair."""
    parsed: _Buckets = {}
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
        parsed[_to_utc(bucket, team)] = (bucket, value)
    return parsed


def _to_utc(bucket: datetime, team: Team) -> datetime:
    if bucket.tzinfo is None:
        return bucket.replace(tzinfo=team.timezone_info).astimezone(UTC)
    return bucket.astimezone(UTC)


def _assemble(merged: _Buckets, matched: DetectorSeriesQuery, anchor: datetime) -> list[_Row]:
    in_window = [
        (bucket, cell, value)
        for bucket, (cell, value) in merged.items()
        if bucket >= anchor - timedelta(hours=matched.window_hours)
    ]
    in_window.sort(key=lambda item: item[0])
    return [[cell, value] for _, cell, value in in_window[-matched.window_hours :]]


def _write(
    *,
    team_id: int,
    alert_id: Any,
    fingerprint: str,
    scanned: _Buckets,
    authoritative_buckets: Iterable[datetime],
    prune_before: datetime,
    watermark: datetime | None = None,
    seeded_at: datetime | None = None,
) -> None:
    """Store what the scan read, drop what it proved gone, prune what aged out.

    A scanned bucket the scan did not return has no rows any more, so its cached value goes
    (never a zero — the full scan omits it too). The watermark advances in the same
    transaction as the buckets it vouches for: a crash re-detects, never skips.
    """
    with transaction.atomic():
        _points(team_id, alert_id).filter(bucket__lt=prune_before).delete()
        _points(team_id, alert_id).exclude(fingerprint=fingerprint).delete()
        _points(team_id, alert_id).filter(bucket__in=list(authoritative_buckets)).exclude(
            bucket__in=list(scanned)
        ).delete()
        if watermark is not None:
            updates: dict[str, Any] = {"fingerprint": fingerprint, "watermark": watermark, "team_id": team_id}
            if seeded_at is not None:
                updates["seeded_at"] = seeded_at
            AlertSeriesState.objects.for_team(team_id, canonical=True).update_or_create(
                alert_config_id=alert_id, defaults=updates
            )
        if scanned:
            AlertSeriesPoint.objects.for_team(team_id, canonical=True).bulk_create(
                [
                    AlertSeriesPoint(
                        team_id=team_id,
                        alert_config_id=alert_id,
                        bucket=bucket,
                        value=value,
                        fingerprint=fingerprint,
                    )
                    for bucket, (_, value) in scanned.items()
                ],
                update_conflicts=True,
                update_fields=["value", "fingerprint", "computed_at"],
                unique_fields=["alert_config", "bucket"],
            )


def _rebuild(
    *,
    alert: AlertConfiguration,
    team_id: int,
    matched: DetectorSeriesQuery,
    fingerprint: str,
    run_query: RunQuery,
    now: datetime,
) -> tuple[list[_Row], list[str]]:
    """Run the query in full, replace the cache with what it returned, and hand back its rows."""
    rows, column_names = run_query(query_override=matched.prepared(at=now, tz=alert.team.timezone))
    parsed = _parse_rows(rows, alert.team)
    if parsed is not None:
        anchor = _hour_floor(now, alert.team)
        window = [anchor - timedelta(hours=back) for back in range(1, matched.window_hours + 1)]
        _write(
            team_id=team_id,
            alert_id=alert.id,
            fingerprint=fingerprint,
            scanned=parsed,
            authoritative_buckets=window,
            prune_before=now - timedelta(hours=matched.window_hours + PRUNE_EXTRA_HOURS),
            watermark=now - timedelta(hours=_CLOCK_SKEW_HOURS),
            seeded_at=now,
        )
    return rows, column_names or matched.column_names
