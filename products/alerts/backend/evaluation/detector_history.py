"""Serve a SQL detector alert's older history from cached hourly buckets.

A detector needs its whole window of bucketed values on every check, and every bucket except the
most recent few is a closed hour whose value the previous check already computed. This module
keeps those values and narrows each check's scan to the recent tail.

Every step falls back to the full scan rather than guessing: an unrecognized query, a changed
query, a gap the cache cannot prove it covers, or too few points for the detector all lead back
to today's behavior, and the cache is rebuilt from that scan.
"""

import json
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone as django_timezone

from posthog.schema import HogQLAlertConfig, HogQLAlertEvaluation, HogQLQueryModifiers

from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.team.event_retention import events_retention_months_for_team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.alerts.backend.evaluation.detector_history_eligibility import (
    DetectorSeriesQuery,
    match_detector_series_query,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.models.alert_series_point import AlertSeriesPoint
from products.product_analytics.backend.facade.models import Insight

INCREMENTAL_DETECTOR_HISTORY_FLAG = "alerts-incremental-detector-history"

# How far back every check re-reads, so an event that arrives late still reaches its bucket.
DEFAULT_MARGIN_HOURS = 3
# Buckets older than the window plus this are dropped on write, so the table stays a fixed size
# per alert while leaving headroom for a window that grows.
PRUNE_EXTRA_HOURS = 48

# The app clock and the ClickHouse clock can disagree. An hour of headroom on the narrowed scan
# means a disagreement makes that scan slightly wider, never leaves a bucket unread.
_CLOCK_SKEW_HOURS = 1

# One result row: the bucket cell as the query returned it, then the value.
_Row = list[Any]
# Bucket instant in UTC -> (bucket cell as returned, value).
_Buckets = dict[datetime, tuple[Any, float]]
RunQuery = Callable[..., tuple[list, list[str] | None]]


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
        return None
    matched = match_detector_series_query(insight.query, column=config.column)
    if matched is None:
        return None

    team_id = resolve_effective_team_id(alert.team_id)
    fingerprint = _fingerprint(matched, config, team, alert.created_by)
    now = django_timezone.now()

    def rebuild() -> tuple[list[_Row], list[str]]:
        return _rebuild(
            alert=alert,
            team_id=team_id,
            matched=matched,
            fingerprint=fingerprint,
            run_query=run_query,
            now=now,
        )

    anchor = _hour_floor(now, team)
    cached = _load_cached(team_id, alert.id, fingerprint, matched, anchor)
    if not cached or len(cached) < min_samples:
        # Even a perfect tail scan could not fill the detector's window from here.
        return rebuild()

    scan_hours = _scan_hours(cached, now)
    if scan_hours >= matched.window_hours:
        return rebuild()

    scanned_rows, _ = run_query(query_override=matched.narrowed_to(scan_hours, at=now, tz=team.timezone))
    scanned = _parse_rows(scanned_rows, team)
    if scanned is None:
        return rebuild()

    authoritative_from = anchor - timedelta(hours=scan_hours)
    _write(
        team_id=team_id,
        alert_id=alert.id,
        fingerprint=fingerprint,
        scanned=scanned,
        authoritative_from=authoritative_from,
        prune_before=now - timedelta(hours=matched.window_hours + PRUNE_EXTRA_HOURS),
    )

    merged: _Buckets = {bucket: (bucket, value) for bucket, value in cached.items()}
    for bucket in list(merged):
        if bucket >= authoritative_from:
            del merged[bucket]
    merged.update(scanned)

    rows = _assemble(merged, matched, anchor)
    if len(rows) < min_samples:
        return rebuild()
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


def _scan_hours(cached: dict[datetime, float], now: datetime) -> int:
    """How far back this check must read to join up with what the cache already holds.

    The newest cached bucket is the only point the cache can prove it has read up to, so a check
    that never ran, or one that ran and found nothing, simply widens the next scan.
    """
    gap_hours = -(-int((now - max(cached)).total_seconds()) // 3600)
    return max(DEFAULT_MARGIN_HOURS, gap_hours + _CLOCK_SKEW_HOURS)


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
    authoritative_from: datetime,
    prune_before: datetime,
) -> None:
    """Store what the scan read, drop what it proved is gone, and prune what aged out.

    ``authoritative_from`` is the bound the scan actually reached back to, so a bucket after it
    that the scan did not return holds no rows any more and its cached value has to go. A bucket with no rows is never written as a zero — it is a bucket with no row here,
    which is what the full scan reports too.
    """
    with transaction.atomic():
        _points(team_id, alert_id).filter(bucket__lt=prune_before).delete()
        _points(team_id, alert_id).exclude(fingerprint=fingerprint).delete()
        _points(team_id, alert_id).filter(bucket__gte=authoritative_from).exclude(bucket__in=list(scanned)).delete()
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
        _write(
            team_id=team_id,
            alert_id=alert.id,
            fingerprint=fingerprint,
            scanned=parsed,
            authoritative_from=_hour_floor(now, alert.team) - timedelta(hours=matched.window_hours),
            prune_before=now - timedelta(hours=matched.window_hours + PRUNE_EXTRA_HOURS),
        )
    return rows, column_names or matched.column_names
