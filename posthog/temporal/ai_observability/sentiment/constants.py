"""Constants for sentiment classification."""

import os
from pathlib import Path


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return max(1, value)


# Model
MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment-latest"
MODEL_MAX_TOKENS = 512  # context window for the cardiffnlp model
LABELS = ["negative", "neutral", "positive"]
ONNX_CACHE_DIR = Path(os.environ.get("POSTHOG_SENTIMENT_MODEL_CACHE", "/tmp/posthog-sentiment-onnx-cache"))
ONNX_INTRA_OP_NUM_THREADS = _positive_int_env("POSTHOG_SENTIMENT_ONNX_INTRA_OP_NUM_THREADS", 1)
ONNX_INTER_OP_NUM_THREADS = _positive_int_env("POSTHOG_SENTIMENT_ONNX_INTER_OP_NUM_THREADS", 1)

# Label selection
# A polar label (negative/positive) must beat neutral by more than this margin to be
# assigned; otherwise the message is treated as neutral. Short, task-focused messages
# often split near-evenly between neutral and a polar label, and promoting those
# coin-flips to negative/positive is the main source of false polar labels.
SENTIMENT_NEUTRAL_MARGIN = 0.15

# Extraction bounds
MAX_USER_MESSAGES = 50
MAX_MESSAGE_CHARS = 2000
SENTIMENT_EVAL_MAX_USER_MESSAGES = 1
SENTIMENT_EVAL_MAX_MESSAGE_CHARS = 1000
SENTIMENT_EVAL_MESSAGE_HEAD_CHARS = 300

# Batch classification
CLASSIFY_BATCH_SIZE = 32  # texts per ONNX forward pass
