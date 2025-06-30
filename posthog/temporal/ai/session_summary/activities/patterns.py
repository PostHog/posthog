import asyncio
import json
from redis import Redis
import structlog
import temporalio
from ee.session_recordings.session_summary.llm.consume import get_llm_session_group_patterns_assignment, get_llm_session_group_patterns_extraction
from ee.session_recordings.session_summary.patterns.output_data import (
    RawSessionGroupPatternAssignmentsList,
    RawSessionGroupSummaryPatternsList,
    combine_event_ids_mappings_from_single_session_summaries,
    combine_patterns_assignments_from_single_session_summaries,
    combine_patterns_ids_with_events_context,
    combine_patterns_with_events_context,
    load_session_summary_from_string,
)
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext
from ee.session_recordings.session_summary.summarize_session_group import (
    generate_session_group_patterns_assignment_prompt,
    generate_session_group_patterns_extraction_prompt,
    remove_excessive_content_from_session_summary_for_llm,
)
from posthog.redis import get_client
from posthog.temporal.ai.session_summary.shared import SESSION_SUMMARIES_DB_DATA_REDIS_TTL
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_str_from_redis
)
from posthog.temporal.ai.session_summary.types.group import SessionGroupSummaryOfSummariesInputs

logger = structlog.get_logger(__name__)

def get_session_ids_from_inputs(inputs: SessionGroupSummaryOfSummariesInputs) -> list[str]:
    return list(
        dict.fromkeys(
            [single_session_input.session_id for single_session_input in inputs.single_session_summaries_inputs]
        )
    )

def get_session_summaries_str_from_inputs(redis_client: Redis, inputs: SessionGroupSummaryOfSummariesInputs) -> list[str]:
    return [
        get_data_str_from_redis(
            redis_client=redis_client,
            redis_key=generate_state_key(
                key_base=single_session_input.redis_key_base,
                label=StateActivitiesEnum.SESSION_SUMMARY,
                state_id=single_session_input.session_id,
            ),
            label=StateActivitiesEnum.SESSION_SUMMARY,
        )
        for single_session_input in inputs.single_session_summaries_inputs
    ]

@temporalio.activity.defn
async def extract_session_group_patterns_activity(inputs: SessionGroupSummaryOfSummariesInputs) -> None:
    redis_client = get_client()
    session_ids = get_session_ids_from_inputs(inputs)
    redis_output_key = generate_state_key(
        key_base=inputs.redis_key_base,
        label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
        state_id=",".join(session_ids),
    )
    # Get session summaries from Redis
    session_summaries_str = get_session_summaries_str_from_inputs(redis_client=redis_client, inputs=inputs)
    # Remove excessive content (like UUIDs) from session summaries when using them as a context for group summaries (and not a final step)
    intermediate_session_summaries_str = [
        remove_excessive_content_from_session_summary_for_llm(session_summary_str)
        for session_summary_str in session_summaries_str
    ]
    patterns_extraction_prompt = generate_session_group_patterns_extraction_prompt(
        session_summaries_str=intermediate_session_summaries_str, extra_summary_context=inputs.extra_summary_context
    )
    # Extract patterns from session summaries through LLM
    patterns_extraction = await get_llm_session_group_patterns_extraction(
        prompt=patterns_extraction_prompt, user_id=inputs.user_id, session_ids=session_ids
    )
    patterns_extraction_str = patterns_extraction.model_dump_json(exclude_none=True)

    # TODO: Remove after testing
    with open("patterns_extraction.json", "w") as f:
        f.write(patterns_extraction_str)

    # Store the extracted patterns in Redis
    redis_client.setex(redis_output_key, SESSION_SUMMARIES_DB_DATA_REDIS_TTL, patterns_extraction_str)
    return None


