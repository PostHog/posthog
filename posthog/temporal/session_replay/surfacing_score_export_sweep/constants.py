"""Static config for the surfacing-score export sweep: daily export of scored
sessions from `session_replay_events` to the ML-account S3 bucket as
dt-partitioned Parquet, keyed by the ML mirror's pseudonymous ids."""

from datetime import date, timedelta

from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import SCORE_LOOKBACK_DAYS

WORKFLOW_NAME = "surfacing-score-export-sweep"
SCHEDULE_ID = "surfacing-score-export-sweep"
SCHEDULE_TYPE = "surfacing-score-export-sweep"

SCHEDULE_INTERVAL = timedelta(days=1)
# Offset from midnight UTC so near-boundary sessions are scored before their day is first exported.
SCHEDULE_OFFSET = timedelta(hours=2)

# First exported day partition — sessions started strictly after July 3rd, 2026 (UTC).
EXPORT_FLOOR_DAY = date(2026, 7, 4)

# Scores land up to SCORE_LOOKBACK_DAYS after session start, so re-export the trailing window each run.
REEXPORT_WINDOW_DAYS = SCORE_LOOKBACK_DAYS + 1

# `cityHash64(session_id) % OF_CHUNKS` partitioning, same scheme as the scoring sweep.
DEFAULT_OF_CHUNKS = 8

SCORE_EXPORT_PREFIX_ENV_VAR = "SESSION_RECORDING_ML_SCORE_EXPORT_PREFIX"
DEFAULT_SCORE_EXPORT_PREFIX = "score"

CH_EXPORT_QUERY_TIMEOUT_S = 120
CH_EXPORT_QUERY_MAX_MEMORY_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB

LIST_PARTITIONS_ACTIVITY_TIMEOUT = timedelta(seconds=30)
EXPORT_PARTITION_ACTIVITY_TIMEOUT = timedelta(minutes=10)
# > CH_EXPORT_QUERY_TIMEOUT_S — no heartbeat during the SELECT.
EXPORT_PARTITION_HEARTBEAT_TIMEOUT = timedelta(minutes=3)

WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)
