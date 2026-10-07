"""
LLM and embedding cost telemetry for business knowledge.

Every event carries ``ai_product=business_knowledge`` and an ``ai_feature``.
Ingestion events also carry the document (the resource) and its source, so
cost can be summed per resource. Retrieval events from one search share one
trace, so cost can be summed per search.
"""

import math
import dataclasses
from collections.abc import Iterable, Mapping
from typing import Any, Literal
from uuid import UUID, uuid4

import structlog
import posthoganalytics
from posthoganalytics.ai.langchain.callbacks import CallbackHandler

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import team_distinct_id

logger = structlog.get_logger(__name__)

BK_AI_PRODUCT = "business_knowledge"

INGEST_SAFETY_FEATURE = "bk_ingest_safety"
INGEST_EMBEDDING_FEATURE = "bk_ingest_embedding"
INGEST_EMBEDDING_REFRESH_FEATURE = "bk_ingest_embedding_refresh"
RETRIEVAL_EMBEDDING_FEATURE = "bk_retrieval_embedding"
RETRIEVAL_RERANK_FEATURE = "bk_retrieval_rerank"

# The LLM analytics cost table prices the OpenAI model name. The "-1536" suffix
# on BK_EMBEDDING_MODEL names the vector size of our ClickHouse table only.
EMBEDDING_COST_MODEL = "text-embedding-3-small"
EMBEDDING_COST_PROVIDER = "openai"
# The Kafka embedding path returns no token usage, so ingestion estimates it.
CHARS_PER_TOKEN_ESTIMATE = 4

RetrievalSurface = Literal["api", "support", "posthog_ai", "docs_shadow"]
EventProperties = dict[str, str | int]


@frozen
class RetrievalTrace:
    """One search. The query embedding and the rerank of that search share the trace."""

    surface: RetrievalSurface
    trace_id: str = dataclasses.field(default_factory=lambda: str(uuid4()))


def ingest_properties(
    *, team_id: int, document_id: UUID, source_id: UUID, source_type: str, feature: str
) -> EventProperties:
    return {
        "ai_product": BK_AI_PRODUCT,
        "ai_feature": feature,
        "team_id": team_id,
        "document_id": str(document_id),
        "source_id": str(source_id),
        "source_type": source_type,
    }


def retrieval_properties(*, team_id: int, trace: RetrievalTrace, feature: str) -> EventProperties:
    return {
        "ai_product": BK_AI_PRODUCT,
        "ai_feature": feature,
        "team_id": team_id,
        "surface": trace.surface,
    }


def estimate_tokens(texts: Iterable[str]) -> int:
    return math.ceil(sum(len(text) for text in texts) / CHARS_PER_TOKEN_ESTIMATE)


def capture_embedding(*, team_id: int, input_tokens: int, trace_id: str, properties: Mapping[str, str | int]) -> None:
    """Capture an ``$ai_embedding`` event. LLM analytics ingestion adds ``$ai_total_cost_usd`` from the tokens."""
    try:
        # Only the AI ingestion pipeline prices events, so this uses the AI lane like the SDK's model wrappers.
        posthoganalytics.capture_ai(
            "$ai_embedding",
            distinct_id=team_distinct_id(team_id),
            properties={
                "$ai_model": EMBEDDING_COST_MODEL,
                "$ai_provider": EMBEDDING_COST_PROVIDER,
                "$ai_input_tokens": input_tokens,
                "$ai_trace_id": trace_id,
                "$process_person_profile": False,
                **properties,
            },
        )
    except Exception:
        logger.warning("business_knowledge.embedding_cost_capture_failed", team_id=team_id, exc_info=True)


class _QuietCallbackHandler(CallbackHandler):
    """
    Records successful generations only. On a model error the base handler
    records the error message and calls ``capture_exception``. That message can
    contain prompt or output text, which privacy mode does not redact, and every
    caller here already handles the failure itself. The base handler also logs
    every prompt at DEBUG level, which privacy mode does not redact either.
    """

    def _log_debug_event(
        self,
        event_name: str,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        _ = event_name, run_id, parent_run_id, kwargs

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        _ = error, run_id, parent_run_id, kwargs

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        _ = error, run_id, parent_run_id, kwargs


def trace_callback(team_id: int, *, trace_id: str, properties: Mapping[str, str | int]) -> CallbackHandler | None:
    """LangChain callback that captures ``$ai_generation`` for a model call made outside a PostHog AI graph."""
    # default_client stays None until the first module-level capture.
    client = posthoganalytics.default_client
    if client is None and not posthoganalytics.disabled:
        client = posthoganalytics.setup()
    if client is None:
        return None
    return _QuietCallbackHandler(
        client,
        distinct_id=team_distinct_id(team_id),
        trace_id=trace_id,
        # Prompts and outputs contain customer content, so only token counts reach analytics.
        privacy_mode=True,
        properties=dict(properties),
    )
