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
MAX_GENERATIONS = 50  # ClickHouse LIMIT for generation events per trace
QUERY_LOOKBACK_DAYS = 30  # timestamp filter to enable partition pruning

# Temporal workflow/activity config
WORKFLOW_NAME = "llma-sentiment-classify"
ACTIVITY_TIMEOUT_SECONDS = 60  # start-to-close timeout for classify activity
WORKFLOW_TIMEOUT_SINGLE_SECONDS = 30  # task timeout when API calls for a single trace
WORKFLOW_TIMEOUT_BATCH_SECONDS = 60  # task timeout when API calls for a batch
MAX_RETRY_ATTEMPTS = 2  # retry policy for both workflow and activity

# API config
CACHE_TTL = 60 * 60 * 24  # 24 hours — events are immutable once ingested
BATCH_MAX_TRACE_IDS = 25

# HogQL query template for fetching $ai_generation events
GENERATIONS_QUERY = """
    SELECT uuid, properties, properties.$ai_trace_id AS trace_id
    FROM events
    WHERE event = '$ai_generation'
      AND timestamp >= toDateTime({date_from}, 'UTC')
      AND timestamp <= toDateTime({date_to}, 'UTC')
      AND properties.$ai_trace_id IN {trace_ids}
    ORDER BY trace_id, timestamp DESC
    LIMIT {max_rows}
"""
