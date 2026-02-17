"""
Module for building person properties from ClickHouse events at a specific point in time.

This module provides functionality to reconstruct person properties as they existed
at a specific timestamp by querying ClickHouse events and applying property updates
chronologically.
"""

from datetime import datetime
from typing import Any, Optional

from posthog.clickhouse.client import sync_execute


def build_person_properties_at_time(
    distinct_id: str,
    team_id: int,
    timestamp: datetime,
    include_set_once: bool = False,
    timeout: Optional[int] = 30,
) -> dict[str, Any]:
    """
    Build person properties as they existed at a specific point in time.

    This method queries ClickHouse events to find all person property updates
    up to the given timestamp and reconstructs the final person properties state.

    Args:
        distinct_id: The distinct_id of the person to build properties for
        team_id: The team ID to filter events by
        timestamp: The point in time to build properties at (events after this are ignored)
        include_set_once: If True, also handles $set_once operations (default: False)
        timeout: Query timeout in seconds (default: 30)

    Returns:
        Dictionary of person properties as they existed at the specified time

    Raises:
        ValueError: If distinct_id or team_id are invalid
        Exception: If ClickHouse query fails
    """
    if not distinct_id or not isinstance(distinct_id, str):
        raise ValueError("distinct_id must be a non-empty string")

    if not isinstance(team_id, int) or team_id <= 0:
        raise ValueError("team_id must be a positive integer")

    if not isinstance(timestamp, datetime):
        raise ValueError("timestamp must be a datetime object")

    if include_set_once:
        # Query to get all property update events ($set, $set_once) up to timestamp
        query = """
        SELECT
            toJSONString(properties) as properties_json,
            timestamp,
            event
        FROM events
        WHERE team_id = %(team_id)s
            AND distinct_id = %(distinct_id)s
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
            AND distinct_id = %(distinct_id)s
            AND timestamp <= %(timestamp)s
            AND (
                event = '$set'
                OR JSONHas(properties, '$set')
            )
        ORDER BY timestamp ASC
        """

    params = {"team_id": team_id, "distinct_id": distinct_id, "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S")}

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
