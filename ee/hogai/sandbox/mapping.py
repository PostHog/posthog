from __future__ import annotations

from django_redis import get_redis_connection

SANDBOX_MAPPING_PREFIX = "conversation-sandbox:"
SANDBOX_MAPPING_TTL = 24 * 60 * 60  # 24 hours


def _key(conversation_id: str) -> str:
    return f"{SANDBOX_MAPPING_PREFIX}{conversation_id}"


def set_sandbox_mapping(conversation_id: str, task_id: str, run_id: str) -> None:
    conn = get_redis_connection("default")
    key = _key(conversation_id)
    conn.hset(key, mapping={"task_id": task_id, "run_id": run_id})
    conn.expire(key, SANDBOX_MAPPING_TTL)


def get_sandbox_mapping(conversation_id: str) -> dict[str, str] | None:
    conn = get_redis_connection("default")
    data = conn.hgetall(_key(conversation_id))
    if not data:
        return None
    return {k.decode(): v.decode() for k, v in data.items()}


def clear_sandbox_mapping(conversation_id: str) -> None:
    conn = get_redis_connection("default")
    conn.delete(_key(conversation_id))
