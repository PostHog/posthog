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
MAX_INPUT_BYTES = 50_000  # skip $ai_input payloads larger than this (accumulated conversation histories)
MIN_INPUT_BYTES = 100  # skip tiny $ai_input payloads (tool calls with no user content)
QUERY_LOOKBACK_DAYS = 30  # timestamp filter to enable partition pruning

# Temporal workflow/activity config
WORKFLOW_NAME = "llma-sentiment-classify"
ACTIVITY_TIMEOUT_SECONDS = 60  # start-to-close timeout for classify activity
WORKFLOW_TIMEOUT_BATCH_SECONDS = 60  # task timeout for sentiment workflow
MAX_RETRY_ATTEMPTS = 2  # retry policy for both workflow and activity

# API config
CACHE_TTL = 60 * 60 * 24  # 24 hours — events are immutable once ingested
BATCH_MAX_TRACE_IDS = 10

# HogQL query template for fetching $ai_generation events.
# Uses a window function to cap rows per trace at the ClickHouse level,
# and a size filter to skip tool calls (tiny) and accumulated conversation
# histories (huge) — the same user messages appear in earlier, smaller
# generations so we lose nothing.
GENERATIONS_QUERY = """
    SELECT uuid, ai_input, trace_id
    FROM (
        SELECT
            uuid,
            properties.$ai_input AS ai_input,
            properties.$ai_trace_id AS trace_id,
            row_number() OVER (
                PARTITION BY properties.$ai_trace_id
                ORDER BY timestamp DESC
            ) AS rn
        FROM events
        WHERE event = '$ai_generation'
          AND timestamp >= toDateTime({date_from}, 'UTC')
          AND timestamp <= toDateTime({date_to}, 'UTC')
          AND properties.$ai_trace_id IN {trace_ids}
          -- skip tiny tool call payloads with no user content
          AND length(properties.$ai_input) >= {min_input_bytes}
          -- skip huge accumulated conversation histories
          AND length(properties.$ai_input) <= {max_input_bytes}
    )
    -- last N qualified generations per trace
    WHERE rn <= {max_gens_per_trace}
"""
