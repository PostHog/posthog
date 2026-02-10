"""Constants for sentiment classification."""

import os
from datetime import timedelta
from pathlib import Path

# Model
MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment-latest"
LABELS = ["negative", "neutral", "positive"]
ONNX_CACHE_DIR = Path(os.environ.get("POSTHOG_SENTIMENT_MODEL_CACHE", "/tmp/posthog-sentiment-onnx-cache"))

# Extraction bounds
MAX_USER_MESSAGES = 50
MAX_MESSAGE_CHARS = 2000

# Temporal retry policy — sentiment is best-effort so we keep retries low
# to avoid queue pressure under load. Better to drop a sentiment event than
# to block the queue retrying.
RETRY_MAX_ATTEMPTS = 2
RETRY_INITIAL_INTERVAL = timedelta(seconds=2)
RETRY_MAX_INTERVAL = timedelta(seconds=10)
RETRY_BACKOFF_COEFFICIENT = 2.0

# Batch size cap — scheduler will never send more than this many events per workflow
MAX_BATCH_SIZE = 100

# Activity timeouts — sized for batch processing (up to MAX_BATCH_SIZE events)
# start_to_close: max wall-clock time for a single activity attempt
# schedule_to_close: max total time including retries (caps overall wait)
# heartbeat: detect stuck ONNX inference early instead of waiting for full timeout
ACTIVITY_START_TO_CLOSE_TIMEOUT = timedelta(minutes=10)
ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT = timedelta(minutes=20)
ACTIVITY_HEARTBEAT_TIMEOUT = timedelta(seconds=60)
