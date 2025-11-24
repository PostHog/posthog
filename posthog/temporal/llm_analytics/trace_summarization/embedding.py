"""Activity for generating embeddings for trace summaries."""

import asyncio

import structlog
import temporalio

from posthog.schema import EmbeddingModelName

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    LLMA_TRACE_DETAILED_RENDERING,
    LLMA_TRACE_MINIMAL_RENDERING,
)
from posthog.temporal.llm_analytics.trace_summarization.models import TraceSummary

logger = structlog.get_logger(__name__)


def format_summary_for_embedding(summary: TraceSummary) -> str:
    """
    Format a trace summary for embedding, excluding line references.

    Combines title, flow diagram, bullets, and interesting notes into a
    single text suitable for semantic search.
    """
    parts = []

    # Title
    if summary.summary.title:
        parts.append(f"Title: {summary.summary.title}")

    # Flow diagram
    if summary.summary.flow_diagram:
        parts.append(f"\nFlow:\n{summary.summary.flow_diagram}")

    # Summary bullets (text only, no line refs)
    if summary.summary.summary_bullets:
        parts.append("\nSummary:")
        for bullet in summary.summary.summary_bullets:
            parts.append(f"• {bullet.text}")

    # Interesting notes (text only, no line refs)
    if summary.summary.interesting_notes:
        parts.append("\nInteresting Notes:")
        for note in summary.summary.interesting_notes:
            parts.append(f"• {note.text}")

    return "\n".join(parts)


@temporalio.activity.defn
async def embed_summaries_from_events_activity(
    trace_ids: list[str],
    team_id: int,
    mode: str,
    workflow_start_time: str | None = None,
) -> dict[str, int]:
    """
    Fetch summaries from ClickHouse events and generate embeddings.

    Args:
        trace_ids: List of trace IDs to fetch summaries for
        team_id: Team ID
        mode: Rendering mode (minimal or detailed)
        workflow_start_time: ISO timestamp of workflow start for efficient querying

    Returns:
        Dict with embeddings_requested and embeddings_failed counts
    """
    from posthog.clickhouse.client.connection import Workload
    from posthog.clickhouse.client.execute import sync_execute
    from posthog.models import Team
    from posthog.temporal.llm_analytics.trace_summarization import constants

    from ee.hogai.llm_traces_summaries.constants import LLM_TRACES_SUMMARIES_DOCUMENT_TYPE, LLM_TRACES_SUMMARIES_PRODUCT
    from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder

    def _fetch_summaries_and_setup():
        """Fetch summaries from ClickHouse and setup embedder (sync operations)."""
        from datetime import datetime, timedelta

        # Build timestamp filter for efficiency
        # Events are written during workflow execution, so look from 5 min before start to 10 min after
        timestamp_filter = ""
        if workflow_start_time:
            timestamp_filter = "AND timestamp >= %(time_from)s AND timestamp <= %(time_to)s"

        # Fetch summaries from ClickHouse events
        query = f"""
            SELECT
                JSONExtractString(properties, '$ai_trace_id') as trace_id,
                JSONExtractString(properties, '$ai_summary_title') as title,
                JSONExtractString(properties, '$ai_summary_flow_diagram') as flow_diagram,
                JSONExtractString(properties, '$ai_summary_bullets') as bullets,
                JSONExtractString(properties, '$ai_summary_interesting_notes') as notes
            FROM events
            WHERE team_id = %(team_id)s
                AND event = %(event_name)s
                AND JSONExtractString(properties, '$ai_trace_id') IN %(trace_ids)s
                {timestamp_filter}
            ORDER BY timestamp DESC
        """

        params = {
            "team_id": team_id,
            "event_name": constants.EVENT_NAME_TRACE_SUMMARY,
            "trace_ids": trace_ids,
        }

        # Add timestamp params if filter is active
        if workflow_start_time:
            start_dt = datetime.fromisoformat(workflow_start_time.replace("Z", "+00:00"))
            params["time_from"] = (start_dt - timedelta(minutes=5)).isoformat()
            params["time_to"] = (start_dt + timedelta(minutes=10)).isoformat()

        results = sync_execute(query, params, workload=Workload.OFFLINE)

        team = Team.objects.get(id=team_id)
        embedder = LLMTracesSummarizerEmbedder(team=team)
        rendering = f"llma_trace_{mode}"

        return results, embedder, rendering

    # Fetch data and setup embedder (sync operations wrapped)
    results, embedder, rendering = await database_sync_to_async(_fetch_summaries_and_setup, thread_sensitive=False)()

    # Process all embeddings in parallel
    async def generate_single_embedding(row):
        """Helper to generate a single embedding with error handling."""
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
            return {"success": True, "trace_id": trace_id}
        except Exception as e:
            logger.exception(
                "Failed to generate embedding",
                trace_id=trace_id,
                error=str(e),
            )
            return {"success": False, "trace_id": trace_id, "error": str(e)}

    # Execute all embedding tasks in parallel
    embedding_results = await asyncio.gather(
        *[generate_single_embedding(row) for row in results],
        return_exceptions=False,  # We handle exceptions in the helper
    )

    # Count successes and failures
    embeddings_requested = len(embedding_results)
    embeddings_failed = sum(1 for r in embedding_results if not r["success"])

    return {
        "embeddings_requested": embeddings_requested,
        "embeddings_failed": embeddings_failed,
    }


