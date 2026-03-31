"""
Redis-based filter storage service for managing large filter datasets in backfill workflows.

This module provides temporary storage for PersonPropertyFilter collections to avoid Temporal
blob size limits when passing large filter payloads between workflows and activities.

TTL Considerations:
- Individual activities have start_to_close_timeout=12h with maximum_attempts=3
- Coordinator workflows spawn multiple child workflows with batch delays
- Total workflow execution time in worst case: 3 retries × 12h + batch delays ≈ 40-48h
- TTL set to 72h (3 days) provides safety margin for retries and delays
- If workflows consistently exceed 48h, consider TTL refresh logic in get_filters()
"""

import json
import hashlib

import structlog

from posthog.redis import get_client
from posthog.temporal.messaging.types import PersonPropertyFilter

KEY_PREFIX = "backfill_person_properties_filters:"
# TTL sizing: Worst case workflow duration ~48h (3 × 12h retries + batch delays)
# 72h provides 50% safety margin. Increase if workflows consistently run longer.
DEFAULT_TTL = 72 * 60 * 60  # 3 days

logger = structlog.get_logger(__name__)


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

    # Create storage object containing both filters and properties
    storage_data = {
        "filters": filter_data,
        "person_properties": sorted(person_properties),  # Sort for consistent ordering
    }

    # Create hash of the storage data for the key
    content_hash = hashlib.sha256(json.dumps(storage_data, sort_keys=True).encode()).hexdigest()

    storage_key = f"{KEY_PREFIX}team_{team_id}_{content_hash}"

    # Store the serialized data in Redis
    get_client().setex(storage_key, ttl, json.dumps(storage_data))

    return storage_key


def get_filters_and_properties(storage_key: str) -> tuple[list[PersonPropertyFilter], list[str]] | None:
    """
    Retrieve both filters and person properties using a storage key.

    Args:
        storage_key: Key returned by store_filters

    Returns:
        Tuple of (filters, person_properties), or None if not found

    Note:
        If workflows consistently exceed 48h and TTL becomes an issue,
        consider adding TTL refresh logic here using Redis EXPIRE command.
    """
    data = get_client().get(storage_key)
    if data is None:
        return None

    storage_data = json.loads(data.decode("utf-8"))
    filter_data = storage_data["filters"]
    person_properties = storage_data["person_properties"]

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

    return filters, person_properties
