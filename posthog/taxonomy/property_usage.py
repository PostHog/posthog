"""30-day query counts per property, kept as one cached map per project.

The property list, its usage sort and the property detail page all read this map, so they always
show the same number. A request serves the cached map and, when it is older than
`USAGE_MAP_STALE_AFTER`, queues one background rebuild.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from django.utils import timezone

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.event_usage import PROPERTY_USAGE_APP_SOURCE, property_usage_instance_id
from posthog.models import Team
from posthog.tasks.property_usage import refresh_property_usage_map
from posthog.taxonomy.property_snapshot_cache import PropertySnapshotCache

logger = structlog.get_logger(__name__)

USAGE_WINDOW_DAYS = 30
USAGE_MAP_STALE_AFTER = timedelta(minutes=15)
USAGE_MAP_CACHE = PropertySnapshotCache(
    name="usage_map",
    format_version=1,
    stale_after=USAGE_MAP_STALE_AFTER,
    ttl=timedelta(hours=24),
    rebuild_marker_ttl=timedelta(minutes=10),
)


@frozen
class PropertyUsageMap:
    """Query counts of the last 30 days, keyed by the app_metrics2 instance id of each property.

    Only properties with at least one query are in `counts`.
    """

    counts: Mapping[str, int]
    computed_at: datetime
    # The first logged property usage when tracking started inside the window, else None.
    # When it is set, the counts cover less than 30 days.
    tracking_since: datetime | None

    def count_for(self, property_type: str, name: str, group_type_index: int | None = None) -> int:
        return self.counts.get(property_usage_instance_id(property_type, name, group_type_index), 0)

    def counts_by_name(self, property_type: str, group_type_index: int | None = None) -> dict[str, int]:
        """The used properties of one type (and group type), keyed by property name."""
        prefix = property_usage_instance_id(property_type, "", group_type_index)
        return {
            instance_id[len(prefix) :]: count
            for instance_id, count in self.counts.items()
            if instance_id.startswith(prefix)
        }


def is_stale(usage_map: PropertyUsageMap, now: datetime) -> bool:
    return now - usage_map.computed_at > USAGE_MAP_STALE_AFTER


def _encode(usage_map: PropertyUsageMap) -> dict[str, Any]:
    return {
        "counts": dict(usage_map.counts),
        "computed_at": usage_map.computed_at.isoformat(),
        "tracking_since": usage_map.tracking_since.isoformat() if usage_map.tracking_since else None,
    }


def _decode(payload: dict[str, Any]) -> PropertyUsageMap:
    return PropertyUsageMap(
        counts=payload["counts"],
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        tracking_since=datetime.fromisoformat(payload["tracking_since"]) if payload["tracking_since"] else None,
    )


def _read_cached(team_id: int) -> PropertyUsageMap | None:
    payload = USAGE_MAP_CACHE.read(str(team_id))
    if payload is None:
        return None
    try:
        return _decode(payload)
    except (ValueError, KeyError, TypeError):
        logger.warning("property_usage_map_unreadable", team_id=team_id)
        return None


def fetch_property_usage_map(team: Team, workload: Workload) -> PropertyUsageMap:
    """Run the ClickHouse query for one project. The caller picks the workload for its context."""
    tag_queries(product=Product.PRODUCT_ANALYTICS, feature=Feature.PROPERTY_DEFINITION_SCENE)
    computed_at = timezone.now().astimezone(UTC)
    window_start = computed_at - timedelta(days=USAGE_WINDOW_DAYS)
    # One extra day before the window tells whether tracking started before the window.
    # Rows from that day only feed `first_seen`, never the counts.
    lookback_start = window_start - timedelta(days=1)
    rows = sync_execute(
        """
        SELECT instance_id, sumIf(count, timestamp >= toDateTime64(%(window_start)s, 6)), min(timestamp)
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = %(app_source)s
          AND metric_name = %(metric_name)s
          AND timestamp >= toDateTime64(%(lookback_start)s, 6)
        GROUP BY instance_id
        """,
        {
            "team_id": team.pk,
            "app_source": PROPERTY_USAGE_APP_SOURCE,
            "metric_name": "viewed",
            "window_start": window_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "lookback_start": lookback_start.strftime("%Y-%m-%dT%H:%M:%S"),
        },
        workload=workload,
        team_id=team.pk,
    )
    counts: dict[str, int] = {}
    first_seen: datetime | None = None
    for instance_id, total, seen_at in rows or []:
        if total > 0:
            counts[instance_id] = int(total)
        seen_at = seen_at if seen_at.tzinfo else seen_at.replace(tzinfo=UTC)
        first_seen = seen_at if first_seen is None else min(first_seen, seen_at)
    tracking_since = first_seen if first_seen is not None and first_seen >= window_start else None
    return PropertyUsageMap(counts=counts, computed_at=computed_at, tracking_since=tracking_since)


def rebuild_property_usage_map(team: Team, workload: Workload) -> PropertyUsageMap:
    usage_map = fetch_property_usage_map(team, workload)
    USAGE_MAP_CACHE.write(str(team.pk), _encode(usage_map))
    return usage_map


def rebuild_property_usage_map_in_background(team_id: int) -> None:
    """The body of the Celery task. It clears the rebuild marker, also when the query fails."""
    try:
        team = Team.objects.get(pk=team_id)
        rebuild_property_usage_map(team, Workload.OFFLINE)
    finally:
        USAGE_MAP_CACHE.release_rebuild(str(team_id))


def get_property_usage_map(team: Team) -> PropertyUsageMap:
    """Serve the cached map, and queue a rebuild when it is stale. Build inline only when none is cached."""
    usage_map = _read_cached(team.pk)
    if usage_map is None:
        # A person waits for the list or the detail page.
        return rebuild_property_usage_map(team, Workload.ONLINE)
    if is_stale(usage_map, timezone.now()) and USAGE_MAP_CACHE.claim_rebuild(str(team.pk)):
        refresh_property_usage_map.delay(team.pk)
    return usage_map