async def _generate_patterns_assignments_per_chunk(
    patterns: RawSessionGroupSummaryPatternsList,
    session_summaries_chunk_str: list[str],
    user_id: int,
    session_ids: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> RawSessionGroupPatternAssignmentsList | Exception:
    try:
        patterns_assignment_prompt = generate_session_group_patterns_assignment_prompt(
            patterns=patterns,
            session_summaries_str=session_summaries_chunk_str,
            extra_summary_context=extra_summary_context,
        )
        return await get_llm_session_group_patterns_assignment(
            prompt=patterns_assignment_prompt, user_id=user_id, session_ids=session_ids
        )
    except Exception as err:  # Activity retries exhausted
        # Let caller handle the error
        return err


async def _generate_patterns_assignments(
    patterns: RawSessionGroupSummaryPatternsList,
    session_summaries_chunks_str: list[list[str]],
    user_id: int,
    session_ids: list[str],
    extra_summary_context: ExtraSummaryContext | None,
) -> list[RawSessionGroupPatternAssignmentsList]:
    patterns_assignments_list_of_lists = []
    tasks = {}
    async with asyncio.TaskGroup() as tg:
        for chunk_index, summaries_chunk in enumerate(session_summaries_chunks_str):
            tasks[chunk_index] = tg.create_task(
                _generate_patterns_assignments_per_chunk(
                    patterns=patterns,
                    session_summaries_chunk_str=summaries_chunk,
                    user_id=user_id,
                    session_ids=session_ids,
                    extra_summary_context=extra_summary_context,
                )
            )
    for chunk_index, task in tasks.items():
        res = task.result()
        if isinstance(res, Exception):
            logger.warning(
                f"Patterns assignments generation failed for chunk from sessions ({session_ids}) for user {user_id}: {res}"
            )
            continue
        patterns_assignments_list_of_lists.append(res)
        # TODO: Remove after testing
        with open(f"patterns_assignments_chunk_{chunk_index}.json", "w") as f:
            f.write(res.model_dump_json(exclude_none=True))

    return patterns_assignments_list_of_lists

@temporalio.activity.defn
async def get_llm_session_group_summary_activity(inputs: SessionGroupSummaryOfSummariesInputs) -> str:
    """Summarize a group of sessions in one call"""
    redis_client = get_client()
    session_ids = get_session_ids_from_inputs(inputs)
    # redis_output_key = generate_state_key(
    #     key_base=inputs.redis_output_key_base,
    #     label=StateActivitiesEnum.SESSION_GROUP_EXTRACTED_PATTERNS,
    #     state_id=",".join(session_ids),
    # )
    total_sessions_count = len(session_ids)
    # Get session summaries from Redis
    session_summaries_str = get_session_summaries_str_from_inputs(redis_client=redis_client, inputs=inputs)

    # Convert session summaries strings to objects to extract event-related data
    session_summaries = [
        load_session_summary_from_string(session_summary_str) for session_summary_str in session_summaries_str
    ]


    # Split sessions summaries into chunks of 10 sessions each
    # TODO: Define in constants after testing optimal chunk size quality-wise
    session_summaries_chunks_str = [
        intermediate_session_summaries_str[i : i + 10] for i in range(0, len(intermediate_session_summaries_str), 10)
    ]
    patterns_assignments_list_of_lists = await _generate_patterns_assignments(
        patterns=patterns_extraction,
        session_summaries_chunks_str=session_summaries_chunks_str,
        user_id=inputs.user_id,
        session_ids=session_ids,
        extra_summary_context=inputs.extra_summary_context,
    )

    # Single session summaries LLM inputs from Redis to be able to enrich the patterns collected
    single_session_summaries_llm_inputs = _get_session_group_single_session_summaries_inputs_from_redis(
        redis_client=redis_client,
        redis_input_keys=[
            generate_state_key(
                key_base=inputs.redis_key_base,
                label=StateActivitiesEnum.SESSION_SUMMARY,
                state_id=single_session_input.session_id,
            )
            for single_session_input in inputs.single_session_summaries_inputs
        ],
    )

    # Combine event ids mappings from all the sessions to identify events and sessions assigned to patterns
    combined_event_ids_mappings = combine_event_ids_mappings_from_single_session_summaries(
        single_session_summaries_inputs=single_session_summaries_llm_inputs
    )
    with open("combined_event_ids_mappings.json", "w") as f:
        f.write(json.dumps(combined_event_ids_mappings))

    # Combine patterns assignments to have a single patter-to-event list
    combined_patterns_assignments = combine_patterns_assignments_from_single_session_summaries(
        patterns_assignments_list_of_lists=patterns_assignments_list_of_lists
    )
    with open("combined_patterns_assignments.json", "w") as f:
        f.write(json.dumps(combined_patterns_assignments))

    # Combine patterns ids with full event ids (from DB) and previous/next events in the segment per each assigned event
    pattern_id_to_event_context_mapping = combine_patterns_ids_with_events_context(
        combined_event_ids_mappings=combined_event_ids_mappings,
        combined_patterns_assignments=combined_patterns_assignments,
        session_summaries=session_summaries,
    )
    with open("pattern_event_ids_mapping.json", "w") as f:
        f.write(
            json.dumps(
                {k: [dataclasses.asdict(dv) for dv in v] for k, v in pattern_id_to_event_context_mapping.items()}
            )
        )

    # Combine patterns info (name, description, etc.) with enriched events context
    patterns_with_events_context = combine_patterns_with_events_context(
        patterns=patterns_extraction,
        pattern_id_to_event_context_mapping=pattern_id_to_event_context_mapping,
        total_sessions_count=total_sessions_count,
    )
    with open("patterns_with_events_context.json", "w") as f:
        f.write(patterns_with_events_context.model_dump_json(exclude_none=True))

    # TODO: Enable after testing
    # summary_prompt = generate_session_group_summary_prompt(
    #     session_summaries=session_summaries, extra_summary_context=inputs.extra_summary_context
    # )
    # # Get summary from LLM
    # summary_of_summaries = await get_llm_session_group_summary(
    #     prompt=summary_prompt, user_id=inputs.user_id, session_ids=inputs.session_ids
    # )
    # return summary_of_summaries
