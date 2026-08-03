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
# Whether the finalizer may terminalize person-property runs and stamp
# `last_backfill_person_properties_at`. Separate from the finalizer gate above, which is already on
# for behavioral runs, so this is the only thing standing between an enabled person seed path and a
# live person stamp.
#
# Keep it off until the flags service stops accepting that stamp as proof the membership table is
# populated. `Cohort::uses_realtime_membership` takes *either* backfill timestamp, because ~19k
# cohorts still carry a person stamp written by the legacy realtime workflow before #57545 removed
# that write, and for those it correctly means "the legacy pipeline computed this cohort into
# cohort_membership". A stamp written here means something different: only the person half is
# backfilled. Until the two can be told apart, a person stamp landing on a cohort whose behavioral
# half is unseeded routes flag evaluation through `cohort_membership` anyway, which under-matches
# "in cohort" targeting and over-matches negated targeting. `Cohort.is_flag_compatible` fail-closes
# on this; the flags service does not.
#
# Also keep it off until a person-leaf edit supersedes the cohort's active person-property runs,
# the way `_supersede_cohort_events_backfills` does for behavioral ones (the B7.3b receiver).
# Without that, the person stamp's only edit-time fence is the hash CAS in `_stamp_readiness`,
# which passes again after an A->B->A revert and stamps readiness over a backfill whose Stage 2
# state went stale in the B window — the `superseded_at` refusal that closes this for behavioral
# runs never fires because nothing sets it on the person path.
BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED: bool = get_from_env(
    "BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED", False, type_cast=str_to_bool
)
# Bounds one finalizer pass: held runs come back every pass, so an unbounded scan would grow with a
# stalled seeder instead of staying proportional to what a pass can actually resolve. Split evenly
# across the finalizable kinds, so opening the person readiness gate halves the behavioral share.
BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS: int = get_from_env(
    "BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS", 500, type_cast=int
)
