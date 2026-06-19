"""Constants for sentiment classification."""

import os
from pathlib import Path

# Model
MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment-latest"
MODEL_MAX_TOKENS = 512  # context window for the cardiffnlp model
LABELS = ["negative", "neutral", "positive"]
ONNX_CACHE_DIR = Path(os.environ.get("POSTHOG_SENTIMENT_MODEL_CACHE", "/tmp/posthog-sentiment-onnx-cache"))

# Extraction bounds
MAX_USER_MESSAGES = 50
MAX_MESSAGE_CHARS = 2000

# Batch classification
CLASSIFY_BATCH_SIZE = 32  # texts per ONNX forward pass
MAX_CLASSIFICATIONS_PER_TRACE = 200
MAX_GENERATIONS_PER_TRACE = 10  # per-trace cap enforced by window function in ClickHouse
MAX_INPUT_CHARS = 300_000  # skip $ai_input longer than this (covers p99; extraction truncates before inference)
MAX_INPUT_CHARS_GENERATION = 1_000_000  # higher limit for generation-level — user asked for specific UUIDs
QUERY_LOOKBACK_DAYS = 7  # fallback timestamp filter when caller omits date range

# Temporal workflow/activity config
WORKFLOW_NAME = "llma-sentiment-classify"
ACTIVITY_TIMEOUT_SECONDS = 120  # start-to-close timeout for classify activity
ACTIVITY_SCHEDULE_TO_START_TIMEOUT_SECONDS = 30  # fail fast if no worker picks up the activity
WORKFLOW_TIMEOUT_BATCH_SECONDS = 120  # task timeout for sentiment workflow
MAX_RETRY_ATTEMPTS = 2  # retry policy for both workflow and activity

# Cache config
CACHE_TTL = 60 * 60 * 24  # 24 hours — events are immutable once ingested
CACHE_KEY_PREFIX = "llma_sentiment"  # key format: {prefix}:{level}:{team_id}:{id}

# API config
BATCH_MAX_TRACE_IDS = 5
BATCH_MAX_GENERATION_IDS = 5  # keep small to avoid upstream request timeouts

# HogQL query template for fetching $ai_generation events.
# Uses a window function to cap rows per trace at the ClickHouse level,
# and a size filter to skip accumulated conversation histories — the same
# user messages appear in earlier, smaller generations so we lose nothing.
#
# Reads from `posthog.ai_events` so post-strip rows still expose the heavy
# `input` column (it's stripped from `events.properties.$ai_input` after
# the cutover). `execute_with_ai_events_fallback` rewrites this back to
# `events.properties.$ai_*` for the shared-table fallback.
GENERATIONS_QUERY = """
    SELECT uuid, ai_input, trace_id
    FROM (
        SELECT
            uuid,
            input AS ai_input,
            trace_id,
            row_number() OVER (
                PARTITION BY trace_id
                ORDER BY timestamp DESC
            ) AS rn
        FROM posthog.ai_events AS ai_events
        WHERE event = '$ai_generation'
          AND timestamp >= toDateTime({date_from}, 'UTC')
          AND timestamp <= toDateTime({date_to}, 'UTC')
          AND trace_id IN {trace_ids}
          -- skip huge accumulated conversation histories
          AND length(input) <= {max_input_chars}
    )
    -- last N qualified generations per trace
    WHERE rn <= {max_gens_per_trace}
    ORDER BY trace_id, rn
"""

# Fetch specific generation events by UUID — no window function needed.
# No length() filter here: on the events fallback it translates to
# JSONExtractRaw on every scanned row which is expensive on high-volume
# teams (benchmarked 2.4x slower). The size check is applied post-fetch
# in Python instead.
GENERATIONS_BY_UUID_QUERY = """
    SELECT
        uuid,
        input AS ai_input
    FROM posthog.ai_events AS ai_events
    WHERE event = '$ai_generation'
      AND trace_id IN {trace_ids}
      AND timestamp >= toDateTime({date_from}, 'UTC')
      AND timestamp <= toDateTime({date_to}, 'UTC')
      AND uuid IN {uuids}
"""
