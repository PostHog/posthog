from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.errors import InternalCHQueryError
from posthog.exceptions import ClickHouseQueryTimeOut

# Calibrated against a serialized `PersonSeed` (rust/cohort-core/src/seed/person.rs): the fixed
# envelope (schema_version, kind, team_id, person_id, scanned_at_ms, run_id, claim_epoch) plus one
# quoted 16-char condition hash in both `evaluated` and `matched` — the worst case, where every
# pinned condition came back TRUE. Recalibrate when that struct's wire fields change.
PERSON_SEED_BASE_BYTES = 256
PERSON_SEED_PER_HASH_BYTES = 38

# TOO_MANY_ROWS / TOO_MANY_BYTES: what `read_overflow_mode: throw` raises when the scan hits
# `BEHAVIORAL_BACKFILL_PERSON_SIZING_MAX_BYTES`. Deterministic for a given team, unlike a transport
# failure.
_READ_CAP_ERROR_CODES = (158, 307)


class PersonSeedEstimateScanCapExceeded(Exception):
    """The sizing scan hit one of its own caps: the team's person history exceeds what the estimate
    may read or how long it may run, so the answer will not change on retry and the caller should
    refuse rather than repeat the capped scan."""


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
    max_bytes_to_read = settings.BEHAVIORAL_BACKFILL_PERSON_SIZING_MAX_BYTES
    max_execution_time = settings.BEHAVIORAL_BACKFILL_PERSON_SIZING_MAX_SECONDS
    # `person` is ORDER BY (team_id, id) with only a minmax index on `_timestamp`, and rows are
    # rewritten in place on every update, so the window bound prunes close to nothing: this reads the
    # team's whole person history either way. `BEHAVIORAL_BACKFILL_PERSON_SIZING_MAX_BYTES` is what
    # actually bounds it, and it throws rather than letting the gate size a run off a partial scan.
    #
    # Collapsing versions per id before counting keeps persons whose latest in-window row is a
    # deletion out of the estimate — counting them inflates the topic-byte figure and biases the
    # budget gate toward refusing runs that would have fit.
    try:
        rows = sync_execute(
            """
            SELECT count()
            FROM (
                SELECT id
                FROM person
                WHERE team_id = %(team_id)s
                  AND _timestamp >= %(person_scan_since)s
                GROUP BY id
                HAVING argMax(is_deleted, version) = 0
            )
            """,
            {"team_id": team_id, "person_scan_since": person_scan_since},
            settings={
                "max_execution_time": max_execution_time,
                "max_bytes_to_read": max_bytes_to_read,
                "read_overflow_mode": "throw",
            },
            team_id=team_id,
            readonly=True,
        )
    except ClickHouseQueryTimeOut as error:
        # `max_execution_time` is this gate's own cap, so a timeout means the same thing as the byte
        # cap: the team's person history does not fit, and a retry pays the whole scan again for the
        # same answer. `trigger_cohort_backfill_run_task` retries every other exception three times,
        # which at a 300 s cap is 20 minutes of scans on the user-facing cluster per cohort save.
        raise PersonSeedEstimateScanCapExceeded(
            f"Person sizing scan for team {team_id} exceeded its {max_execution_time}s time cap"
        ) from error
    except InternalCHQueryError as error:
        if error.code in _READ_CAP_ERROR_CODES:
            raise PersonSeedEstimateScanCapExceeded(
                f"Person sizing scan for team {team_id} exceeded its {max_bytes_to_read} byte read cap"
            ) from error
        raise
    estimated_persons = int(rows[0][0])
    bytes_per_seed = PERSON_SEED_BASE_BYTES + PERSON_SEED_PER_HASH_BYTES * pinned_condition_count
    return PersonSeedEstimate(
        estimated_persons=estimated_persons,
        pinned_condition_count=pinned_condition_count,
        bytes_per_seed=bytes_per_seed,
        estimated_topic_bytes=estimated_persons * bytes_per_seed,
        budget_bytes=settings.BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET,
    )
