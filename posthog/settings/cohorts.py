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
