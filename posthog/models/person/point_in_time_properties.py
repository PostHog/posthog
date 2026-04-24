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
DEFAULT_LOWER_BOUND_WINDOW = timedelta(days=365 * 2)


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

    # Person.distinct_ids is an @property that returns the personhog-hydrated
    # cache when present and otherwise falls back to a DB query, so we can rely
    # on it directly.
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
    lower_bound: Optional[datetime] = None,
    row_limit: int = DEFAULT_PROPERTY_ROW_LIMIT,
) -> tuple[dict[str, Any], bool]:
    """
    Build person properties at a specific point in time and check whether the
    person had any events at or before that time, in a single ClickHouse round trip.

    Args:
        team_id: The team ID to filter events by
        timestamp: The point in time to build properties at (events after this are ignored)
        distinct_ids: List of distinct_ids to query for person properties
        include_set_once: If True, also handles $set_once operations (default: False)
        timeout: Query timeout in seconds (default: 30)
        lower_bound: Oldest timestamp to scan. Defaults to ``timestamp - 2 years``.
            Callers with tighter knowledge (e.g. flag creation time) should pass a
            stricter bound to keep the ClickHouse scan small.
        row_limit: Maximum property update rows to ship back from ClickHouse (default 100_000).

    Returns:
        Tuple of ``(person_properties, person_existed)``. ``person_existed`` is True
        when any event exists for the distinct_ids at or before ``timestamp``.

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

    effective_lower_bound = lower_bound if lower_bound is not None else timestamp - DEFAULT_LOWER_BOUND_WINDOW

    if effective_lower_bound > timestamp:
        raise ValueError("lower_bound must not be after timestamp")

    if include_set_once:
        event_filter = "event IN ('$set', '$set_once') OR JSONHas(properties, '$set')"
    else:
        event_filter = "event = '$set' OR JSONHas(properties, '$set')"

    # UNION ALL folds the property query and a LIMIT 1 existence probe into a
    # single ClickHouse round trip. Columns must line up across both sub-selects.
    # kind=1 -> property update row; kind=0 -> existence probe row.
    query = f"""
    SELECT kind, set_json, set_once_json, event_name FROM (
        SELECT
            1 AS kind,
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
    )
    UNION ALL
    SELECT kind, set_json, set_once_json, event_name FROM (
        SELECT
            0 AS kind,
            '' AS set_json,
            '' AS set_once_json,
            '' AS event_name
        FROM events
        WHERE team_id = %(team_id)s
            AND distinct_id IN %(distinct_ids)s
            AND timestamp <= %(upper_bound)s
        LIMIT 1
    )
    """

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
    existed = False

    for row in rows:
        kind, set_json, set_once_json, event_name = row

        # Both property rows and the existence probe row signal that the person
        # had activity at or before the timestamp.
        existed = True

        if kind == 0:
            continue

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

    return person_properties, existed
