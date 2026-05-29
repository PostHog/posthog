from typing import cast

import temporalio
from dateutil import parser as dateutil_parser
from temporalio.exceptions import ApplicationError

from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.session_replay.session_summary.types.inputs import SingleSessionSummaryInputs

from ee.hogai.session_summaries.llm.consume import get_exception_event_ids_from_summary, get_llm_single_session_summary
from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.models.session_summaries import SessionSummaryRunMeta, SingleSessionSummary


def _store_final_summary_in_db_from_activity(
    inputs: SingleSessionSummaryInputs,
    session_summary: SessionSummarySerializer,
    llm_input: SingleSessionSummaryLlmInputs,
) -> None:
    exception_event_ids = get_exception_event_ids_from_summary(session_summary)
    user = User.objects.get(id=inputs.user_id)
    if not user:
        msg = f"User with id {inputs.user_id} not found, when trying to add session summary for session {inputs.session_id}"
        temporalio.activity.logger.error(
            msg,
            extra={
                "user_id": inputs.user_id,
                "session_id": inputs.session_id,
                "signals_type": "session-summaries",
            },
        )
        raise ValueError(msg)
    SingleSessionSummary.objects.add_summary(
        session_id=inputs.session_id,
        team_id=inputs.team_id,
        summary=session_summary,
        exception_event_ids=exception_event_ids,
        extra_summary_context=inputs.extra_summary_context,
        run_metadata=SessionSummaryRunMeta(
            model_used=inputs.model_to_use,
            visual_confirmation=False,
        ),
        session_start_time=dateutil_parser.isoparse(llm_input.session_start_time_str),
        session_duration=llm_input.session_duration,
        distinct_id=llm_input.distinct_id,
        created_by=user,
    )


@temporalio.activity.defn
async def get_llm_single_session_summary_activity(
    inputs: SingleSessionSummaryInputs,
) -> None:
    """Summarize a single session via LLM. Caches inputs/outputs in Redis to avoid Temporal payload limits."""
    # Re-check the summary guard: the group-summary path skips the workflow-entry guard.
    summary_exists = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=[inputs.session_id],
        extra_summary_context=inputs.extra_summary_context,
    )
    if summary_exists.get(inputs.session_id):
        return None
    redis_client, redis_input_key, _ = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        state_id=inputs.session_id,
    )
    llm_input_raw = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_input_key,
        label=StateActivitiesEnum.SESSION_DB_DATA,
        target_class=SingleSessionSummaryLlmInputs,
    )
    if llm_input_raw is None:
        msg = f"No LLM input found for session {inputs.session_id} when summarizing"
        temporalio.activity.logger.error(
            msg,
            extra={
                "session_id": inputs.session_id,
                "signals_type": "session-summaries",
            },
        )
        raise ApplicationError(msg, non_retryable=True)
    llm_input = cast(
        SingleSessionSummaryLlmInputs,
        llm_input_raw,
    )
    session_summary = await get_llm_single_session_summary(
        session_id=llm_input.session_id,
        user_id=llm_input.user_id,
        model_to_use=llm_input.model_to_use,
        summary_prompt=llm_input.summary_prompt,
        system_prompt=llm_input.system_prompt,
        allowed_event_ids=list(llm_input.simplified_events_mapping.keys()),
        simplified_events_mapping=llm_input.simplified_events_mapping,
        event_ids_mapping=llm_input.event_ids_mapping,
        simplified_events_columns=llm_input.simplified_events_columns,
        url_mapping_reversed=llm_input.url_mapping_reversed,
        window_mapping_reversed=llm_input.window_mapping_reversed,
        session_start_time_str=llm_input.session_start_time_str,
        session_duration=llm_input.session_duration,
        trace_id=temporalio.activity.info().workflow_id,
        user_distinct_id=llm_input.user_distinct_id_to_log,
        trigger_session_id=llm_input.trigger_session_id,
    )
    await database_sync_to_async(_store_final_summary_in_db_from_activity, thread_sensitive=False)(
        inputs, session_summary, llm_input
    )
    return None
