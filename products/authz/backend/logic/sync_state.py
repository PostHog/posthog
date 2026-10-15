from typing import cast
from uuid import UUID, uuid4

from redis.exceptions import WatchError

from posthog import redis

# Older projections omit warehouse objects; their ready state must not authorize the new routes.
READY_PREFIX = b"ready:v2:"


def state_key(organization_id: UUID) -> str:
    return f"authz:sync-state:{organization_id}"


def current_state(organization_id: UUID) -> bytes | None:
    return redis.get_client().get(state_key(organization_id))


def mark_pending(organization_id: UUID) -> bytes:
    state = f"pending:{uuid4()}".encode()
    redis.get_client().set(state_key(organization_id), state)
    return state


def mark_ready(organization_id: UUID, pending: bytes) -> None:
    key = state_key(organization_id)
    with redis.get_client().pipeline() as pipeline:
        try:
            pipeline.watch(key)
            if cast(bytes | None, pipeline.get(key)) == pending:
                pipeline.multi()
                pipeline.set(key, READY_PREFIX + pending.removeprefix(b"pending:"))
                pipeline.execute()
        except WatchError:
            # A later commit is pending and its reconciliation must publish readiness.
            return
