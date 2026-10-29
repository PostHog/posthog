"""Result types and literals shared by the divergence scans and the repair."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen

# "equal": the versions match but the ClickHouse winner holds other content (a tie or a blanked person).
PersonDivergenceKind = Literal["hidden", "swept", "stale", "behind", "absent", "equal"]

MappingDivergenceKind = Literal["hidden", "other_person", "stale", "absent"]

SampleClassification = Literal["equal", "pg_below_ch", "pg_above_ch", "team_gone", "pg_tombstone", "pg_absent"]

SampleEra = Literal["before_cutoff", "since_cutoff", "any"]

RepairOutcome = Literal[
    "would_repair",
    "repaired",
    "skipped_not_divergent",
    "skipped_not_live",
    "skipped_team_gone",
    "skipped_tombstoned",
    "skipped_owner_changed",
    "skipped_mapping_gone",
    "skipped_reread_lagging",
    "skipped_stale",
    "skipped_stale_merge_failed",
    "skipped_stale_merge_too_large",
    "skipped_stale_merge_restricted",
    "merge_queued",
    "skipped_too_many_distinct_ids",
]


@frozen
class DivergentPerson:
    team_id: int
    person_uuid: str
    kind: PersonDivergenceKind
    ch_max_version: int
    pg_version: int


@frozen
class ScanSummary:
    candidates: int
    divergent: int
    skipped_team_ids: list[int]


@frozen
class SampledPerson:
    team_id: int
    person_uuid: str
    classification: SampleClassification
    era: SampleEra
    ch_max_version: int
    pg_version: int | None


@frozen
class SampleBucket:
    classification: SampleClassification
    era: SampleEra


@frozen
class SampleSummary:
    sampled: int
    counts: dict[SampleBucket, int]
    skipped_team_ids: list[int]


@frozen
class TeamCheck:
    team_id: int
    persons_sampled: int
    persons_live_in_postgres: int
    distinct_ids_sampled: int
    distinct_ids_live_in_postgres: int


@frozen
class PersonRef:
    team_id: int
    person_uuid: str

    def __post_init__(self) -> None:
        # Lookups key on the canonical form that ClickHouse toString(id) and the persons reads return.
        if str(UUID(self.person_uuid)) != self.person_uuid:
            raise ValueError(f"person_uuid must be a canonical lowercase UUID: {self.person_uuid!r}")


@frozen
class RepairAction:
    """One person row (``distinct_id`` is None) or one of its mappings, with what the repair did to it.

    A person with too many distinct ids to repair gets one extra row with no ``distinct_id`` and the
    outcome ``skipped_too_many_distinct_ids``, which stands for all of its mappings.
    """

    team_id: int
    person_uuid: str
    distinct_id: str | None
    kind: PersonDivergenceKind | MappingDivergenceKind | None
    pg_version: int | None
    ch_max_version: int | None
    target_version: int | None
    outcome: RepairOutcome


@frozen
class RepairSummary:
    applied: bool
    persons: int
    person_outcomes: dict[RepairOutcome, int]
    mapping_outcomes: dict[RepairOutcome, int]
    # Published rows that Kafka did not confirm: the delivery failed, or it was still queued at the deadline.
    undelivered: int
