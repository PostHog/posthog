"""When each property was last sent, kept as one cached snapshot per project and property type.

The dates come from the ClickHouse `property_values` table, which the property-values service
(rust/property-vals-rs) fills from ingested events and group identifies. Each (key, value) row keeps
the time it was last seen and expires 30 days after that. The service writes each row at most once a
day, so a date is precise to the day only.

The rollup reads every value of every key of the type, so it never runs inside a request. A request
serves the cached snapshot. When there is none, or it is stale, the request queues one Celery rebuild.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db.models import TextChoices
from django.utils import timezone

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.tasks.property_usage import refresh_property_last_sent_map
from posthog.taxonomy.property_snapshot_cache import PropertySnapshotCache

from products.event_definitions.backend.models import PropertyDefinition

logger = structlog.get_logger(__name__)

LAST_SENT_WINDOW_DAYS = 30
# The dates are precise to the day, so a fresher snapshot shows nothing new.
LAST_SENT_MAP_STALE_AFTER = timedelta(hours=1)
LAST_SENT_MAP_CACHE = PropertySnapshotCache(
    name="last_sent_map",
    format_version=1,
    stale_after=LAST_SENT_MAP_STALE_AFTER,
    ttl=timedelta(hours=24),
    rebuild_marker_ttl=timedelta(minutes=10),
)
# Above this many keys of one type the snapshot keeps no dates, so it stays small enough for Redis.
MAX_KEYS_PER_SNAPSHOT = 100_000

# Keep in sync with EXCLUDED_PROPERTY_KEYS of the property-values service. Its deployment config sets
# the value, and rust/property-vals-rs/src/config.rs parses it. The service never records these keys,
# so a missing row says nothing about when they were last sent.
SERVICE_EXCLUDED_PROPERTY_KEYS = frozenset(
    {"$insert_id", "$sent_at", "$feature_flag_request_id", "$time", "$feature_flag_evaluated_at"}
)
SERVICE_EXCLUDED_PROPERTY_KEY_PREFIXES = ("$feature/",)
# The service drops longer keys. Keep in sync with MAX_PROPERTY_KEY_LEN in rust/property-vals-rs/src/config.rs.
SERVICE_MAX_PROPERTY_KEY_LENGTH = 400
VIRTUAL_PROPERTY_PREFIX = "$virt_"
COLUMN_BACKED_GROUP_PROPERTIES = frozenset({"$group_key"})


class PropertyLastSentStatus(TextChoices):
    SENT = "sent", "Sent in the last 30 days"
    NOT_SENT_IN_30_DAYS = "not_sent_in_30_days", "Not sent in the last 30 days"
    NOT_TRACKED = "not_tracked", "Not tracked"


@frozen
class PropertyLastSent:
    status: PropertyLastSentStatus
    at: datetime | None = None


NOT_TRACKED = PropertyLastSent(status=PropertyLastSentStatus.NOT_TRACKED)


@frozen
class PropertyLastSentMap:
    """The last-sent time of each key of one property type that was sent in the last 30 days."""

    property_type: str
    last_sent: Mapping[str, datetime]
    computed_at: datetime
    # False when the project has no row at all, for example when the service does not process it.
    # Then an absent key is not evidence that the property was not sent.
    has_data: bool
    too_many_keys: bool

    def last_sent_for(self, name: str) -> PropertyLastSent:
        if not self.has_data or self.too_many_keys:
            return NOT_TRACKED
        at = self.last_sent.get(name)
        if at is None:
            return PropertyLastSent(status=PropertyLastSentStatus.NOT_SENT_IN_30_DAYS)
        return PropertyLastSent(status=PropertyLastSentStatus.SENT, at=at)


def snapshot_property_type(definition_type: int, group_type_index: int | None) -> str | None:
    """The `property_type` of the `property_values` rows for a definition type, or None when it has no rows."""
    if definition_type == PropertyDefinition.Type.EVENT:
        return "event"
    if definition_type == PropertyDefinition.Type.PERSON:
        return "person"
    if definition_type == PropertyDefinition.Type.GROUP and group_type_index is not None:
        return f"group_{group_type_index}"
    return None


def is_last_sent_tracked(definition: PropertyDefinition) -> bool:
    if snapshot_property_type(definition.type, definition.group_type_index) is None:
        return False
    name = definition.name
    if (
        name in SERVICE_EXCLUDED_PROPERTY_KEYS
        or name.startswith(SERVICE_EXCLUDED_PROPERTY_KEY_PREFIXES)
        or len(name) > SERVICE_MAX_PROPERTY_KEY_LENGTH
        or name.startswith(VIRTUAL_PROPERTY_PREFIX)
    ):
        return False
    if definition.type == PropertyDefinition.Type.GROUP and name in COLUMN_BACKED_GROUP_PROPERTIES:
        return False
    # A data warehouse sync writes these person properties, so no event has to carry them.
    return definition.warehouse_origin is None


def is_stale(last_sent_map: PropertyLastSentMap, now: datetime) -> bool:
    return now - last_sent_map.computed_at > LAST_SENT_MAP_STALE_AFTER


def _scope(team_id: int, property_type: str) -> str:
    return f"{team_id}:{property_type}"


def _encode(last_sent_map: PropertyLastSentMap) -> dict[str, Any]:
    return {
        "property_type": last_sent_map.property_type,
        "last_sent": {key: int(at.timestamp()) for key, at in last_sent_map.last_sent.items()},
        "computed_at": last_sent_map.computed_at.isoformat(),
        "has_data": last_sent_map.has_data,
        "too_many_keys": last_sent_map.too_many_keys,
    }


def _decode(payload: dict[str, Any]) -> PropertyLastSentMap:
    return PropertyLastSentMap(
        property_type=payload["property_type"],
        last_sent={key: datetime.fromtimestamp(seconds, tz=UTC) for key, seconds in payload["last_sent"].items()},
        computed_at=datetime.fromisoformat(payload["computed_at"]),
        has_data=payload["has_data"],
        too_many_keys=payload["too_many_keys"],
    )


def _read_cached(team_id: int, property_type: str) -> PropertyLastSentMap | None:
    payload = LAST_SENT_MAP_CACHE.read(_scope(team_id, property_type))
    if payload is None:
        return None
    try:
        return _decode(payload)
    except (ValueError, KeyError, TypeError, AttributeError):
        logger.warning("property_last_sent_map_unreadable", team_id=team_id, property_type=property_type)
        return None


def fetch_property_last_sent_map(team: Team, property_type: str, workload: Workload) -> PropertyLastSentMap:
    tag_queries(product=Product.PRODUCT_ANALYTICS, feature=Feature.PROPERTY_DEFINITION_SCENE)
    computed_at = timezone.now().astimezone(UTC)
    window_start = computed_at - timedelta(days=LAST_SENT_WINDOW_DAYS)
    # The 30-day TTL deletes rows only when parts merge, so older rows can remain. The filter keeps
    # every date inside the window.
    rows = sync_execute(
        """
        SELECT property_key, max(last_seen)
        FROM property_values_distributed
        WHERE team_id = %(team_id)s
          AND property_type = %(property_type)s
          AND last_seen >= toDateTime(%(window_start)s, 'UTC')
        GROUP BY property_key
        LIMIT %(key_limit)s
        """,
        {
            "team_id": team.pk,
            "property_type": property_type,
            "window_start": window_start.strftime("%Y-%m-%d %H:%M:%S"),
            "key_limit": MAX_KEYS_PER_SNAPSHOT + 1,
        },
        workload=workload,
        team_id=team.pk,
    )
    rows = rows or []
    too_many_keys = len(rows) > MAX_KEYS_PER_SNAPSHOT
    last_sent: dict[str, datetime] = {}
    if not too_many_keys:
        for key, seen_at in rows:
            last_sent[key] = seen_at if seen_at.tzinfo else seen_at.replace(tzinfo=UTC)
    has_data = bool(rows) or _team_has_property_values(team, workload)
    return PropertyLastSentMap(
        property_type=property_type,
        last_sent=last_sent,
        computed_at=computed_at,
        has_data=has_data,
        too_many_keys=too_many_keys,
    )


def _team_has_property_values(team: Team, workload: Workload) -> bool:
    rows = sync_execute(
        "SELECT 1 FROM property_values_distributed WHERE team_id = %(team_id)s LIMIT 1",
        {"team_id": team.pk},
        workload=workload,
        team_id=team.pk,
    )
    return bool(rows)


def rebuild_property_last_sent_map(team: Team, property_type: str, workload: Workload) -> PropertyLastSentMap:
    last_sent_map = fetch_property_last_sent_map(team, property_type, workload)
    LAST_SENT_MAP_CACHE.write(_scope(team.pk, property_type), _encode(last_sent_map))
    return last_sent_map


def rebuild_property_last_sent_map_in_background(team_id: int, property_type: str) -> None:
    """The body of the Celery task. It clears the rebuild marker, also when the query fails."""
    try:
        team = Team.objects.get(pk=team_id)
        rebuild_property_last_sent_map(team, property_type, Workload.OFFLINE)
    finally:
        LAST_SENT_MAP_CACHE.release_rebuild(_scope(team_id, property_type))


def get_property_last_sent_map(team: Team, property_type: str) -> PropertyLastSentMap | None:
    """Serve the cached snapshot, and queue a rebuild when it is missing or stale.

    Returns None while the first snapshot of the type is being built.
    """
    last_sent_map = _read_cached(team.pk, property_type)
    needs_rebuild = last_sent_map is None or is_stale(last_sent_map, timezone.now())
    if needs_rebuild and LAST_SENT_MAP_CACHE.claim_rebuild(_scope(team.pk, property_type)):
        refresh_property_last_sent_map.delay(team.pk, property_type)
    return last_sent_map
