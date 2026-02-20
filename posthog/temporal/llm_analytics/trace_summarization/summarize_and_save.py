"""Activity for generating LLM summary and saving the result."""

import time
from uuid import uuid4

import structlog
import temporalio

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.redis import get_async_client
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.models import (
    SummarizationActivityResult,
    SummarizeAndSaveInput,
    TextReprExpiredError,
)
from posthog.temporal.llm_analytics.trace_summarization.state import delete_text_repr, load_text_repr

from products.llm_analytics.backend.summarization.llm import summarize
from products.llm_analytics.backend.summarization.llm.schema import SummarizationResponse
from products.llm_analytics.backend.summarization.models import OpenAIModel, SummarizationMode

from ee.hogai.llm_traces_summaries.constants import LLM_TRACES_SUMMARIES_DOCUMENT_TYPE, LLM_TRACES_SUMMARIES_PRODUCT
from ee.hogai.llm_traces_summaries.tools.embed_summaries import LLMTracesSummarizerEmbedder

logger = structlog.get_logger(__name__)


def _save_trace_summary_event(
    summary_result: SummarizationResponse,
    text_repr_length: int,
    event_count: int,
    trace_id: str,
    trace_first_timestamp: str,
    mode: str,
    batch_run_id: str,
    team: Team,
    team_id: int,
) -> None:
    summary_bullets_json = [bullet.model_dump() for bullet in summary_result.summary_bullets]
    summary_notes_json = [note.model_dump() for note in summary_result.interesting_notes]

    properties = {
        "$ai_trace_id": trace_id,
        "$ai_batch_run_id": batch_run_id,
        "$ai_summary_mode": mode,
        "$ai_summary_title": summary_result.title,
        "$ai_summary_flow_diagram": summary_result.flow_diagram,
        "$ai_summary_bullets": summary_bullets_json,
        "$ai_summary_interesting_notes": summary_notes_json,
        "$ai_text_repr_length": text_repr_length,
        "$ai_event_count": event_count,
        "trace_timestamp": trace_first_timestamp,
    }

    create_event(
        event_uuid=uuid4(),
        event=constants.EVENT_NAME_TRACE_SUMMARY,
        team=team,
        distinct_id=f"trace_summary_{team_id}",
        properties=properties,
    )


def _save_generation_summary_event(
    summary_result: SummarizationResponse,
    text_repr_length: int,
    generation_id: str,
    trace_id: str,
    trace_first_timestamp: str,
    mode: str,
    batch_run_id: str,
    team: Team,
    team_id: int,
) -> None:
    summary_bullets_json = [bullet.model_dump() for bullet in summary_result.summary_bullets]
    summary_notes_json = [note.model_dump() for note in summary_result.interesting_notes]

    properties = {
        "$ai_generation_id": generation_id,
        "$ai_trace_id": trace_id,
        "$ai_batch_run_id": batch_run_id,
        "$ai_summary_mode": mode,
        "$ai_summary_title": summary_result.title,
        "$ai_summary_flow_diagram": summary_result.flow_diagram,
        "$ai_summary_bullets": summary_bullets_json,
        "$ai_summary_interesting_notes": summary_notes_json,
        "$ai_text_repr_length": text_repr_length,
        "trace_timestamp": trace_first_timestamp,
    }

    create_event(
        event_uuid=uuid4(),
        event=constants.EVENT_NAME_GENERATION_SUMMARY,
        team=team,
        distinct_id=f"generation_summary_{team_id}",
        properties=properties,
    )


def _embed_trace_summary(
    summary_result: SummarizationResponse,
    trace_id: str,
    mode: str,
    batch_run_id: str,
    team: Team,
) -> None:
    summary_text = _format_summary_for_embedding(summary_result)
    document_type_with_mode = f"{LLM_TRACES_SUMMARIES_DOCUMENT_TYPE}-{mode}"

    embedder = LLMTracesSummarizerEmbedder(team=team)
    embedder._embed_document(
        content=summary_text,
        document_id=trace_id,
        document_type=document_type_with_mode,
        rendering=batch_run_id,
        product=LLM_TRACES_SUMMARIES_PRODUCT,
    )


def _embed_generation_summary(
    summary_result: SummarizationResponse,
    generation_id: str,
    batch_run_id: str,
    team: Team,
) -> None:
    summary_text = _format_summary_for_embedding(summary_result)

    embedder = LLMTracesSummarizerEmbedder(team=team)
    embedder._embed_document(
        content=summary_text,
        document_id=generation_id,
        document_type=constants.GENERATION_DOCUMENT_TYPE,
        rendering=batch_run_id,
        product="llm-analytics",
    )


