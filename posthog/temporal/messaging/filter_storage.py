"""
Redis-based filter storage service for managing large filter datasets in backfill workflows.

This module provides temporary storage for PersonPropertyFilter collections to avoid Temporal
blob size limits when passing large filter payloads between workflows and activities.

TTL Considerations:
- Individual activities have start_to_close_timeout=12h with maximum_attempts=3
- Coordinator workflows spawn multiple child workflows with batch delays
- Total workflow execution time in worst case: 3 retries × 12h + batch delays ≈ 40-48h
- TTL set to 168h (7 days) provides generous safety margin for retries and delays
- If workflows consistently approach TTL (7d), consider TTL refresh logic in get_filters()
"""

import json
import hashlib
from typing import Any

import structlog

from posthog.redis import get_client
from posthog.temporal.messaging.types import BehavioralEventFilter, PersonPropertyFilter

from common.hogvm.python.operation import HOGQL_BYTECODE_IDENTIFIER, Operation

KEY_PREFIX = "backfill_person_properties_filters:"
EVENT_KEY_PREFIX = "backfill_event_filters:"
# TTL sizing: Worst case workflow duration ~48h (3 × 12h retries + batch delays)
# 168h provides generous safety margin for complex backfill operations that may run longer.
DEFAULT_TTL = 168 * 60 * 60  # 7 days

logger = structlog.get_logger(__name__)


def combine_filter_bytecodes(filters: list[PersonPropertyFilter]) -> list[Any]:
    """Combine multiple filter bytecodes into a single bytecode returning a dict.

    Strips the header from each filter's bytecode body, interleaves condition_hash
    keys, and appends a DICT opcode to collect all results into
    {condition_hash: bool_result, ...}.

    Built once at coordinator startup and reused for every person.
    """
    combined: list[Any] = [HOGQL_BYTECODE_IDENTIFIER, 1]

    valid_count = 0
    for f in filters:
        if len(f.bytecode) <= 2:
            logger.warning(
                "Skipping malformed bytecode for filter",
                condition_hash=f.condition_hash,
                bytecode_length=len(f.bytecode),
            )
            continue
        combined.append(Operation.STRING)
        combined.append(f.condition_hash)
        combined.extend(f.bytecode[2:])
        valid_count += 1

    combined.append(Operation.DICT)
    combined.append(valid_count)

    return combined


def store_filters(filters: list[PersonPropertyFilter], team_id: int, ttl: int = DEFAULT_TTL) -> str:
    """
    Store a list of filters and return a storage key.

    Args:
        filters: List of PersonPropertyFilter objects to store
        team_id: Team ID for namespacing
        ttl: Time to live in seconds

    Returns:
        Storage key that can be used to retrieve the filters
    """
    # Create serializable filter data
    filter_data = [
        {
            "condition_hash": f.condition_hash,
            "bytecode": f.bytecode,
            "cohort_ids": f.cohort_ids,
            "property_key": f.property_key,
        }
        for f in filters
    ]

    # Extract person properties from filters using the property_key field
    person_properties = set()
    for f in filters:
        if f.property_key:
            person_properties.add(f.property_key)

    # Combine all filter bytecodes into a single optimized bytecode
    combined_bytecode = combine_filter_bytecodes(filters)

    # Create storage object containing filters, properties, and combined bytecode
    storage_data = {
        "filters": filter_data,
        "person_properties": sorted(person_properties),  # Sort for consistent ordering
        "combined_bytecode": combined_bytecode,
    }

    # Create hash of the storage data for the key
    content_hash = hashlib.sha256(json.dumps(storage_data, sort_keys=True).encode()).hexdigest()

    storage_key = f"{KEY_PREFIX}team_{team_id}_{content_hash}"

    # Store the serialized data in Redis
    get_client().setex(storage_key, ttl, json.dumps(storage_data))

    return storage_key


def get_filters_and_properties(storage_key: str) -> tuple[list[PersonPropertyFilter], list[str], list[Any]] | None:
    """
    Retrieve filters, person properties, and combined bytecode using a storage key.

    Args:
        storage_key: Key returned by store_filters

    Returns:
        Tuple of (filters, person_properties, combined_bytecode), or None if not found

    Note:
        If workflows consistently approach TTL (7d) and expiration becomes an issue,
        consider adding TTL refresh logic here using Redis EXPIRE command.
    """
    data = get_client().get(storage_key)
    if data is None:
        return None

    storage_data = json.loads(data.decode("utf-8"))
    filter_data = storage_data["filters"]
    person_properties = storage_data["person_properties"]
    combined_bytecode = storage_data.get("combined_bytecode")

    # Reconstruct PersonPropertyFilter objects
    filters = [
        PersonPropertyFilter(
            condition_hash=item["condition_hash"],
            bytecode=item["bytecode"],
            cohort_ids=item["cohort_ids"],
            property_key=item["property_key"],
        )
        for item in filter_data
    ]

    # If combined_bytecode is not present (backward compatibility), generate it
    if combined_bytecode is None:
        combined_bytecode = combine_filter_bytecodes(filters)

    return filters, person_properties, combined_bytecode


