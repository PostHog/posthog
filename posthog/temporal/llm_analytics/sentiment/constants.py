"""Constants for sentiment classification."""

import os
from pathlib import Path

# Model
MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment-latest"
LABELS = ["negative", "neutral", "positive"]
ONNX_CACHE_DIR = Path(os.environ.get("POSTHOG_SENTIMENT_MODEL_CACHE", "/tmp/posthog-sentiment-onnx-cache"))

# Extraction bounds
MAX_USER_MESSAGES = 50
MAX_MESSAGE_CHARS = 2000

# Batch classification
CLASSIFY_BATCH_SIZE = 32  # texts per ONNX forward pass
MAX_TOTAL_CLASSIFICATIONS = 200  # hard cap on classify() calls per trace
MAX_GENERATIONS = 50  # ClickHouse LIMIT for generation events per trace
QUERY_LOOKBACK_DAYS = 30  # timestamp filter to enable partition pruning
