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

# Severity ordering for "worst" aggregation (higher = worse)
SEVERITY = {"negative": 2, "neutral": 1, "positive": 0}

# Temporal retry / timeout
RETRY_MAX_ATTEMPTS = 3
RETRY_INITIAL_INTERVAL = timedelta(seconds=5)
RETRY_MAX_INTERVAL = timedelta(seconds=30)
RETRY_BACKOFF_COEFFICIENT = 2.0
ACTIVITY_TIMEOUT = timedelta(minutes=5)
