"""
Module for building person properties from ClickHouse events at a specific point in time.

This module provides functionality to reconstruct person properties as they existed
at a specific timestamp by querying ClickHouse events and applying property updates
chronologically.
"""

from datetime import datetime
from typing import Any, Optional, Union

from posthog.clickhouse.client import sync_execute


def build_person_properties_at_time(
    team_id: int,
    timestamp: datetime,
    distinct_id: Optional[str] = None,
    person_id: Optional[Union[str, int]] = None,
    include_set_once: bool = False,
    timeout: Optional[int] = 30,
) -> dict[str, Any]:
    """
    Build person properties as they existed at a specific point in time.

    This method queries ClickHouse events to find all person property updates
    up to the given timestamp and reconstructs the final person properties state.
    When person_id is provided, it considers events from ALL distinct_ids associated
    with that person.

    Args:
        team_id: The team ID to filter events by
        timestamp: The point in time to build properties at (events after this are ignored)
        distinct_id: The distinct_id to build properties for (mutually exclusive with person_id)
        person_id: The person_id to build properties for, considers all distinct_ids (mutually exclusive with distinct_id)
        include_set_once: If True, also handles $set_once operations (default: False)
        timeout: Query timeout in seconds (default: 30)

    Returns:
        Dictionary of person properties as they existed at the specified time

    Raises:
        ValueError: If parameters are invalid or both distinct_id and person_id are provided
        Exception: If ClickHouse query fails
    """
    # Validation
    if not isinstance(team_id, int) or team_id <= 0:
        raise ValueError("team_id must be a positive integer")

    if not isinstance(timestamp, datetime):
        raise ValueError("timestamp must be a datetime object")

    if distinct_id is not None and person_id is not None:
        raise ValueError("Cannot provide both distinct_id and person_id - choose one")

    if distinct_id is None and person_id is None:
        raise ValueError("Must provide either distinct_id or person_id")

    if distinct_id is not None and (not distinct_id or not isinstance(distinct_id, str)):
        raise ValueError("distinct_id must be a non-empty string")

    if person_id is not None and not person_id:
        raise ValueError("person_id must be a non-empty value")

    # Get distinct_ids to query
    distinct_ids_to_query = []

    if distinct_id is not None:
        # Simple case - query for single distinct_id
        distinct_ids_to_query = [distinct_id]
    else:
        # Complex case - get all distinct_ids for this person
        from posthog.models.person import Person, PersonDistinctId

        try:
            # First get the Person object (handle both integer ID and UUID)
            try:
                # Try as integer first (primary key)
                person_id_int = int(person_id)
                person = Person.objects.get(team_id=team_id, id=person_id_int)
            except (ValueError, TypeError):
                # If not integer, try as UUID
                person = Person.objects.get(team_id=team_id, uuid=person_id)

            # Now get all distinct_ids for this person
            distinct_id_objects = PersonDistinctId.objects.filter(team_id=team_id, person=person).values_list(
                "distinct_id", flat=True
            )
            distinct_ids_to_query = list(distinct_id_objects)

            if not distinct_ids_to_query:
                # No distinct_ids found for this person - return empty properties
                return {}

        except Person.DoesNotExist:
            # Person not found - return empty properties
            return {}
        except Exception as e:
            raise Exception(f"Failed to query person distinct_ids: {str(e)}") from e

    # Build the ClickHouse query for all distinct_ids
    if include_set_once:
        # Query to get all property update events ($set, $set_once) up to timestamp
        query = """
        SELECT
            toJSONString(properties) as properties_json,
            timestamp,
            event
        FROM events
        WHERE team_id = %(team_id)s
            AND distinct_id IN %(distinct_ids)s
            AND event IN ('$set', '$set_once')
            AND timestamp <= %(timestamp)s
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
        "distinct_ids": distinct_ids_to_query,
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
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
                import json

                # ClickHouse toJSONString() returns double-escaped JSON
                # First parse gets the JSON string, second parse gets the object
                json_string = json.loads(properties_json)
                event_properties = json.loads(json_string)

                if include_set_once:
                    # Handle both $set and $set_once when include_set_once is True
                    if event_name == "$set" and "$set" in event_properties:
                        # $set operations always update properties
                        set_properties = event_properties["$set"]
                        if isinstance(set_properties, dict):
                            person_properties.update(set_properties)

                    elif event_name == "$set_once" and "$set_once" in event_properties:
                        # $set_once operations only set if property doesn't exist
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

    return person_properties
