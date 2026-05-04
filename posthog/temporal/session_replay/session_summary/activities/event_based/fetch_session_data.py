import json
import dataclasses

import temporalio

from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
    store_data_in_redis,
)
from posthog.temporal.session_replay.session_summary.types.inputs import SingleSessionSummaryInputs

from ee.hogai.session_summaries.session.summarize_session import (
    SingleSessionSummaryLlmInputs,
    get_session_data_from_db,
    prepare_data_for_single_session_summary,
    prepare_single_session_summary_input,
)


@temporalio.activity.defn
async def fetch_session_data_activity(inputs: SingleSessionSummaryInputs) -> bool:
    """Returns False if the session has no events (static); True otherwise."""
    redis_client, redis_input_key, _ = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        state_id=inputs.session_id,
    )
    success = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_input_key,
        label=StateActivitiesEnum.SESSION_DB_DATA,
        target_class=SingleSessionSummaryLlmInputs,
    )
    if success is not None:
        return True
    session_db_data = await get_session_data_from_db(
        session_id=inputs.session_id,
        team_id=inputs.team_id,
        local_reads_prod=inputs.local_reads_prod,
    )
    if not session_db_data.session_events or not session_db_data.session_events_columns:
        return False
    summary_data = await prepare_data_for_single_session_summary(
        session_id=inputs.session_id,
        user_id=inputs.user_id,
        session_db_data=session_db_data,
        extra_summary_context=inputs.extra_summary_context,
    )
    input_data = prepare_single_session_summary_input(
        session_id=inputs.session_id,
        user_id=inputs.user_id,
        user_distinct_id_to_log=inputs.user_distinct_id_to_log,
        summary_data=summary_data,
        model_to_use=inputs.model_to_use,
        trigger_session_id=inputs.trigger_session_id,
    )
    input_data_str = json.dumps(dataclasses.asdict(input_data))
    await store_data_in_redis(
        redis_client=redis_client,
        redis_key=redis_input_key,
        data=input_data_str,
        label=StateActivitiesEnum.SESSION_DB_DATA,
    )
    return True
