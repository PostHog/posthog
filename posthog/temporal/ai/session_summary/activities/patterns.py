import json
import asyncio
from math import ceil
from typing import cast

import structlog
import temporalio
from redis import asyncio as aioredis
from temporalio.client import WorkflowHandle
from temporalio.exceptions import ApplicationError

from posthog.redis import get_async_client
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    generate_state_id_from_session_ids,
    get_data_class_from_redis,
    get_ready_summaries_from_db,
    get_redis_state_client,
    store_data_in_redis,
)
from posthog.temporal.ai.session_summary.types.group import (
    SessionGroupSummaryOfSummariesInputs,
    SessionGroupSummaryPatternsExtractionChunksInputs,
)
from posthog.temporal.common.client import async_connect

from products.enterprise.backend.hogai.session_summaries.constants import (
    FAILED_PATTERNS_ASSIGNMENT_MIN_RATIO,
    PATTERNS_ASSIGNMENT_CHUNK_SIZE,
    PATTERNS_EXTRACTION_MAX_TOKENS,
    SESSION_SUMMARIES_SYNC_MODEL,
    SINGLE_ENTITY_MAX_TOKENS,
)
from products.enterprise.backend.hogai.session_summaries.llm.consume import (
    get_llm_session_group_patterns_assignment,
    get_llm_session_group_patterns_combination,
    get_llm_session_group_patterns_extraction,
)
from products.enterprise.backend.hogai.session_summaries.session.summarize_session import ExtraSummaryContext
from products.enterprise.backend.hogai.session_summaries.session_group.patterns import (
    EnrichedSessionGroupSummaryPatternsList,
    RawSessionGroupPatternAssignmentsList,
    RawSessionGroupSummaryPattern,
    RawSessionGroupSummaryPatternsList,
    combine_patterns_assignments_from_single_session_summaries,
    combine_patterns_ids_with_events_context,
    combine_patterns_with_events_context,
    create_event_ids_mapping_from_ready_summaries,
    session_summary_to_serializer,
)
from products.enterprise.backend.hogai.session_summaries.session_group.summarize_session_group import (
    generate_session_group_patterns_assignment_prompt,
    generate_session_group_patterns_combination_prompt,
    generate_session_group_patterns_extraction_prompt,
    remove_excessive_content_from_session_summary_for_llm,
)
from products.enterprise.backend.hogai.session_summaries.utils import estimate_tokens_from_strings, logging_session_ids

logger = structlog.get_logger(__name__)


def _get_session_ids_from_inputs(inputs: SessionGroupSummaryOfSummariesInputs) -> list[str]:
    """Return unique session IDs contained in the inputs."""
    return list(
        dict.fromkeys(
            [single_session_input.session_id for single_session_input in inputs.single_session_summaries_inputs]
        )
    )


async def get_patterns_from_redis_outside_workflow(
    redis_output_keys: list[str],
    redis_client: aioredis.Redis,
) -> list[RawSessionGroupSummaryPattern]:
    """Sync function to get patterns from Redis outside of the workflow."""
    extracted_patterns: list[RawSessionGroupSummaryPattern] = []
    if not redis_output_keys:
        return extracted_patterns
    for redis_output_key in redis_output_keys:
        patterns_list = await get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=redis_output_key,
            label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
            target_class=RawSessionGroupSummaryPatternsList,
        )
        if patterns_list is None:
            raise ValueError(
                f"Failed to get Redis output data for key {redis_output_key} when getting extracted patterns from Redis"
            )
        extracted_patterns.extend(patterns_list.patterns)
    return extracted_patterns


