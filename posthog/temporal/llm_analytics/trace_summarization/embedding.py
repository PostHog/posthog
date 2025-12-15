"""Activity for generating embeddings for trace summaries."""

import asyncio
from datetime import datetime, timedelta

import structlog
import temporalio

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.models import (
    EmbeddingActivityResult,
    SingleEmbeddingResult,
    SummaryRow,
)

from ee.hogai.llm_traces_summaries.constants import LLM_TRACES_SUMMARIES_DOCUMENT_TYPE, LLM_TRACES_SUMMARIES_PRODUCT
from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def embed_summaries_activity(
    trace_ids: list[str],
    team_id: int,
    mode: str,
    workflow_start_time: str,
) -> EmbeddingActivityResult:
    """
    Fetch summaries from ClickHouse using HogQL and queue embeddings via Kafka.

    Uses workflow_start_time to efficiently filter events to a narrow time window.
    """

    def _fetch_summaries_and_setup(
        trace_ids: list[str], team_id: int, mode: str, workflow_start_time: str
    ) -> tuple[list[SummaryRow], LLMTracesSummarizerEmbedder, str]:
        """Fetch summaries using HogQL and setup embedder (sync operations)."""
        team = Team.objects.get(id=team_id)

        # Calculate time window for efficient filtering
        start_dt = datetime.fromisoformat(workflow_start_time.replace("Z", "+00:00"))
        time_from = start_dt - timedelta(minutes=constants.EMBEDDING_QUERY_BUFFER_BEFORE_MINUTES)
        time_to = start_dt + timedelta(
            minutes=constants.WORKFLOW_EXECUTION_TIMEOUT_MINUTES + constants.EMBEDDING_QUERY_BUFFER_AFTER_MINUTES
        )

        # Build HogQL query for fetching summaries
        # Always filter for 'detailed' mode to get richest embeddings
        query = parse_select(
            """
            SELECT
                properties.$ai_trace_id as trace_id,
                properties.$ai_summary_title as title,
                properties.$ai_summary_flow_diagram as flow_diagram,
                properties.$ai_summary_bullets as bullets,
                properties.$ai_summary_interesting_notes as notes
            FROM events
            WHERE event = {event_name}
                AND properties.$ai_trace_id IN {trace_ids}
                AND properties.$ai_summary_mode = {summary_mode}
                AND timestamp >= {time_from}
                AND timestamp <= {time_to}
            ORDER BY timestamp DESC
            """
        )

        # Build trace_ids tuple for IN clause
        trace_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=tid) for tid in trace_ids])

        # Execute query with proper tagging
        with tags_context(product=Product.LLM_ANALYTICS):
            result = execute_hogql_query(
                query_type="TraceSummariesForEmbedding",
                query=query,
                placeholders={
                    "event_name": ast.Constant(value=constants.EVENT_NAME_TRACE_SUMMARY),
                    "trace_ids": trace_ids_tuple,
                    "summary_mode": ast.Constant(value=constants.DEFAULT_MODE),
                    "time_from": ast.Constant(value=time_from),
                    "time_to": ast.Constant(value=time_to),
                },
                team=team,
            )

        embedder = LLMTracesSummarizerEmbedder(team=team)
        rendering = f"llma_trace_{mode}"

        return result.results or [], embedder, rendering

    async def generate_single_embedding(row: SummaryRow) -> SingleEmbeddingResult:
        """Generate a single embedding with error handling."""
        trace_id, title, flow_diagram, bullets, notes = row

        # Format summary text for embedding
        parts = []
        if title:
            parts.append(f"Title: {title}")
        if flow_diagram:
            parts.append(f"\nFlow:\n{flow_diagram}")
        if bullets:
            parts.append(f"\nSummary:\n{bullets}")
        if notes:
            parts.append(f"\nInteresting Notes:\n{notes}")

        summary_text = "\n".join(parts)

        try:
            # Use embedder's _embed_document method to send to Kafka
            await database_sync_to_async(embedder._embed_document, thread_sensitive=False)(
                content=summary_text,
                document_id=trace_id,
                document_type=LLM_TRACES_SUMMARIES_DOCUMENT_TYPE,
                rendering=rendering,
                product=LLM_TRACES_SUMMARIES_PRODUCT,
            )
            return SingleEmbeddingResult(success=True, trace_id=trace_id)
        except Exception as e:
            logger.exception(
                "Failed to generate embedding",
                trace_id=trace_id,
                error=str(e),
            )
            return SingleEmbeddingResult(success=False, trace_id=trace_id, error=str(e))

    # Early return if no traces to embed (avoids ClickHouse IN [] error)
    if not trace_ids:
        return EmbeddingActivityResult(embeddings_requested=0, embeddings_failed=0)

    # Fetch data and setup embedder (sync operations wrapped)
    results, embedder, rendering = await database_sync_to_async(_fetch_summaries_and_setup, thread_sensitive=False)(
        trace_ids=trace_ids,
        team_id=team_id,
        mode=mode,
        workflow_start_time=workflow_start_time,
    )

    # Execute all embedding tasks in parallel
    embedding_results = await asyncio.gather(
        *[generate_single_embedding(row) for row in results],
        return_exceptions=False,  # We handle exceptions in the helper
    )

    # Count successes and failures
    embeddings_requested = len(embedding_results)
    embeddings_failed = sum(1 for r in embedding_results if not r.success)

    return EmbeddingActivityResult(
        embeddings_requested=embeddings_requested,
        embeddings_failed=embeddings_failed,
    )
