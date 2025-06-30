import dataclasses
import json
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext, SingleSessionSummaryLlmInputs
from ee.session_recordings.session_summary.summarize_session import (
    prepare_data_for_single_session_summary,
    prepare_single_session_summary_input,
)
import structlog
from ee.session_recordings.session_summary import ExceptionToRetry
import temporalio
from posthog.temporal.ai.session_summary.state import (
    compress_redis_data,
    get_data_class_from_redis,
    get_redis_state_client,
    StateActivitiesEnum,
)

logger = structlog.get_logger(__name__)

# How long to store the DB data in Redis within Temporal session summaries jobs
SESSION_SUMMARIES_DB_DATA_REDIS_TTL = 60 * 3 * 60  # 180 minutes to keep alive for retries and long-running workflows


@dataclasses.dataclass(frozen=True, kw_only=True)
class SingleSessionSummaryInputs:
    """Workflow input to get summary for a single session"""

    session_id: str
    user_id: int
    team_id: int
    redis_key_base: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


@temporalio.activity.defn
async def fetch_session_data_activity(inputs: SingleSessionSummaryInputs) -> str | None:
    """Fetch data from DB for a single session and store/cache in Redis (to avoid hitting Temporal memory limits)"""
    redis_client, redis_input_key, _ = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        state_id=inputs.session_id,
    )
    try:
        # Check if DB data is already in Redis. If it is and matched the target class - it's within TTL, so no need to re-fetch it from DB
        # TODO: Think about edge-cases like still-running sessions (could be solved with checking statuses)
        get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=redis_input_key,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            target_class=SingleSessionSummaryLlmInputs,
        )
    except ValueError:
        # If not yet, or TTL expired - fetch data from DB
        summary_data = await prepare_data_for_single_session_summary(
            session_id=inputs.session_id,
            user_id=inputs.user_id,
            team_id=inputs.team_id,
            extra_summary_context=inputs.extra_summary_context,
            local_reads_prod=inputs.local_reads_prod,
        )
        if summary_data.error_msg is not None:
            # If we weren't able to collect the required data - retry
            logger.exception(
                f"Not able to fetch data from the DB for session {inputs.session_id} (by user {inputs.user_id}): {summary_data.error_msg}",
                session_id=inputs.session_id,
                user_id=inputs.user_id,
            )
            raise ExceptionToRetry()
        input_data = prepare_single_session_summary_input(
            session_id=inputs.session_id,
            user_id=inputs.user_id,
            summary_data=summary_data,
        )
        # Store the input in Redis
        input_data_str = json.dumps(dataclasses.asdict(input_data))
        compressed_input_data = compress_redis_data(input_data_str)
        redis_client.setex(
            redis_input_key,
            SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
            compressed_input_data,
        )
    # Nothing to return if the fetch was successful, as the data is stored in Redis
    return None