def _format_summary_for_embedding(summary_result: SummarizationResponse) -> str:
    parts = []
    if summary_result.title:
        parts.append(f"Title: {summary_result.title}")
    if summary_result.flow_diagram:
        parts.append(f"\nFlow:\n{summary_result.flow_diagram}")
    if summary_result.summary_bullets:
        bullets_text = "\n".join(f"- {b.text}" for b in summary_result.summary_bullets)
        parts.append(f"\nSummary:\n{bullets_text}")
    if summary_result.interesting_notes:
        notes_text = "\n".join(f"- {n.text}" for n in summary_result.interesting_notes)
        parts.append(f"\nInteresting Notes:\n{notes_text}")
    return "\n".join(parts)


@temporalio.activity.defn
async def summarize_and_save_activity(input: SummarizeAndSaveInput) -> SummarizationActivityResult:
    """Read text_repr from Redis, call LLM, save event, embed, and clean up."""
    is_generation = input.generation_id is not None
    log = logger.bind(
        trace_id=input.trace_id, generation_id=input.generation_id, team_id=input.team_id, redis_key=input.redis_key
    )

    activity_start = time.monotonic()

    async with Heartbeater():
        # Step 1: Load text_repr from Redis
        redis_client = get_async_client()
        text_repr = await load_text_repr(redis_client, input.redis_key)
        if text_repr is None:
            raise TextReprExpiredError(f"Redis key expired or missing: {input.redis_key}")

        # Step 2: Generate summary using LLM
        mode_enum = SummarizationMode(input.mode)
        model_enum = OpenAIModel(input.model) if input.model else None

        t0 = time.monotonic()
        summary_result = await database_sync_to_async(summarize, thread_sensitive=False)(
            text_repr=text_repr,
            team_id=input.team_id,
            mode=mode_enum,
            model=model_enum,
            user_id=f"temporal-workflow-team-{input.team_id}",
        )
        llm_duration_s = time.monotonic() - t0
        log.info(
            "LLM summary generated",
            llm_duration_s=round(llm_duration_s, 2),
            text_repr_length=len(text_repr),
            model=input.model,
        )

        # Step 3: Save event to ClickHouse
        team = await database_sync_to_async(Team.objects.get, thread_sensitive=False)(id=input.team_id)
        t0 = time.monotonic()
        if is_generation:
            assert input.generation_id is not None
            await database_sync_to_async(_save_generation_summary_event, thread_sensitive=False)(
                summary_result,
                len(text_repr),
                input.generation_id,
                input.trace_id,
                input.trace_first_timestamp,
                input.mode,
                input.batch_run_id,
                team,
                input.team_id,
            )
        else:
            await database_sync_to_async(_save_trace_summary_event, thread_sensitive=False)(
                summary_result,
                len(text_repr),
                input.event_count,
                input.trace_id,
                input.trace_first_timestamp,
                input.mode,
                input.batch_run_id,
                team,
                input.team_id,
            )
        save_duration_s = time.monotonic() - t0

        # Step 4: Request embedding
        embedding_requested = False
        embedding_request_error = None
        t0 = time.monotonic()
        try:
            if is_generation:
                assert input.generation_id is not None
                await database_sync_to_async(_embed_generation_summary, thread_sensitive=False)(
                    summary_result, input.generation_id, input.batch_run_id, team
                )
            else:
                await database_sync_to_async(_embed_trace_summary, thread_sensitive=False)(
                    summary_result, input.trace_id, input.mode, input.batch_run_id, team
                )
            embedding_requested = True
        except Exception as e:
            embedding_request_error = str(e)
            log.exception("Failed to request embedding", error=embedding_request_error)
        embed_duration_s = time.monotonic() - t0

        # Step 5: Clean up Redis key
        await delete_text_repr(redis_client, input.redis_key)

        total_duration_s = time.monotonic() - activity_start
        log.info(
            "Activity completed",
            total_duration_s=round(total_duration_s, 2),
            llm_duration_s=round(llm_duration_s, 2),
            save_duration_s=round(save_duration_s, 2),
            embed_duration_s=round(embed_duration_s, 2),
            text_repr_length=len(text_repr),
            embedding_requested=embedding_requested,
        )

    return SummarizationActivityResult(
        trace_id=input.trace_id,
        success=True,
        generation_id=input.generation_id,
        text_repr_length=len(text_repr),
        event_count=input.event_count,
        embedding_requested=embedding_requested,
        embedding_request_error=embedding_request_error,
    )
