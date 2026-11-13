"""Sentiment classification using cardiffnlp/twitter-roberta-base-sentiment-latest.

Uses ONNX Runtime for inference (~60MB) instead of PyTorch (~2GB).
Loads the pre-baked ONNX model once per worker process (singleton)
and provides a classify function that returns three-class
sentiment scores.

The ONNX model is baked into the Docker image at build time
(see Dockerfile.llm-analytics). The worker expects it at ONNX_CACHE_DIR.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog

from posthog.hogql_queries.ai.sentiment_labeling import select_sentiment_label
from posthog.temporal.ai_observability.sentiment.constants import (
    CLASSIFY_BATCH_SIZE,
    INFERENCE_THREADS,
    LABELS,
    MODEL_MAX_TOKENS,
    MODEL_NAME,
    ONNX_CACHE_DIR,
    ONNX_INTER_OP_NUM_THREADS,
    ONNX_INTRA_OP_NUM_THREADS,
)
from posthog.temporal.ai_observability.sentiment.schema import SentimentResult

logger = structlog.get_logger(__name__)

_model_lock = threading.Lock()
_model_cache: dict[str, Any] = {}
# ONNX Runtime sessions are thread-safe, but the Rust fast tokenizer is not ("Already borrowed"
# when two threads share one). Threads share the model and each builds its own pipeline.
_thread_state = threading.local()
# Runs inference off the event loop's default executor, so that evals waiting for inference
# never hold the threads that event fetches and hog evals use.
inference_executor = ThreadPoolExecutor(max_workers=INFERENCE_THREADS, thread_name_prefix="sentiment-inference")


def _load_model() -> Any:
    """Load the pre-baked ONNX sentiment model. Called once per worker.

    Uses double-checked locking to ensure only one thread loads the model.
    Raises FileNotFoundError if the ONNX model is missing from the expected
    cache directory — this means the Docker image was not built correctly.
    """
    if "model" in _model_cache:
        return _model_cache["model"]

    with _model_lock:
        if "model" in _model_cache:
            return _model_cache["model"]

        cache_dir = str(ONNX_CACHE_DIR)
        onnx_path = ONNX_CACHE_DIR / "model.onnx"

        if not onnx_path.exists():
            logger.error(
                "ONNX model not found — the Docker image must bake the model at build time",
                expected_path=str(onnx_path),
                cache_dir=cache_dir,
            )
            raise FileNotFoundError(
                f"Sentiment ONNX model not found at {onnx_path}. "
                f"Ensure Dockerfile.llm-analytics bakes the model into {ONNX_CACHE_DIR}."
            )

        from onnxruntime import SessionOptions
        from optimum.onnxruntime import ORTModelForSequenceClassification

        session_options = SessionOptions()
        session_options.intra_op_num_threads = ONNX_INTRA_OP_NUM_THREADS
        session_options.inter_op_num_threads = ONNX_INTER_OP_NUM_THREADS
        # bf16 matrix math, which only takes effect on arm64 CPUs with bf16 instructions (Graviton3).
        # Labels matched fp32 on 399 of 400 test messages.
        session_options.add_session_config_entry("mlas.enable_gemm_fastmath_arm64_bfloat16", "1")

        logger.info(
            "Loading sentiment model from ONNX cache",
            cache_dir=cache_dir,
            onnx_intra_op_threads=ONNX_INTRA_OP_NUM_THREADS,
            onnx_inter_op_threads=ONNX_INTER_OP_NUM_THREADS,
        )
        _model_cache["model"] = ORTModelForSequenceClassification.from_pretrained(
            cache_dir, session_options=session_options
        )

        logger.info("Sentiment model loaded", model=MODEL_NAME)
        return _model_cache["model"]


def _build_pipeline(model: Any) -> Any:
    from transformers import AutoTokenizer, pipeline

    return pipeline(
        "sentiment-analysis",
        model=model,
        tokenizer=AutoTokenizer.from_pretrained(str(ONNX_CACHE_DIR)),
        top_k=None,
        truncation=True,
        max_length=MODEL_MAX_TOKENS,
    )


def _thread_pipeline() -> Any:
    pipe = getattr(_thread_state, "pipe", None)
    if pipe is None:
        pipe = _thread_state.pipe = _build_pipeline(_load_model())
    return pipe


def _parse_single_result(scores_list: list[dict[str, Any]]) -> SentimentResult:
    """Convert a pipeline output for one text into a SentimentResult."""
    scores: dict[str, float] = {}
    for item in scores_list:
        scores[item["label"]] = round(item["score"], 4)

    for label in LABELS:
        if label not in scores:
            scores[label] = 0.0

    label = select_sentiment_label(scores)
    return SentimentResult(label=label, score=scores[label], scores=scores)


def classify(texts: list[str]) -> list[SentimentResult]:
    """Classify a batch of texts. The pipeline handles internal chunking."""
    if not texts:
        return []

    # Pipeline with top_k=None returns list of list[dict] for batch input
    batch_results = _thread_pipeline()(texts, batch_size=CLASSIFY_BATCH_SIZE)
    return [_parse_single_result(result) for result in batch_results]
