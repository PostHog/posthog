"""
Module for building person properties from ClickHouse events at a specific point in time.

This module provides functionality to reconstruct person properties as they existed
at a specific timestamp by querying ClickHouse events and applying property updates
chronologically.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from posthog.clickhouse.client import sync_execute

if TYPE_CHECKING:
    from posthog.models.person import Person


DEFAULT_PROPERTY_ROW_LIMIT = 100_000

# Hard floor on how far back the property scan walks. Anything older is almost
# certainly past retention anyway; bounding here saves ClickHouse from walking
# dead partitions when ``timestamp`` is the only bound (worst case: a brand-new
# distinct_id with no matching events on a team with multi-year retention).
_HISTORY_SCAN_FLOOR = timedelta(days=365 * 2)


def get_person_and_distinct_ids_for_identifier(
    team_id: int,
    distinct_id: Optional[str] = None,
    person_id: Optional[str] = None,
) -> tuple[Optional["Person"], list[str]]:
    """
    Helper function to get person object and all distinct_ids for a person based on either distinct_id or person_id.

    Args:
        team_id: The team ID
        distinct_id: A distinct_id belonging to the person (mutually exclusive with person_id)
        person_id: The person_id (UUID) to get distinct_ids for (mutually exclusive with distinct_id)

    Returns:
        Tuple of (Person object or None, list of distinct_ids associated with the person)

    Raises:
        ValueError: If parameters are invalid or both distinct_id and person_id are provided
        Exception: If person lookup fails
    """
    # Validation
    if distinct_id is not None and person_id is not None:
        raise ValueError("Cannot provide both distinct_id and person_id - choose one")

    if distinct_id is None and person_id is None:
        raise ValueError("Must provide either distinct_id or person_id")

    if distinct_id is not None and (not distinct_id or not isinstance(distinct_id, str)):
        raise ValueError("distinct_id must be a non-empty string")

    if person_id is not None and not person_id:
        raise ValueError("person_id must be a non-empty value")

    from posthog.models.person.util import get_person_by_distinct_id, get_person_by_uuid

    if distinct_id is not None:
        person = get_person_by_distinct_id(team_id, distinct_id)
    else:
        assert person_id is not None
        person = get_person_by_uuid(team_id, person_id)

    if person is None:
        return None, []

    # Person.distinct_ids returns the in-memory cache when populated (e.g. by
    # the personhog client wrapper around posthog/personhog_client/) and
    # otherwise falls back to a DB query, so we can rely on it directly.
    return person, person.distinct_ids


def get_distinct_ids_for_person_identifier(
    team_id: int,
    distinct_id: Optional[str] = None,
    person_id: Optional[str] = None,
) -> list[str]:
    """
    Legacy helper function that returns only distinct_ids.

    This is kept for backwards compatibility. New code should use
    get_person_and_distinct_ids_for_identifier() to avoid duplicate queries.
    """
    _, distinct_ids = get_person_and_distinct_ids_for_identifier(team_id, distinct_id, person_id)
    return distinct_ids


def build_person_properties_at_time(
    team_id: int,
    timestamp: datetime,
    distinct_ids: list[str],
    include_set_once: bool = False,
    timeout: Optional[int] = 30,
    row_limit: int = DEFAULT_PROPERTY_ROW_LIMIT,
    lower_bound: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Build person properties at a specific point in time from ClickHouse events.

    Args:
        team_id: The team ID to filter events by
        timestamp: The point in time to build properties at (events after this are ignored)
        distinct_ids: List of distinct_ids to query for person properties
        include_set_once: If True, also handles $set_once operations (default: False)
        timeout: Query timeout in seconds (default: 30)
        row_limit: Maximum property update rows to ship back from ClickHouse (default 100_000).
        lower_bound: Optional lower bound for the time range scan. If not provided, defaults to timestamp - 2 years.

    Returns:
        Dict containing person properties as they existed at the specified timestamp.

    Raises:
        ValueError: If parameters are invalid
        Exception: If ClickHouse query fails
    """
    # Validation
    if not isinstance(team_id, int) or team_id <= 0:
        raise ValueError("team_id must be a positive integer")

    if not isinstance(timestamp, datetime):
        raise ValueError("timestamp must be a datetime object")

    if not isinstance(distinct_ids, list) or not distinct_ids:
        raise ValueError("distinct_ids must be a non-empty list")

    if not all(isinstance(did, str) and did for did in distinct_ids):
        raise ValueError("All distinct_ids must be non-empty strings")

    if not isinstance(row_limit, int) or row_limit <= 0:
        raise ValueError("row_limit must be a positive integer")

    if include_set_once:
        event_filter = "event IN ('$set', '$set_once') OR JSONHas(properties, '$set')"
    else:
        event_filter = "event = '$set' OR JSONHas(properties, '$set')"

    # Pulls every property-update event in the window. Existence is established
    # upstream by get_person_and_distinct_ids_for_identifier (Postgres row);
    # ``existed`` here means "had property activity in the scan window", which
    # the property row count answers directly. We extract $set / $set_once raw
    # JSON instead of shipping the full properties blob, and the timestamp
    # window + LIMIT keeps ClickHouse from walking dead partitions.
    query = f"""
    SELECT
        JSONExtractRaw(properties, '$set') AS set_json,
        JSONExtractRaw(properties, '$set_once') AS set_once_json,
        event AS event_name
    FROM events
    WHERE team_id = %(team_id)s
        AND distinct_id IN %(distinct_ids)s
        AND timestamp >= %(lower_bound)s
        AND timestamp <= %(upper_bound)s
        AND ({event_filter})
    ORDER BY timestamp ASC
    LIMIT {int(row_limit)}
    """

    # Use provided lower_bound or default to timestamp - 2 years
    effective_lower_bound = lower_bound if lower_bound is not None else timestamp - _HISTORY_SCAN_FLOOR

    params = {
        "team_id": team_id,
        "distinct_ids": distinct_ids,
        "lower_bound": effective_lower_bound.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "upper_bound": timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        rows = sync_execute(query, params, settings={"max_execution_time": timeout})
    except Exception as e:
        raise Exception(f"Failed to query ClickHouse events: {str(e)}") from e

    person_properties: dict[str, Any] = {}

    for row in rows:
        set_json, set_once_json, event_name = row

        if set_json:
            try:
                set_properties = json.loads(set_json)
            except (json.JSONDecodeError, TypeError):
                set_properties = None

            if isinstance(set_properties, dict):
                person_properties.update(set_properties)

        # $set_once semantics only apply to dedicated $set_once events.
        if include_set_once and event_name == "$set_once" and set_once_json:
            try:
                set_once_properties = json.loads(set_once_json)
            except (json.JSONDecodeError, TypeError):
                set_once_properties = None

            if isinstance(set_once_properties, dict):
                for key, value in set_once_properties.items():
                    if key not in person_properties:
                        person_properties[key] = value

    return person_properties
