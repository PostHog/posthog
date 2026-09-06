"""
Module for building person properties from ClickHouse events at a specific point in time.

This module provides functionality to reconstruct person properties as they existed
at a specific timestamp by querying ClickHouse events and applying property updates
chronologically.
"""

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query

if TYPE_CHECKING:
    from posthog.models.person import Person
    from posthog.models.team import Team


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

    from posthog.models.person.util import get_person_by_uuid, get_persons_by_distinct_ids
    from posthog.personhog_client.caller_tag import personhog_caller_tag

    # The returned distinct_ids are consumed in full by callers — the point-in-time API echoes them
    # back with an exact count, and flag evaluation picks a deterministic (lexicographically smallest)
    # distinct_id — so the fetch is intentionally unbounded here, only tagged for attribution.
    if distinct_id is not None:
        # Plural lookup: index-friendly __in query that also prefetches distinct_ids_cache,
        # which the person.distinct_ids return below relies on. The singular
        # get_person_by_distinct_id times out on large teams.
        with personhog_caller_tag("persons/point-in-time"):
            persons = get_persons_by_distinct_ids(team_id, [distinct_id])
        person = persons[0] if persons else None
    else:
        assert person_id is not None
        with personhog_caller_tag("persons/point-in-time"):
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


def _validate_build_inputs(timestamp: datetime, distinct_ids: list[str], row_limit: int) -> None:
    if not isinstance(timestamp, datetime):
        raise ValueError("timestamp must be a datetime object")

    if not isinstance(distinct_ids, list) or not distinct_ids:
        raise ValueError("distinct_ids must be a non-empty list")

    if not all(isinstance(did, str) and did for did in distinct_ids):
        raise ValueError("All distinct_ids must be non-empty strings")

    if not isinstance(row_limit, int) or row_limit <= 0:
        raise ValueError("row_limit must be a positive integer")


def _parse_property_json(raw: Any) -> Optional[dict]:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _reconstruct_properties(rows: list, include_set_once: bool) -> dict[str, Any]:
    person_properties: dict[str, Any] = {}

    for row in rows:
        set_json, set_once_json, event_name = row

        if set_json:
            set_properties = _parse_property_json(set_json)
            if set_properties is not None:
                person_properties.update(set_properties)

        # $set_once semantics only apply to dedicated $set_once events.
        if include_set_once and event_name == "$set_once" and set_once_json:
            set_once_properties = _parse_property_json(set_once_json)
            if set_once_properties is not None:
                for key, value in set_once_properties.items():
                    if key not in person_properties:
                        person_properties[key] = value

    return person_properties


def build_person_properties_at_time(
    team: "Team",
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
        team: The team whose events are scanned
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
    """
    _validate_build_inputs(timestamp, distinct_ids, row_limit)

    if include_set_once:
        event_filter = "event IN ('$set', '$set_once') OR JSONHas(properties, '$set')"
    else:
        event_filter = "event = '$set' OR JSONHas(properties, '$set')"

    # Use provided lower_bound or default to timestamp - 2 years
    effective_lower_bound = lower_bound if lower_bound is not None else timestamp - _HISTORY_SCAN_FLOOR

    # Pulls every property-update event in the window. Existence is established
    # upstream by get_person_and_distinct_ids_for_identifier (Postgres row);
    # ``existed`` here means "had property activity in the scan window", which
    # the property row count answers directly. We extract $set / $set_once raw
    # JSON instead of shipping the full properties blob, and the timestamp
    # window + LIMIT keeps ClickHouse from walking dead partitions.
    response = execute_hogql_query(
        """
        SELECT
            JSONExtractRaw(properties, '$set') AS set_json,
            JSONExtractRaw(properties, '$set_once') AS set_once_json,
            event AS event_name
        FROM events
        WHERE distinct_id IN {distinct_ids}
            AND timestamp >= {lower_bound}
            AND timestamp <= {upper_bound}
            AND ({event_filter})
        ORDER BY timestamp ASC
        LIMIT {row_limit}
        """,
        placeholders={
            "distinct_ids": ast.Constant(value=distinct_ids),
            "lower_bound": ast.Constant(value=effective_lower_bound),
            "upper_bound": ast.Constant(value=timestamp),
            "event_filter": parse_expr(event_filter),
            "row_limit": ast.Constant(value=row_limit),
        },
        team=team,
        query_type="person_properties_at_time",
        settings=HogQLGlobalSettings(max_execution_time=timeout),
        # row_limit is the only LIMIT this scan wants. The default context caps a top-level LIMIT at
        # MAX_SELECT_RETURNED_ROWS, which would silently truncate the default row_limit, and every
        # limit context with a larger cap also overrides max_execution_time.
        #
        # The scan must not stop at the plan's events retention floor. Ingestion applies every $set to the
        # person profile regardless of retention, so a floored scan rebuilds a profile that never existed and
        # drops every property set before the window. The scan reconstructs person state. It does not expose
        # events past the floor.
        context=HogQLContext(team_id=team.pk, limit_top_select=False, apply_events_retention_floor=False),
    )

    return _reconstruct_properties(response.results, include_set_once)