@temporalio.activity.defn
async def split_session_summaries_into_chunks_for_patterns_extraction_activity(
    inputs: SessionGroupSummaryOfSummariesInputs,
) -> list[list[str]]:
    """
    Split LLM input data into chunks based on token count.
    This is an activity to avoid workflow deadlocks when using tiktoken inside workflow.
    """
    if not inputs.single_session_summaries_inputs:
        return []
    session_ids = _get_session_ids_from_inputs(inputs)
    # Calculate token count for the prompt templates, providing empty context
    prompt = generate_session_group_patterns_extraction_prompt(
        session_summaries_str=[""], extra_summary_context=inputs.extra_summary_context
    )
    # Estimate base template tokens (without session summaries)
    base_template_tokens = estimate_tokens_from_strings(
        strings=[prompt.system_prompt, prompt.patterns_prompt], model=SESSION_SUMMARIES_SYNC_MODEL
    )
    # Get ready session summaries from DB
    # Disable thread-sensitive as the call is heavy (N summaries through pagination)
    ready_summaries = await database_sync_to_async(get_ready_summaries_from_db, thread_sensitive=False)(
        team_id=inputs.team_id,
        session_ids=session_ids,
        extra_summary_context=inputs.extra_summary_context,
    )
    # Ensure we got all the summaries, as it's crucial to keep the order of sessions to match them with ids
    if len(ready_summaries) != len(inputs.single_session_summaries_inputs):
        raise ValueError(
            f"Expected {len(inputs.single_session_summaries_inputs)} session summaries, got {len(ready_summaries)}, when splitting into chunks for patterns extraction"
        )
    # Calculate tokens for each session summary, mapped by session_id to preserve input order
    tokens_per_session: dict[str, int] = {}
    for summary in ready_summaries:
        summary_str = json.dumps(remove_excessive_content_from_session_summary_for_llm(summary.summary).data)
        tokens_per_session[summary.session_id] = estimate_tokens_from_strings(
            strings=[summary_str], model=SESSION_SUMMARIES_SYNC_MODEL
        )
    # Create chunks ensuring each stays under the token limit
    chunks = []
    current_chunk: list[str] = []
    current_tokens = base_template_tokens
    for summary_input in inputs.single_session_summaries_inputs:
        session_id = summary_input.session_id
        summary_tokens = tokens_per_session.get(session_id)
        if summary_tokens is None:
            raise ValueError(
                f"Missing token estimation for session {session_id} when splitting into chunks for patterns extraction"
            )
        # Check if single session exceeds the limit
        if base_template_tokens + summary_tokens > PATTERNS_EXTRACTION_MAX_TOKENS:
            # Check if it fits within the single entity max tokens limit
            if base_template_tokens + summary_tokens <= SINGLE_ENTITY_MAX_TOKENS:
                logger.warning(
                    f"Session {session_id} exceeds PATTERNS_EXTRACTION_MAX_TOKENS "
                    f"({base_template_tokens + summary_tokens} tokens) but fits within "
                    f"SINGLE_ENTITY_MAX_TOKENS. Processing it in a separate chunk."
                )
                # Save current chunk if not empty
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = []
                    current_tokens = base_template_tokens
                # Process this large session in its own chunk
                chunks.append([session_id])
                continue
            else:
                # Session is too large even for single entity processing
                logger.error(
                    f"Session {session_id} exceeds even SINGLE_ENTITY_MAX_TOKENS "
                    f"({base_template_tokens + summary_tokens} tokens). Skipping this session."
                )
                continue

        # Check if adding this session would exceed the limit
        if current_tokens + summary_tokens > PATTERNS_EXTRACTION_MAX_TOKENS:
            # If current chunk is not empty, save it and start a new one
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_tokens = base_template_tokens
        # Add session id to current chunk
        current_chunk.append(session_id)
        current_tokens += summary_tokens
    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


