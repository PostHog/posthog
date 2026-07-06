"""Static config for the surfacing-score export sweep.

Once a day, export every scored session (the `surfacing_score` column on
`session_replay_events`) to the ML-account S3 bucket as dt-partitioned
Parquet, keyed by the same pseudonymous ids as the session replay ML mirror
(see `nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/`), so the ML
side can join scores onto the mirrored replay dataset.
"""

from datetime import date, timedelta

from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import SCORE_LOOKBACK_DAYS

WORKFLOW_NAME = "surfacing-score-export-sweep"
SCHEDULE_ID = "surfacing-score-export-sweep"
SCHEDULE_TYPE = "surfacing-score-export-sweep"

# Daily, offset from midnight UTC so sessions that started just before the
# day boundary have had time to be scored before their day is first exported.
SCHEDULE_INTERVAL = timedelta(days=1)
SCHEDULE_OFFSET = timedelta(hours=2)

# Only sessions started strictly after July 3rd, 2026 (UTC) are exported —
# this is the first exported day partition.
EXPORT_FLOOR_DAY = date(2026, 7, 4)

# Scores land up to SCORE_LOOKBACK_DAYS after a session starts, so each run
# re-exports the trailing window (deterministic object keys make the
# overwrite idempotent). +1 covers the day-boundary straddle.
REEXPORT_WINDOW_DAYS = SCORE_LOOKBACK_DAYS + 1

# Deterministic hash partitioning over `cityHash64(session_id) % OF_CHUNKS`,
# same scheme as the scoring sweep. Bounds per-activity row volume so one
# day's export never has to hold every scored session in memory at once.
DEFAULT_OF_CHUNKS = 8

# Objects land at `{prefix}/dt=YYYY-MM-DD/part-*.parquet`, a sibling of the
# ML mirror's `block-metadata/` dataset in the same bucket.
SCORE_EXPORT_PREFIX_ENV_VAR = "SESSION_RECORDING_ML_SCORE_EXPORT_PREFIX"
DEFAULT_SCORE_EXPORT_PREFIX = "score"

# ClickHouse query budget — same rationale as the scoring sweep: a background
# job must never compete with interactive queries for cluster memory.
CH_EXPORT_QUERY_TIMEOUT_S = 120
CH_EXPORT_QUERY_MAX_MEMORY_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB

LIST_PARTITIONS_ACTIVITY_TIMEOUT = timedelta(seconds=30)
# CH read + Parquet encode + S3 put for one (day, chunk) slice.
EXPORT_PARTITION_ACTIVITY_TIMEOUT = timedelta(minutes=10)
# > CH_EXPORT_QUERY_TIMEOUT_S (no heartbeat during the SELECT).
EXPORT_PARTITION_HEARTBEAT_TIMEOUT = timedelta(minutes=3)

# Daily cadence leaves plenty of headroom; must outlive the slowest partition.
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=30)
