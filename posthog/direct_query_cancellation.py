import hashlib

from posthog import redis

DIRECT_QUERY_CANCELLATION_TTL_SECONDS = 60 * 20
DIRECT_QUERY_CANCELLATION_KEY_PREFIX = "direct_query_cancellation"


def build_direct_query_cancellation_token(query_id: str, task_id: str) -> str:
    return hashlib.sha256(f"{query_id}\0{task_id}".encode()).hexdigest()


def _direct_query_cancellation_key(team_id: int, cancellation_token: str) -> str:
    return f"{DIRECT_QUERY_CANCELLATION_KEY_PREFIX}:{team_id}:{cancellation_token}"


def request_direct_query_cancellation(team_id: int, cancellation_token: str) -> None:
    redis.get_client().set(
        _direct_query_cancellation_key(team_id, cancellation_token),
        "1",
        ex=DIRECT_QUERY_CANCELLATION_TTL_SECONDS,
    )


def is_direct_query_cancellation_requested(team_id: int, cancellation_token: str) -> bool:
    return bool(redis.get_client().get(_direct_query_cancellation_key(team_id, cancellation_token)))
