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
    person_id: Optional[Union[str, int]] = None,
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
    logger.info(
        f"[ClickHouse Person Lookup] Called with team_id={team_id}, distinct_id={distinct_id}, person_id={person_id}"
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
            logger.info(f"[ClickHouse Person Lookup] Looking up by distinct_id: {distinct_id}")
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
                logger.warning(f"[ClickHouse Person Lookup] No person found for distinct_id: {distinct_id}")
                return None, []

            found_person_id = result[0][0]
            logger.info(f"[ClickHouse Person Lookup] Found person_id: {found_person_id}")

        else:  # person_id provided
            logger.info(f"[ClickHouse Person Lookup] Looking up by person_id: {person_id}")
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
            logger.warning(f"[ClickHouse Person Lookup] No distinct_ids found for person_id: {found_person_id}")
            return None, []

        logger.info(f"[ClickHouse Person Lookup] Found person_id: {found_person_id}, distinct_ids: {distinct_ids}")
        return found_person_id, distinct_ids

    except Exception as e:
        logger.exception(f"[ClickHouse Person Lookup] Exception during lookup: {str(e)}")
        raise Exception(f"Failed to query person distinct_ids from ClickHouse: {str(e)}") from e


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
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"[Person Lookup] Called with team_id={team_id}, distinct_id={distinct_id}, person_id={person_id}")

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
        from django.conf import settings

        from posthog.models import (
            Person as PersonModel,
            PersonDistinctId,
        )
        from posthog.models.person.person import READ_DB_FOR_PERSONS

        logger.info(f"[Person Lookup] Database configuration:")
        logger.info(f"[Person Lookup] READ_DB_FOR_PERSONS = {READ_DB_FOR_PERSONS}")
        logger.info(f"[Person Lookup] Available databases: {list(settings.DATABASES.keys())}")
        if "persons_db_reader" in settings.DATABASES:
            logger.info(
                f"[Person Lookup] persons_db_reader URL: {settings.DATABASES['persons_db_reader'].get('NAME', 'Not set')}"
            )
        if "persons_db_writer" in settings.DATABASES:
            logger.info(
                f"[Person Lookup] persons_db_writer URL: {settings.DATABASES['persons_db_writer'].get('NAME', 'Not set')}"
            )

        # Create the query manager and log which database it will use
        query_manager = PersonModel.objects.db_manager(READ_DB_FOR_PERSONS)
        actual_database = query_manager.db
        logger.info(f"[Person Lookup] Query will use database: '{actual_database}'")

        # Log the database connection details
        try:
            db_config = settings.DATABASES[actual_database]
            db_name = db_config.get("NAME", "Unknown")
            db_host = db_config.get("HOST", "localhost")
            db_port = db_config.get("PORT", "5432")
            logger.info(f"[Person Lookup] Database details: name='{db_name}', host='{db_host}', port='{db_port}'")
        except Exception as e:
            logger.warning(f"[Person Lookup] Could not get database details: {e}")

        if distinct_id is not None:
            logger.info(f"[Person Lookup] Looking up person by distinct_id using direct ORM: {distinct_id}")
            # Direct ORM query avoiding PersonHog routing
            person = query_manager.filter(team_id=team_id, persondistinctid__distinct_id=distinct_id).first()
        else:
            logger.info(f"[Person Lookup] Looking up person by person_id using direct ORM: {person_id}")
            # Direct ORM query avoiding PersonHog routing
            person = query_manager.filter(team_id=team_id, uuid=person_id).first()

        logger.info(f"[Person Lookup] ORM query result: person={person}")
        logger.info(f"[Person Lookup] Query executed on database: '{actual_database}'")

        if person is None:
            logger.warning(f"[Person Lookup] No person found for team_id={team_id}")

            # Debug information to help understand what went wrong
            try:
                if distinct_id is not None:
                    # Check if distinct_id exists at all
                    distinct_id_obj = PersonDistinctId.objects.filter(distinct_id=distinct_id).first()
                    logger.info(
                        f"[Person Lookup] Direct DB check - distinct_id '{distinct_id}' exists: {distinct_id_obj is not None}"
                    )
                    if distinct_id_obj:
                        logger.info(
                            f"[Person Lookup] Found distinct_id with team_id={distinct_id_obj.team_id}, person_id={distinct_id_obj.person_id}"
                        )

                    # Check if it exists for this specific team
                    team_distinct_id = PersonDistinctId.objects.filter(team_id=team_id, distinct_id=distinct_id).first()
                    logger.info(
                        f"[Person Lookup] Team-specific check - distinct_id exists for team {team_id}: {team_distinct_id is not None}"
                    )

                elif person_id is not None:
                    # Check if person_id (UUID) exists
                    person_obj = PersonModel.objects.filter(uuid=person_id).first()
                    logger.info(
                        f"[Person Lookup] Direct DB check - person_id '{person_id}' exists: {person_obj is not None}"
                    )
                    if person_obj:
                        logger.info(
                            f"[Person Lookup] Found person with team_id={person_obj.team_id}, uuid={person_obj.uuid}"
                        )

                    # Check if it exists for this specific team
                    team_person = PersonModel.objects.filter(team_id=team_id, uuid=person_id).first()
                    logger.info(
                        f"[Person Lookup] Team-specific check - person_id exists for team {team_id}: {team_person is not None}"
                    )

                    # Also check total person count for this team
                    total_persons = PersonModel.objects.filter(team_id=team_id).count()
                    logger.info(f"[Person Lookup] Total persons in team {team_id}: {total_persons}")

                    # Show a few sample person UUIDs for comparison
                    sample_persons = PersonModel.objects.filter(team_id=team_id)[:3]
                    for i, p in enumerate(sample_persons):
                        logger.info(f"[Person Lookup] Sample person {i + 1}: uuid={p.uuid}")

            except Exception as e:
                logger.exception(f"[Person Lookup] Error during direct DB check: {e}")

            return None, []

        # Get all distinct_ids for this person using direct ORM query
        distinct_ids = list(
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(team_id=team_id, person_id=person.pk)
            .values_list("distinct_id", flat=True)
        )

        logger.info(f"[Person Lookup] Found person: uuid={person.uuid}, distinct_ids={distinct_ids}")
        return person, distinct_ids

    except Exception as e:
        logger.exception(f"[Person Lookup] Exception during lookup: {str(e)}")
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