@temporalio.activity.defn
async def embed_summaries_activity(
    summaries: list[TraceSummary],
    team_id: int,
    mode: str,
) -> dict[str, int]:
    """
    Generate embeddings for trace summaries using Kafka + Rust embedding worker.

    This activity sends embedding requests to Kafka. The actual embedding generation
    happens asynchronously in the Rust embedding worker.

    Returns dict with:
        - embeddings_requested: Total number of embedding requests sent
        - embeddings_failed: Number of summaries that failed to queue
    """

    def _embed():
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            logger.exception("Team not found", team_id=team_id)
            raise ValueError(f"Team {team_id} not found")

        # Import here to avoid circular dependencies
        from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder

        embedder = LLMTracesSummarizerEmbedder(
            team=team,
            embedding_model_name=EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072,
        )

        # Determine rendering type based on mode
        rendering = LLMA_TRACE_DETAILED_RENDERING if mode == "detailed" else LLMA_TRACE_MINIMAL_RENDERING

        # Format summaries for embedding (exclude line refs)
        summarized_traces: dict[str, str] = {}
        failed_count = 0

        for summary in summaries:
            try:
                formatted_text = format_summary_for_embedding(summary)
                summarized_traces[summary.trace_id] = formatted_text
            except Exception as e:
                logger.exception(
                    "Failed to format summary for embedding",
                    trace_id=summary.trace_id,
                    error=str(e),
                )
                failed_count += 1

        # Calculate failure rate
        total = len(summaries)
        failure_rate = failed_count / total if total > 0 else 0

        # Fail if >10% failure rate
        if failure_rate > 0.1:
            raise ValueError(
                f"Embedding formatting failed for {failed_count}/{total} summaries ({failure_rate:.1%}). "
                f"Exceeds 10% threshold."
            )

        # Send to Kafka (batch embedding via dict)
        # Note: This uses a custom type that doesn't exist in LLMTraceSummary.LLMTraceSummaryType
        # We'll need to use the rendering string directly
        try:
            # Since LLMTracesSummarizerEmbedder expects LLMTraceSummary.LLMTraceSummaryType,
            # but we want to use custom rendering strings, we need to call _embed_document directly
            from ee.hogai.llm_traces_summaries.constants import (
                LLM_TRACES_SUMMARIES_DOCUMENT_TYPE,
                LLM_TRACES_SUMMARIES_PRODUCT,
            )

            for trace_id, content in summarized_traces.items():
                embedder._embed_document(
                    content=content,
                    document_id=trace_id,
                    document_type=LLM_TRACES_SUMMARIES_DOCUMENT_TYPE,
                    rendering=rendering,
                    product=LLM_TRACES_SUMMARIES_PRODUCT,
                )

            embeddings_requested = len(summarized_traces)

            return {
                "embeddings_requested": embeddings_requested,
                "embeddings_failed": failed_count,
            }

        except Exception as e:
            logger.exception("Failed to send embeddings to Kafka", error=str(e))
            raise

    return await database_sync_to_async(_embed, thread_sensitive=False)()
