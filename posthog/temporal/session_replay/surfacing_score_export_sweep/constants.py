"""Static config for the surfacing-score export sweep: daily export of scored
sessions from `session_replay_events` to the ML-account S3 bucket as
dt-partitioned Parquet, keyed by the real team and session ids the v2 ML
mirror uses."""

from datetime import date, timedelta

from posthog.temporal.session_replay.surfacing_score_export_sweep.session_identifier_format import (
    RAW_SESSION_IDENTIFIERS_START,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import SCORE_LOOKBACK_DAYS

WORKFLOW_NAME = "surfacing-score-export-sweep"
SCHEDULE_ID = "surfacing-score-export-sweep"
SCHEDULE_TYPE = "surfacing-score-export-sweep"

SCHEDULE_INTERVAL = timedelta(days=1)
# Offset from midnight UTC so near-boundary sessions are scored before their day is first exported.
SCHEDULE_OFFSET = timedelta(hours=2)

EXPORT_FLOOR_DAY = RAW_SESSION_IDENTIFIERS_START.date()

# Scores land up to SCORE_LOOKBACK_DAYS after session start, so re-export the trailing window each run.
REEXPORT_WINDOW_DAYS = SCORE_LOOKBACK_DAYS + 1

# Keep the cutoff day reachable during the deployment window.
BACKFILL_UNTIL = date(2026, 10, 1)

# `cityHash64(session_id) % OF_CHUNKS` partitioning, same scheme as the scoring sweep.
DEFAULT_OF_CHUNKS = 8

# Keep this background export within a small share of the shared ClickHouse query capacity.
MAX_CONCURRENT_EXPORT_PARTITIONS = 4

SCORE_EXPORT_PREFIX_ENV_VAR = "SESSION_RECORDING_ML_SCORE_EXPORT_PREFIX"
# Must stay under `score/`: the ML bucket policy grants the exporter `score/*` only.
DEFAULT_SCORE_EXPORT_PREFIX = "score/v2"

CH_EXPORT_QUERY_TIMEOUT_S = 120
CH_EXPORT_QUERY_MAX_MEMORY_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB

# Keyset-pagination page size — bounds worker memory and per-query result size per
# fetch (~100 B/row, so a full page is low hundreds of MB of Python objects).
# Sized so typical partitions are single-page and pagination only engages on outliers.
EXPORT_PAGE_MAX_ROWS = 500_000

LIST_PARTITIONS_ACTIVITY_TIMEOUT = timedelta(seconds=30)
EXPORT_PARTITION_ACTIVITY_TIMEOUT = timedelta(minutes=20)
EXPORT_PARTITION_MAX_ATTEMPTS = 3

# > CH_EXPORT_QUERY_TIMEOUT_S — heartbeats fire between page fetches, not during a SELECT.
EXPORT_PARTITION_HEARTBEAT_TIMEOUT = timedelta(minutes=3)

# Leave enough time for every bounded wave to exhaust its activity retry budget,
# plus headroom for planning, retry backoff, and workflow task scheduling.
_MAX_EXPORT_DAYS = max(REEXPORT_WINDOW_DAYS, (BACKFILL_UNTIL - EXPORT_FLOOR_DAY).days - 1)
_MAX_PARTITIONS_PER_SWEEP = _MAX_EXPORT_DAYS * DEFAULT_OF_CHUNKS
_MAX_PARTITION_WAVES = (
    _MAX_PARTITIONS_PER_SWEEP + MAX_CONCURRENT_EXPORT_PARTITIONS - 1
) // MAX_CONCURRENT_EXPORT_PARTITIONS
WORKFLOW_EXECUTION_TIMEOUT = (
    _MAX_PARTITION_WAVES * EXPORT_PARTITION_ACTIVITY_TIMEOUT * EXPORT_PARTITION_MAX_ATTEMPTS + timedelta(hours=1)
)
