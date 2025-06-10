from contextlib import contextmanager
import uuid
from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client


def _get_hash_key(team_id: int) -> str:
    return f"posthog:data_warehouse_row_tracking:{team_id}"


@contextmanager
def _get_redis():
    try:
        # Ensure redis is up and alive
        redis = get_client()
        redis.ping()

        yield redis
    except Exception as e:
        capture_exception(e)
        yield None


def setup_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    with _get_redis() as redis:
        if not redis:
            return

        redis.hset(_get_hash_key(team_id), str(schema_id), 0)
        redis.expire(_get_hash_key(team_id), 60 * 60 * 24 * 7)  # 7 day expire


def increment_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    with _get_redis() as redis:
        if not redis:
            return

        redis.hincrby(_get_hash_key(team_id), str(schema_id), rows)


def decrement_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    with _get_redis() as redis:
        if not redis:
            return

        if not redis.hexists(_get_hash_key(team_id), str(schema_id)):
            return

        value = redis.hget(_get_hash_key(team_id), str(schema_id))
        if not value:
            return

        value_int = int(value)
        if value_int - rows < 0:
            redis.hset(_get_hash_key(team_id), str(schema_id), 0)
        else:
            redis.hincrby(_get_hash_key(team_id), str(schema_id), -rows)


def finish_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    with _get_redis() as redis:
        if not redis:
            return

        redis.hdel(_get_hash_key(team_id), str(schema_id))


def get_rows(team_id: int, schema_id: uuid.UUID | str) -> int:
    with _get_redis() as redis:
        if not redis:
            return 0

        if redis.hexists(_get_hash_key(team_id), str(schema_id)):
            value = redis.hget(_get_hash_key(team_id), str(schema_id))
            if value:
                return int(value)

        return 0
