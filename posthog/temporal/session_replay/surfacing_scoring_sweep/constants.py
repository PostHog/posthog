"""Static config for the session surfacing scoring pipeline.

The pipeline runs on a fixed Schedule (every SCHEDULE_INTERVAL) and per tick
scores up to TARGET_SESSIONS_PER_TICK unscored sessions, sharded into
DEFAULT_OF_CHUNKS deterministic hash buckets.
"""

from datetime import timedelta

WORKFLOW_NAME = "score-sessions-batch"
SCHEDULE_ID = "surfacing-scoring-sweep-batch"
SCHEDULE_TYPE = "surfacing-scoring-sweep"

MODEL_S3_KEY = "surfacing-scoring/surfacing_score_xgb_v1.ubj"

# Pipeline cadence. Must align with the consumer's freshness expectation —
# 5m gives the model 5 minutes of headroom between fetch and re-tick, which
# is comfortable for chunks of TARGET_CHUNK_SIZE on a single libomp worker.
SCHEDULE_INTERVAL = timedelta(minutes=5)

# Per-tick budget. The pipeline will pick up to this many unscored sessions per
# tick across all chunks. Sized so the schedule keeps up with steady-state
# session creation; transient backlogs drain across consecutive ticks.
TARGET_SESSIONS_PER_TICK = 200_000

# Deterministic hash partitioning over `cityHash64(session_id) % DEFAULT_OF_CHUNKS`.
# 20 buckets × ~10k sessions = TARGET_SESSIONS_PER_TICK, matched to a 5min budget.
# Skew is bounded by hash uniformity (~10% per-bucket variance is normal).
DEFAULT_OF_CHUNKS = 20
TARGET_CHUNK_SIZE = TARGET_SESSIONS_PER_TICK // DEFAULT_OF_CHUNKS

# Window for "score eligible" rows. Older sessions are intentionally left
# unscored — if a session hasn't been scored within this window its features
# are no longer useful for downstream summarization.
SCORE_LOOKBACK_DAYS = 7

# ClickHouse query budget. Enforced server-side via `max_execution_time` so a
# runaway scan can't eat the whole activity timeout.
CH_FEATURE_QUERY_TIMEOUT_S = 60

# Server-side memory ceiling for the sweep queries. A background job must
# never compete with interactive queries for cluster memory — better to fail
# the chunk (it retries next tick) than to OOM a shard.
CH_FEATURE_QUERY_MAX_MEMORY_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB

# librdkafka flush budget after producing a chunk. Kafka writeback is async —
# `produce()` enqueues, `flush()` blocks until every message has been ack'd by
# the broker. 30s leaves headroom for a one-replica-down hiccup without busting
# the activity timeout (4m).
KAFKA_PRODUCE_FLUSH_TIMEOUT_S = 30

# Activity timeouts. Sized for chunks of TARGET_CHUNK_SIZE on libomp-parallel
# XGBoost predict (CH read ~10s + predict ~1s + Kafka produce+flush ~5s = ~20s
# typical). The 4-minute ceiling absorbs CH replica failover / one slow shard /
# a Kafka leader election.
SCORE_CHUNK_ACTIVITY_TIMEOUT = timedelta(minutes=4)
# > CH_FEATURE_QUERY_TIMEOUT_S (no heartbeat during the SELECT)
SCORE_CHUNK_HEARTBEAT_TIMEOUT = timedelta(seconds=90)
LIST_CHUNKS_ACTIVITY_TIMEOUT = timedelta(seconds=30)

# Parent workflow has to outlive its longest in-flight chunk activity, but
# must not stretch into the next 5-min tick.
WORKFLOW_EXECUTION_TIMEOUT = timedelta(minutes=4, seconds=30)
