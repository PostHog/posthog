"""
Redis-based filter storage service for managing large filter datasets in backfill workflows.
"""

import json
import hashlib

from posthog.redis import get_client
from posthog.temporal.messaging.types import PersonPropertyFilter


class FilterStorage:
    """
    Redis-based service for storing and retrieving filter data to avoid Temporal blob size limits.

    Uses Redis with a TTL to store filter collections temporarily during workflows.
    """

    KEY_PREFIX = "backfill_person_properties_filters:"
    DEFAULT_TTL = 24 * 60 * 60  # 24 hours

    def __init__(self):
        self._redis_client = None

    def _get_client(self):
        if self._redis_client is None:
            self._redis_client = get_client()
        return self._redis_client

    def store_filters(self, filters: list[PersonPropertyFilter], team_id: int, ttl: int = DEFAULT_TTL) -> str:
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
            }
            for f in filters
        ]

        # Create hash of the filter data for the key
        content_hash = hashlib.sha256(json.dumps(filter_data, sort_keys=True).encode()).hexdigest()[:16]

        storage_key = f"{self.KEY_PREFIX}team_{team_id}_{content_hash}"

        # Store the serialized filter data in Redis
        self._get_client().setex(storage_key, ttl, json.dumps(filter_data))

        return storage_key

    def get_filters(self, storage_key: str) -> list[PersonPropertyFilter] | None:
        """
        Retrieve filters using a storage key.

        Args:
            storage_key: Key returned by store_filters

        Returns:
            List of PersonPropertyFilter objects, or None if not found
        """
        data = self._get_client().get(storage_key)
        if data is None:
            return None

        filter_data = json.loads(data.decode("utf-8"))

        # Reconstruct PersonPropertyFilter objects
        return [
            PersonPropertyFilter(
                condition_hash=item["condition_hash"],
                bytecode=item["bytecode"],
                cohort_ids=item["cohort_ids"],
            )
            for item in filter_data
        ]


# Global instance for use across workflows
filter_storage = FilterStorage()
