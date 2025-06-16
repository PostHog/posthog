import dataclasses
import gzip
import json
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext, SingleSessionSummaryLlmInputs
from redis import Redis


@dataclasses.dataclass(frozen=True, kw_only=True)
class SingleSessionSummaryInputs:
    """Workflow input to get summary for a single session"""

    session_id: str
    user_pk: int
    team_id: int
    redis_input_key: str
    redis_output_key: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


def compress_llm_input_data(llm_input_data: SingleSessionSummaryLlmInputs) -> bytes:
    return gzip.compress(json.dumps(dataclasses.asdict(llm_input_data)).encode("utf-8"))


def get_single_session_summary_llm_input_from_redis(
    redis_client: Redis, redis_input_key: str
) -> SingleSessionSummaryLlmInputs:
    raw_redis_data = redis_client.get(redis_input_key)
    if not raw_redis_data:
        raise ValueError(f"Single session summary LLM input data not found in Redis for key {redis_input_key}")
    try:
        # Decompress the data
        if isinstance(raw_redis_data, bytes):
            redis_data_str = gzip.decompress(raw_redis_data).decode("utf-8")
        else:
            # Fallback for uncompressed data (if stored as string)
            redis_data_str = raw_redis_data
        redis_data = SingleSessionSummaryLlmInputs(**json.loads(redis_data_str))
    except Exception as e:
        raise ValueError(
            f"Failed to parse single session summary LLM input data ({raw_redis_data}) for Redis key {redis_input_key}: {e}"
        )
    return redis_data
