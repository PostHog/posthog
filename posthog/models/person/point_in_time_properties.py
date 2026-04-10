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


def get_person_distinct_ids_from_clickhouse(
    team_id: int,
    distinct_id: Optional[str] = None,
    person_id: Optional[str] = None,
) -> tuple[Optional[str], list[str]]:
    """
    Get person_id and all distinct_ids from ClickHouse for a person identified by either distinct_id or person_id.

    This bypasses PostgreSQL entirely and queries ClickHouse directly, which is useful when
    the posthog_person table in PostgreSQL is empty but data exists in ClickHouse.

    Args:
        team_id: The team ID
        distinct_id: A distinct_id belonging to the person (mutually exclusive with person_id)
        person_id: The person_id (UUID) to get distinct_ids for (mutually exclusive with distinct_id)

    Returns:
        Tuple of (person_id as string or None, list of distinct_ids associated with the person)

    Raises:
        ValueError: If parameters are invalid or both distinct_id and person_id are provided
        Exception: If ClickHouse query fails
    """
    import logging

    from posthog.clickhouse.client import sync_execute

    logger = logging.getLogger(__name__)
    logger.debug(
        f"[ClickHouse Person Lookup] Called with team_id={team_id}, distinct_id=<redacted>, person_id=<redacted>"
    )

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
            logger.debug("[ClickHouse Person Lookup] Looking up by distinct_id")
            # First, get the person_id for this distinct_id
            query = """
            SELECT person_id
            FROM person_distinct_id2 FINAL
            WHERE team_id = %(team_id)s
              AND distinct_id = %(distinct_id)s
              AND is_deleted = 0
            LIMIT 1
            """
            params = {
                "team_id": team_id,
                "distinct_id": distinct_id,
            }

            result = sync_execute(query, params)
            if not result:
                logger.warning("[ClickHouse Person Lookup] No person found for distinct_id")
                return None, []

            found_person_id = result[0][0]
            logger.debug("[ClickHouse Person Lookup] Found person_id")

        else:  # person_id provided
            logger.debug("[ClickHouse Person Lookup] Looking up by person_id")
            found_person_id = str(person_id)

        # Now get all distinct_ids for this person_id
        query = """
        SELECT distinct_id
        FROM person_distinct_id2 FINAL
        WHERE team_id = %(team_id)s
          AND person_id = %(person_id)s
          AND is_deleted = 0
        """
        params = {
            "team_id": team_id,
            "person_id": found_person_id,
        }

        result = sync_execute(query, params)
        distinct_ids = [row[0] for row in result]

        if not distinct_ids:
            logger.warning("[ClickHouse Person Lookup] No distinct_ids found for person_id")
            return None, []

        logger.debug(f"[ClickHouse Person Lookup] Found {len(distinct_ids)} distinct_ids")
        return found_person_id, distinct_ids

    except Exception:
        logger.exception("[ClickHouse Person Lookup] Failed to query person distinct_ids")
        raise


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
    import logging

    logger = logging.getLogger(__name__)
    logger.debug(f"[Person Lookup] Called with team_id={team_id}, distinct_id=<redacted>, person_id=<redacted>")

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
        from posthog.models import (
            Person as PersonModel,
            PersonDistinctId,
        )
        from posthog.models.person.person import READ_DB_FOR_PERSONS

        logger.debug("[Person Lookup] Database configuration loaded")

        # Create the query manager and log which database it will use
        query_manager = PersonModel.objects.db_manager(READ_DB_FOR_PERSONS)
        logger.debug("[Person Lookup] Query manager configured")

        # Database configuration is handled internally

        if distinct_id is not None:
            logger.debug("[Person Lookup] Looking up person by distinct_id using direct ORM")
            # Direct ORM query avoiding PersonHog routing
            person = query_manager.filter(team_id=team_id, persondistinctid__distinct_id=distinct_id).first()
        else:
            logger.debug("[Person Lookup] Looking up person by person_id using direct ORM")
            # Direct ORM query avoiding PersonHog routing
            # person_id is guaranteed to be not None at this point due to validation above
            assert person_id is not None
            person = query_manager.filter(team_id=team_id, uuid=person_id).first()

        logger.debug(f"[Person Lookup] ORM query result: {'found' if person else 'not found'}")

        if person is None:
            logger.warning(f"[Person Lookup] No person found for team_id={team_id}")

            # Debug information available at DEBUG level only
            logger.debug("[Person Lookup] Person lookup failed - enable DEBUG logging for detailed analysis")

            return None, []

        # Get all distinct_ids for this person using direct ORM query
        distinct_ids = list(
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(team_id=team_id, person_id=person.pk)
            .values_list("distinct_id", flat=True)
        )

        logger.debug(f"[Person Lookup] Found person with {len(distinct_ids)} distinct_ids")
        return person, distinct_ids

    except Exception:
        logger.exception("[Person Lookup] Failed to query person distinct_ids")
        raise


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
    except Exception:
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Failed to query ClickHouse events for person properties")
        raise

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
