from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings

from posthog.clickhouse.client import sync_execute

PERSON_SEED_BASE_BYTES = 256
# Each worst-case condition hash appears in both evaluated and matched.
PERSON_SEED_PER_HASH_BYTES = 38


@dataclass(frozen=True)
class PersonSeedEstimate:
    estimated_persons: int
    pinned_condition_count: int
    bytes_per_seed: int
    estimated_topic_bytes: int
    budget_bytes: int

    @property
    def over_budget(self) -> bool:
        return self.estimated_topic_bytes > self.budget_bytes

    def as_preconditions(self) -> dict[str, Any]:
        return {
            "person_seed_estimated_persons": self.estimated_persons,
            "person_seed_pinned_condition_count": self.pinned_condition_count,
            "person_seed_bytes_per_seed": self.bytes_per_seed,
            "person_seed_estimated_topic_bytes": self.estimated_topic_bytes,
            "person_seed_topic_bytes_budget": self.budget_bytes,
        }


def estimate_person_seed_topic_bytes(
    team_id: int,
    person_scan_since: datetime,
    pinned_condition_count: int,
) -> PersonSeedEstimate:
    rows = sync_execute(
        """
        SELECT uniq(id)
        FROM person
        WHERE team_id = %(team_id)s
          AND _timestamp >= %(person_scan_since)s
        """,
        {"team_id": team_id, "person_scan_since": person_scan_since},
        settings={"max_execution_time": 30},
        team_id=team_id,
        readonly=True,
    )
    estimated_persons = int(rows[0][0])
    bytes_per_seed = PERSON_SEED_BASE_BYTES + PERSON_SEED_PER_HASH_BYTES * pinned_condition_count
    return PersonSeedEstimate(
        estimated_persons=estimated_persons,
        pinned_condition_count=pinned_condition_count,
        bytes_per_seed=bytes_per_seed,
        estimated_topic_bytes=estimated_persons * bytes_per_seed,
        budget_bytes=settings.BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET,
    )