@temporalio.activity.defn
async def extract_session_group_patterns_activity(inputs: SessionGroupSummaryOfSummariesInputs) -> str:
    """Extract patterns for a group of sessions and store them in Redis."""
    session_ids = _get_session_ids_from_inputs(inputs)
    redis_client, _, redis_output_key = get_redis_state_client(
        key_base=inputs.redis_key_base,
        output_label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id=generate_state_id_from_session_ids(session_ids),
    )
    if redis_output_key is None:
        raise ValueError(
            f"Failed to generate Redis output key for extracted patterns for sessions: {','.join(session_ids)}"
        )
    # Check if patterns extracted are already in Redis. If it is and matched the target class - it's within TTL, so no need to re-fetch them from LLM
    success = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_output_key,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        target_class=RawSessionGroupSummaryPatternsList,
    )
    if success is not None:
        # Cached successfully
        return redis_output_key
    # Get ready session summaries from DB
    # Disable thread-sensitive as the call is heavy (N summaries through pagination)
    ready_summaries = await database_sync_to_async(get_ready_summaries_from_db, thread_sensitive=False)(
        team_id=inputs.team_id,
        session_ids=session_ids,
        extra_summary_context=inputs.extra_summary_context,
    )
    # Remove excessive content (like UUIDs) from session summaries when using them as a context for group summaries (and not a final step)
    intermediate_session_summaries_str = [
        json.dumps(remove_excessive_content_from_session_summary_for_llm(summary.summary).data)
        for summary in ready_summaries
    ]
    patterns_extraction_prompt = generate_session_group_patterns_extraction_prompt(
        session_summaries_str=intermediate_session_summaries_str, extra_summary_context=inputs.extra_summary_context
    )
    # Extract patterns from session summaries through LLM
    patterns_extraction = await get_llm_session_group_patterns_extraction(
        prompt=patterns_extraction_prompt,
        user_id=inputs.user_id,
        session_ids=session_ids,
        model_to_use=inputs.model_to_use,
        trace_id=temporalio.activity.info().workflow_id,
    )
    patterns_extraction_str = patterns_extraction.model_dump_json(exclude_none=True)
    # Store the extracted patterns in Redis
    await store_data_in_redis(
        redis_client=redis_client,
        redis_key=redis_output_key,
        data=patterns_extraction_str,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
    )
    return redis_output_key


async def _generate_patterns_assignments_per_chunk(
    patterns: RawSessionGroupSummaryPatternsList,
    session_summaries_chunk_str: list[str],
    user_id: int,
    session_ids: list[str],
    model_to_use: str,
    workflow_handle: WorkflowHandle,
    extra_summary_context: ExtraSummaryContext | None,
    trace_id: str | None = None,
) -> RawSessionGroupPatternAssignmentsList | Exception:
    """Assign events to patterns for a single chunk of summaries."""
    try:
        patterns_assignment_prompt = generate_session_group_patterns_assignment_prompt(
            patterns=patterns,
            session_summaries_str=session_summaries_chunk_str,
            extra_summary_context=extra_summary_context,
        )
        result = await get_llm_session_group_patterns_assignment(
            prompt=patterns_assignment_prompt,
            user_id=user_id,
            session_ids=session_ids,
            model_to_use=model_to_use,
            trace_id=trace_id,
        )
        # Send progress signal to workflow
        await workflow_handle.signal("update_pattern_assignments_progress", len(session_summaries_chunk_str))
        return result
    except Exception as err:  # Activity retries exhausted
        # Let caller handle the error
        return err


async def _generate_patterns_assignments(
    patterns: RawSessionGroupSummaryPatternsList,
    session_summaries_chunks_str: list[list[str]],
    user_id: int,
    session_ids: list[str],
    model_to_use: str,
    extra_summary_context: ExtraSummaryContext | None,
    trace_id: str | None = None,
) -> list[RawSessionGroupPatternAssignmentsList]:
    """Run pattern assignments concurrently for multiple chunks."""
    patterns_assignments_list_of_lists = []
    tasks = {}
    # Get workflow handle to send progress signals
    # TODO: Replace later by splitting `_generate_patterns_assignments` into separate activity
    temporal_client = await async_connect()
    info = temporalio.activity.info()
    workflow_handle = temporal_client.get_workflow_handle(info.workflow_id, run_id=info.workflow_run_id)
    # Send initial progress
    await workflow_handle.signal("update_pattern_assignments_progress", 0)
    # Assign events to patterns in chunks
    async with asyncio.TaskGroup() as tg:
        for chunk_index, summaries_chunk in enumerate(session_summaries_chunks_str):
            tasks[chunk_index] = tg.create_task(
                _generate_patterns_assignments_per_chunk(
                    patterns=patterns,
                    session_summaries_chunk_str=summaries_chunk,
                    user_id=user_id,
                    session_ids=session_ids,
                    model_to_use=model_to_use,
                    workflow_handle=workflow_handle,
                    extra_summary_context=extra_summary_context,
                    trace_id=trace_id,
                )
            )
    # Process results and send progress updates
    for _, task in tasks.items():
        res: RawSessionGroupPatternAssignmentsList | Exception = task.result()
        if isinstance(res, Exception):
            logger.warning(
                f"Patterns assignments generation failed for chunk from sessions ({logging_session_ids(session_ids)}) for user {user_id}: {res}"
            )
            continue
        patterns_assignments_list_of_lists.append(res)
    # Fail the activity if too many patterns failed to assign session events
    if ceil(len(session_summaries_chunks_str) * FAILED_PATTERNS_ASSIGNMENT_MIN_RATIO) > len(
        patterns_assignments_list_of_lists
    ):
        exception_message = (
            f"Too many patterns failed to assign session events, when summarizing {len(session_ids)} "
            f"sessions ({logging_session_ids(session_ids)}) for user {user_id}"
        )
        logger.error(exception_message)
        raise ApplicationError(exception_message)
    return patterns_assignments_list_of_lists


