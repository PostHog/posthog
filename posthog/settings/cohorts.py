from posthog.settings.utils import get_from_env, str_to_bool

REALTIME_COHORT_TEAM_ALLOWLIST: str = get_from_env("REALTIME_COHORT_TEAM_ALLOWLIST", "2")
BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED: bool = get_from_env(
    "BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED", False, type_cast=str_to_bool
)
BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED: bool = get_from_env(
    "BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED", False, type_cast=str_to_bool
)
