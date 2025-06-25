import dataclasses
import gzip
import json
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext, SingleSessionSummaryLlmInputs
from redis import Redis
from ee.session_recordings.session_summary.summarize_session import (
    prepare_data_for_single_session_summary,
    prepare_single_session_summary_input,
)
import structlog
from ee.session_recordings.session_summary import ExceptionToRetry
import temporalio
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

# How long to store the DB data in Redis within Temporal session summaries jobs
SESSION_SUMMARIES_DB_DATA_REDIS_TTL = 60 * 60  # 60 minutes to keep alive for retries and long-running workflows


@dataclasses.dataclass(frozen=True, kw_only=True)
class SingleSessionSummaryInputs:
    """Workflow input to get summary for a single session"""

    session_id: str
    user_id: int
    team_id: int
    redis_input_key: str
    redis_output_key: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


@temporalio.activity.defn
async def fetch_session_data_activity(inputs: SingleSessionSummaryInputs) -> str | None:
    """Fetch data from DB for a single session and store/cache in Redis (to avoid hitting Temporal memory limits)"""
    redis_client = get_client()
    try:
        # Check if DB data is already in Redis. If it is - it's within TTL, so no need to re-fetch it from DB
        # TODO: Think about edge-cases like still-running sessions (could be solved with checking statuses)
        input_data = get_single_session_summary_llm_input_from_redis(
            redis_client=redis_client,
            redis_input_key=inputs.redis_input_key,
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
            inputs.redis_input_key,
            SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
            compressed_input_data,
        )
    # Nothing to return if the fetch was successful, as the data is stored in Redis
    return None


def compress_redis_data(input_data: str) -> bytes:
    return gzip.compress(input_data.encode("utf-8"))


def _decompress_redis_data(raw_redis_data: bytes) -> str:
    if isinstance(raw_redis_data, bytes):
        return gzip.decompress(raw_redis_data).decode("utf-8")
    else:
        # Fallback for uncompressed data (if stored as string)
        return raw_redis_data


def get_single_session_summary_llm_input_from_redis(
    redis_client: Redis, redis_input_key: str
) -> SingleSessionSummaryLlmInputs:
    raw_redis_data = redis_client.get(redis_input_key)
    if not raw_redis_data:
        raise ValueError(f"Single session summary LLM input data not found in Redis for key {redis_input_key}")
    try:
        redis_data_str = _decompress_redis_data(raw_redis_data)
        redis_data = SingleSessionSummaryLlmInputs(**json.loads(redis_data_str))
    except Exception as e:
        raise ValueError(
            f"Failed to parse single session summary LLM input data ({raw_redis_data}) for Redis key {redis_input_key}: {e}"
        ) from e
    return redis_data


def get_single_session_summary_output_from_redis(redis_client: Redis, redis_output_key: str) -> str:
    raw_redis_data = redis_client.get(redis_output_key)
    if not raw_redis_data:
        raise ValueError(f"Single session summary LLM output data not found in Redis for key {redis_output_key}")
    try:
        redis_data_str = _decompress_redis_data(raw_redis_data)
    except Exception as e:
        raise ValueError(
            f"Failed to decompress single session summary LLM output data ({raw_redis_data}) for Redis key {redis_output_key}: {e}"
        ) from e
    return redis_data_str
