"""Activity for generating embeddings for trace summaries."""

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

            logger.info(
                "Embedding requests sent to Kafka",
                team_id=team_id,
                embeddings_requested=embeddings_requested,
                embeddings_failed=failed_count,
                mode=mode,
                rendering=rendering,
            )

            return {
                "embeddings_requested": embeddings_requested,
                "embeddings_failed": failed_count,
            }

        except Exception as e:
            logger.exception("Failed to send embeddings to Kafka", error=str(e))
            raise

    return await database_sync_to_async(_embed, thread_sensitive=False)()
