"""
Module for building person properties from ClickHouse events at a specific point in time.

This module provides functionality to reconstruct person properties as they existed
at a specific timestamp by querying ClickHouse events and applying property updates
chronologically.
"""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional, Union

from posthog.clickhouse.client import sync_execute

if TYPE_CHECKING:
    from posthog.models.person import Person


def get_person_and_distinct_ids_for_identifier(
    team_id: int,
    distinct_id: Optional[str] = None,
    person_id: Optional[Union[str, int]] = None,
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
    from posthog.models.person import Person, PersonDistinctId

    # Validation
    if distinct_id is not None and person_id is not None:
        raise ValueError("Cannot provide both distinct_id and person_id - choose one")

    if distinct_id is None and person_id is None:
        raise ValueError("Must provide either distinct_id or person_id")

    if distinct_id is not None and (not distinct_id or not isinstance(distinct_id, str)):
        raise ValueError("distinct_id must be a non-empty string")

    if person_id is not None and not person_id:
        raise ValueError("person_id must be a non-empty value")

    try:
        if distinct_id is not None:
            # Get the person that this distinct_id belongs to
            person = Person.objects.get(team_id=team_id, persondistinctid__distinct_id=distinct_id)
        else:
            # Get the person by UUID
            person = Person.objects.get(team_id=team_id, uuid=str(person_id))

        # Now get ALL distinct_ids for this person
        distinct_id_objects = PersonDistinctId.objects.filter(team_id=team_id, person=person).values_list(
            "distinct_id", flat=True
        )
        return person, list(distinct_id_objects)

    except Person.DoesNotExist:
        # Person not found - return None and empty list
        return None, []
    except Exception as e:
        raise Exception(f"Failed to query person distinct_ids: {str(e)}") from e


def get_distinct_ids_for_person_identifier(
    team_id: int,
    distinct_id: Optional[str] = None,
    person_id: Optional[Union[str, int]] = None,
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
    return_debug_info: bool = False,
) -> Union[dict[str, Any], tuple[dict[str, Any], list, str, dict[str, Any]]]:
    """
    Build person properties as they existed at a specific point in time.

    This method queries ClickHouse events to find all person property updates
    up to the given timestamp and reconstructs the final person properties state.

    Args:
        team_id: The team ID to filter events by
        timestamp: The point in time to build properties at (events after this are ignored)
        distinct_ids: List of distinct_ids to query for person properties
        include_set_once: If True, also handles $set_once operations (default: False)
        timeout: Query timeout in seconds (default: 30)
        return_debug_info: If True, also returns query and params for debugging (default: False)

    Returns:
        If return_debug_info=False: Dictionary of person properties as they existed at the specified time
        If return_debug_info=True: Tuple of (properties dict, raw_rows, query_string, query_params)

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

    # Build the ClickHouse query for all distinct_ids
    if include_set_once:
        # Query to get all property update events ($set, $set_once) up to timestamp
        # This includes both dedicated events and other events with $set in their properties
        query = """
        SELECT
            toJSONString(properties) as properties_json,
            timestamp,
            event
        FROM events
        WHERE team_id = %(team_id)s
            AND distinct_id IN %(distinct_ids)s
            AND timestamp <= %(timestamp)s
            AND (
                event = '$set'
                OR event = '$set_once'
                OR JSONHas(properties, '$set')
            )
        ORDER BY timestamp ASC
        """
    else:
        # Query to get all events that might contain $set operations
        # This includes both dedicated $set events and other events with $set in their properties
        query = """
        SELECT
            toJSONString(properties) as properties_json,
            timestamp,
            event
        FROM events
        WHERE team_id = %(team_id)s
            AND distinct_id IN %(distinct_ids)s
            AND timestamp <= %(timestamp)s
            AND (
                event = '$set'
                OR JSONHas(properties, '$set')
            )
        ORDER BY timestamp ASC
        """

    params = {
        "team_id": team_id,
        "distinct_ids": distinct_ids,
        "timestamp": timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        rows = sync_execute(query, params, settings={"max_execution_time": timeout})
    except Exception as e:
        raise Exception(f"Failed to query ClickHouse events: {str(e)}") from e

    # Build person properties by applying operations chronologically
    person_properties = {}

    for row in rows:
        properties_json, event_timestamp, event_name = row

        if properties_json:
            try:
                # ClickHouse toJSONString() may return double-escaped JSON
                # Parse defensively to handle both single and double encoding
                parsed = json.loads(properties_json)
                event_properties = json.loads(parsed) if isinstance(parsed, str) else parsed

                if include_set_once:
                    # Handle both $set and $set_once when include_set_once is True
                    # Handle $set operations from any event (including nested $set in $pageview etc.)
                    if "$set" in event_properties:
                        set_properties = event_properties["$set"]
                        if isinstance(set_properties, dict):
                            person_properties.update(set_properties)

                    # Handle $set_once operations (only from dedicated $set_once events)
                    if event_name == "$set_once" and "$set_once" in event_properties:
                        set_once_properties = event_properties["$set_once"]
                        if isinstance(set_once_properties, dict):
                            for key, value in set_once_properties.items():
                                if key not in person_properties:
                                    person_properties[key] = value
                else:
                    # Only handle $set operations when include_set_once is False
                    if "$set" in event_properties:
                        set_properties = event_properties["$set"]
                        if isinstance(set_properties, dict):
                            person_properties.update(set_properties)

            except (json.JSONDecodeError, KeyError, TypeError):
                # Skip events with malformed property data
                continue

    if return_debug_info:
        return person_properties, rows, query, params
    else:
        return person_properties