def combine_event_filter_bytecodes(filters: list[BehavioralEventFilter]) -> list[Any]:
    """Combine multiple behavioral event filter bytecodes into a single bytecode returning a dict.

    Same strategy as combine_filter_bytecodes: strips headers, interleaves condition_hash keys,
    and appends a DICT opcode. The resulting bytecode returns {condition_hash: bool_result, ...}
    when executed with event globals.

    Malformed filters (bytecode length <= 2) are silently skipped with a warning log. If all
    filters are malformed, the result is a valid bytecode that produces an empty dict.
    """
    combined: list[Any] = [HOGQL_BYTECODE_IDENTIFIER, 1]

    valid_count = 0
    for f in filters:
        if len(f.bytecode) <= 2:
            logger.warning(
                "Skipping malformed bytecode for event filter",
                condition_hash=f.condition_hash,
                event_name=f.event_name,
                bytecode_length=len(f.bytecode),
            )
            continue
        combined.append(Operation.STRING)
        combined.append(f.condition_hash)
        combined.extend(f.bytecode[2:])
        valid_count += 1

    combined.append(Operation.DICT)
    combined.append(valid_count)

    return combined


def store_event_filters(filters: list[BehavioralEventFilter], team_id: int, ttl: int = DEFAULT_TTL) -> str:
    """Store behavioral event filters in Redis and return a storage key.

    Filters are grouped by event name and a combined bytecode is built per group,
    enabling efficient per-event-name evaluation during the backfill scan.
    """
    filter_data = [
        {
            "condition_hash": f.condition_hash,
            "bytecode": f.bytecode,
            "cohort_ids": f.cohort_ids,
            "event_name": f.event_name,
            "time_value": f.time_value,
            "time_interval": f.time_interval,
            "event_filters": f.event_filters,
        }
        for f in filters
    ]

    # Group filters by event name for per-event combined bytecodes
    event_name_groups: dict[str, list[BehavioralEventFilter]] = {}
    for f in filters:
        event_name_groups.setdefault(f.event_name, []).append(f)

    combined_bytecodes_by_event: dict[str, list[Any]] = {
        event_name: combine_event_filter_bytecodes(group) for event_name, group in sorted(event_name_groups.items())
    }

    storage_data = {
        "filters": filter_data,
        "event_names": sorted(event_name_groups.keys()),
        "combined_bytecodes_by_event": combined_bytecodes_by_event,
    }

    content_hash = hashlib.sha256(json.dumps(storage_data, sort_keys=True).encode()).hexdigest()
    storage_key = f"{EVENT_KEY_PREFIX}team_{team_id}_{content_hash}"

    get_client().setex(storage_key, ttl, json.dumps(storage_data))

    return storage_key


def get_event_filters(
    storage_key: str,
) -> tuple[list[BehavioralEventFilter], list[str], dict[str, list[Any]]] | None:
    """Retrieve behavioral event filters, event names, and per-event combined bytecodes.

    Returns:
        Tuple of (filters, event_names, combined_bytecodes_by_event), or None if not found.
    """
    data = get_client().get(storage_key)
    if data is None:
        return None

    storage_data = json.loads(data.decode("utf-8"))
    filter_data = storage_data["filters"]
    event_names = storage_data["event_names"]
    combined_bytecodes_by_event = storage_data.get("combined_bytecodes_by_event", {})

    filters = [
        BehavioralEventFilter(
            condition_hash=item["condition_hash"],
            bytecode=item["bytecode"],
            cohort_ids=item["cohort_ids"],
            event_name=item["event_name"],
            time_value=item["time_value"],
            time_interval=item["time_interval"],
            event_filters=item.get("event_filters"),
        )
        for item in filter_data
    ]

    # Regenerate combined bytecodes if missing (backward compatibility)
    if not combined_bytecodes_by_event:
        event_name_groups: dict[str, list[BehavioralEventFilter]] = {}
        for f in filters:
            event_name_groups.setdefault(f.event_name, []).append(f)
        combined_bytecodes_by_event = {
            event_name: combine_event_filter_bytecodes(group) for event_name, group in sorted(event_name_groups.items())
        }

    return filters, event_names, combined_bytecodes_by_event
