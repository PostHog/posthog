import os

from posthog.settings.utils import get_from_env, str_to_bool

# Off by default ("none"); enable per environment via the env override
# A set-but-empty value survives as "", which the parser reads as "all teams".
REALTIME_COHORT_TEAM_ALLOWLIST: str = os.getenv("REALTIME_COHORT_TEAM_ALLOWLIST", "none")
# Teams whose cohort saves enqueue a backfill run for rust/cohort-seeder to claim. Same grammar as
# the allowlist above, except that a set-but-empty value means no teams: nothing outside Python
# parses this setting, so it can fail closed on empty where the realtime allowlist cannot. It is
# deliberately a separate setting, an opt-in on top of realtime membership rather than something a
# team inherits by it: replaying a team's history costs ClickHouse scans and seed-topic bytes, so it
# stays an explicit operator decision. A team listed here but not above enqueues nothing.
#
# Order this against the seeder's own arming: Django cannot see `SEEDER_PERSON_SEEDS_ENABLED`, so a
# team with person-leaf cohorts opted in before that switch files person runs that park in
# `awaiting_boundary`, each holding its cohort's uniqueness slot and blocking the operator's team
# command until the seeder starts discovering them.
COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST: str = os.getenv("COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST", "none")
BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED: bool = get_from_env(
    "BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED", False, type_cast=str_to_bool
)
BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED: bool = get_from_env(
    "BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED", False, type_cast=str_to_bool
)
BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS: int = get_from_env(
    "BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS", 64, type_cast=int
)
BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS: int = get_from_env(
    "BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS", 90, type_cast=int
)
# Bounds the estimated total person-seed bytes emitted by one team run.
BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET: int = get_from_env(
    "BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET", 0, type_cast=int
)
BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED: bool = get_from_env(
    "BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED", False, type_cast=str_to_bool
)
BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED: bool = get_from_env(
    "BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED", False, type_cast=str_to_bool
)
BEHAVIORAL_BACKFILL_FINALIZER_ENABLED: bool = get_from_env(
    "BEHAVIORAL_BACKFILL_FINALIZER_ENABLED", False, type_cast=str_to_bool
)
# Whether the finalizer may terminalize person-property runs and stamp
# `last_backfill_person_properties_at`.
#
# Keep it off until every region's flags service runs
# `REALTIME_COHORT_MEMBERSHIP_STAMP_POLICY=events_or_calculation_stamp`. Under the service's
# default policy either backfill stamp proves the `cohort_membership` table is populated, but a
# stamp written here means only the person half is backfilled, so it routes flag evaluation for a
# cohort whose behavioral half is unseeded through an empty table: "in cohort" targeting matches
# nobody and negated targeting matches everybody.
#
# A team in the service's `REALTIME_COHORT_EVALUATION_TEAM_IDS` must also be in
# `REALTIME_COHORT_TEAM_ALLOWLIST`, because the stamps that service trusts are only invalidated on
# edit inside the allowlist guard.
#
# `cohort_person_shape_changed_supersede` covers the A->B->A revert that would otherwise stamp
# readiness over a backfill whose Stage 2 state went stale, but only on saves that maintain the
# shape hashes: an edit clearing `cohort_type` or a delete/undelete round-trip supersedes nothing.
BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED: bool = get_from_env(
    "BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED", False, type_cast=str_to_bool
)
# Bounds one finalizer pass: held runs come back every pass, so an unbounded scan would grow with a
# stalled seeder instead of staying proportional to what a pass can actually resolve. Split evenly
# across the finalizable kinds, so opening the person readiness gate halves the behavioral share.
BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS: int = get_from_env(
    "BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS", 500, type_cast=int
)