@temporalio.activity.defn
async def assign_events_to_patterns_activity(
    inputs: SessionGroupSummaryOfSummariesInputs,
) -> EnrichedSessionGroupSummaryPatternsList:
    """Summarize a group of sessions in one call"""
    session_ids = _get_session_ids_from_inputs(inputs)
    redis_client, redis_input_key, redis_output_key = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        output_label=StateActivitiesEnum.SESSION_GROUP_PATTERNS_ASSIGNMENTS,
        state_id=generate_state_id_from_session_ids(session_ids),
    )
    # Check if patterns assignments are already in Redis. If it is and matched the target class - it's within TTL, so no need to re-fetch them from LLM
    patterns_with_events_context = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_output_key,
        label=StateActivitiesEnum.SESSION_GROUP_PATTERNS_ASSIGNMENTS,
        target_class=EnrichedSessionGroupSummaryPatternsList,
    )
    # Return if it's processed already
    if patterns_with_events_context:
        return patterns_with_events_context
    # Get ready session summaries from DB
    # Disable thread-sensitive as the call is heavy (N summaries through pagination)
    ready_summaries = await database_sync_to_async(get_ready_summaries_from_db, thread_sensitive=False)(
        team_id=inputs.team_id,
        session_ids=session_ids,
        extra_summary_context=inputs.extra_summary_context,
    )
    # Remove excessive content (like UUIDs) from session summaries when using them as a context for group summaries (and not a final step)
    intermediate_session_summaries_str = [
        json.dumps(remove_excessive_content_from_session_summary_for_llm(summary.summary).data)
        for summary in ready_summaries
    ]
    # Split sessions summaries into chunks to keep context small-enough for LLM for proper assignment
    # TODO: Run activity for each chunk instead to avoid retrying the whole activity if one chunk fails
    # TODO: Split not by number of sessions, but by tokens, as with patterns extraction
    session_summaries_chunks_str = [
        intermediate_session_summaries_str[i : i + PATTERNS_ASSIGNMENT_CHUNK_SIZE]
        for i in range(0, len(intermediate_session_summaries_str), PATTERNS_ASSIGNMENT_CHUNK_SIZE)
    ]
    # Get extracted patterns from Redis to be able to assign events to them
    patterns_extraction_raw = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_input_key,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        target_class=RawSessionGroupSummaryPatternsList,
    )
    if patterns_extraction_raw is None:
        # No reason to retry activity, as the data from the previous activity is not in Redis
        raise ApplicationError(
            f"No patterns extraction found for sessions {logging_session_ids(session_ids)} when assigning events to patterns",
            non_retryable=True,
        )
    patterns_extraction = cast(
        RawSessionGroupSummaryPatternsList,
        patterns_extraction_raw,
    )
    # Assign events <> patterns through LLM calls in chunks to keep the content meaningful
    patterns_assignments_list_of_lists = await _generate_patterns_assignments(
        patterns=patterns_extraction,
        session_summaries_chunks_str=session_summaries_chunks_str,
        user_id=inputs.user_id,
        session_ids=session_ids,
        model_to_use=inputs.model_to_use,
        extra_summary_context=inputs.extra_summary_context,
        trace_id=temporalio.activity.info().workflow_id,
    )
    # Convert session summaries strings to objects to extract event-related data
    session_summaries = [session_summary_to_serializer(summary.summary) for summary in ready_summaries]
    # Create event ids mappings from ready summaries to identify events and sessions assigned to patterns
    combined_event_ids_mappings = create_event_ids_mapping_from_ready_summaries(session_summaries=session_summaries)
    # Combine patterns assignments to have a single pattern-to-events list
    combined_patterns_assignments = combine_patterns_assignments_from_single_session_summaries(
        patterns_assignments_list_of_lists=patterns_assignments_list_of_lists
    )
    # Combine patterns ids with full event ids (from DB) and previous/next events in the segment per each assigned event
    pattern_id_to_event_context_mapping = combine_patterns_ids_with_events_context(
        combined_event_ids_mappings=combined_event_ids_mappings,
        combined_patterns_assignments=combined_patterns_assignments,
        session_summaries=session_summaries,
    )
    # Combine patterns info (name, description, etc.) with enriched events context
    patterns_with_events_context = combine_patterns_with_events_context(
        patterns=patterns_extraction,
        pattern_id_to_event_context_mapping=pattern_id_to_event_context_mapping,
        session_ids=session_ids,
        user_id=inputs.user_id,
    )
    patterns_with_events_context_str = patterns_with_events_context.model_dump_json(exclude_none=True)
    await store_data_in_redis(
        redis_client=redis_client,
        redis_key=redis_output_key,
        data=patterns_with_events_context_str,
        label=StateActivitiesEnum.SESSION_GROUP_PATTERNS_ASSIGNMENTS,
    )
    return patterns_with_events_context


