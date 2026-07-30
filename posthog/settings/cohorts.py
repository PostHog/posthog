import os

from posthog.settings.utils import get_from_env, str_to_bool

# Off by default ("none"); enable per environment via the env override
# A set-but-empty value survives as "", which the parser reads as "all teams".
REALTIME_COHORT_TEAM_ALLOWLIST: str = os.getenv("REALTIME_COHORT_TEAM_ALLOWLIST", "none")
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
# Bounds one finalizer pass: held runs come back every pass, so an unbounded scan would grow with a
# stalled seeder instead of staying proportional to what a pass can actually resolve.
BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS: int = get_from_env(
    "BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS", 500, type_cast=int
)