@temporalio.activity.defn
async def combine_patterns_from_chunks_activity(inputs: SessionGroupSummaryPatternsExtractionChunksInputs) -> None:
    """Combine patterns from multiple chunks using LLM and store in Redis."""
    redis_client = get_async_client()
    _, _, redis_output_key = get_redis_state_client(
        key_base=inputs.redis_key_base,
        output_label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id=generate_state_id_from_session_ids(inputs.session_ids),
    )
    # Check if combined patterns are already in Redis (for all the sessions at once)
    success = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_output_key,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        target_class=RawSessionGroupSummaryPatternsList,
    )
    if success is not None:
        # Already exists, no need to regenerate
        return None
    # Retrieve all chunk patterns from Redis
    chunk_patterns = []
    for chunk_key in inputs.redis_keys_of_chunks_to_combine:
        try:
            chunk_pattern = await get_data_class_from_redis(
                redis_client=redis_client,
                redis_key=chunk_key,
                label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
                target_class=RawSessionGroupSummaryPatternsList,
            )
            if chunk_pattern is None:
                # Raise error if chunk is missing
                raise ValueError(f"Chunk patterns not found in Redis for key {chunk_key}")
            chunk_patterns.append(chunk_pattern)
        except ValueError as err:
            # Raise error if any chunk is missing or malformed
            logger.exception(
                f"Failed to retrieve chunk patterns from Redis key {chunk_key} when combining patterns from chunks: {err}",
                redis_key=chunk_key,
                user_id=inputs.user_id,
                session_ids=inputs.session_ids,
            )
            raise
    if not chunk_patterns:
        raise ApplicationError(
            f"No chunk patterns could be retrieved for sessions {inputs.session_ids} "
            f"for user {inputs.user_id}. All chunks may be missing or corrupted."
        )

    # Generate prompt for combining patterns from chunks
    combined_patterns_prompt = generate_session_group_patterns_combination_prompt(
        patterns_chunks=chunk_patterns,
        extra_summary_context=inputs.extra_summary_context,
    )

    # Use LLM to intelligently combine and deduplicate patterns
    combined_patterns = await get_llm_session_group_patterns_combination(
        prompt=combined_patterns_prompt,
        user_id=inputs.user_id,
        session_ids=inputs.session_ids,
        trace_id=temporalio.activity.info().workflow_id,
    )

    # Store the combined patterns in Redis with 24-hour TTL
    combined_patterns_str = combined_patterns.model_dump_json(exclude_none=True)
    await store_data_in_redis(
        redis_client=redis_client,
        redis_key=redis_output_key,
        data=combined_patterns_str,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
    )
    return None
