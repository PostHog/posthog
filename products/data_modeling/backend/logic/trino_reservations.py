"""Per-model reservations that keep two Trino runs from building the same model at once.

A manual run reserves every model it selected for the whole run. A scheduled run reserves each model only
while it builds it. Both use the same Redis key, so whichever reserves first wins and the other skips or refuses.
"""

import json
import time
import asyncio
from datetime import timedelta
from typing import cast

import redis
from temporalio.client import Client

from posthog.redis import get_client
from posthog.temporal.data_modeling.activities.preempt_dag_run import workflow_has_closed
from posthog.temporal.data_modeling.workflows.execute_dag import TRINO_SHADOW_RUN_TIMEOUT

# A reservation is taken before its workflow exists, so Temporal can't vouch for it during this window.
RESERVATION_START_GRACE = timedelta(minutes=1)


class Liveness:
    """Answers whether a reservation's workflow is still running, asking Temporal once per workflow."""

    def __init__(self, temporal: Client) -> None:
        self.temporal = temporal
        self.closed: dict[str, bool] = {}

    def holds(self, holder: dict) -> bool:
        if time.time() - holder["at"] < RESERVATION_START_GRACE.total_seconds():
            return True
        workflow_id = holder["workflow_id"]
        if workflow_id not in self.closed:
            self.closed[workflow_id] = asyncio.run(workflow_has_closed(self.temporal, workflow_id))
        return not self.closed[workflow_id]


def _key(team_id: int, node_id: str) -> str:
    return f"data_modeling:trino_run:{team_id}:{node_id}"


def reserve_trino_models(
    liveness: Liveness, team_id: int, node_ids: set[str], workflow_id: str, *, manual: bool
) -> tuple[list[str], list[str]]:
    """Reserve each model for this workflow. Returns the node ids reserved and those another live run holds.

    Reserving in sorted order means two overlapping requests contend on the same first model, so one wins.
    """
    client = get_client()
    value = json.dumps({"workflow_id": workflow_id, "at": time.time(), "manual": manual})
    ttl = int(TRINO_SHADOW_RUN_TIMEOUT.total_seconds())
    reserved: list[str] = []
    for node_id in sorted(node_ids):
        key = _key(team_id, node_id)
        if client.set(key, value, nx=True, ex=ttl) or _take_over_ended(liveness, client, key, value, ttl):
            reserved.append(node_id)
        else:
            return reserved, [node_id]
    return reserved, []


def _take_over_ended(liveness: Liveness, client: redis.Redis, key: str, value: str, ttl: int) -> bool:
    """Replace a reservation whose run has ended. False when its run is still live or another request won."""
    with client.pipeline() as pipe:
        try:
            pipe.watch(key)
            held = cast(bytes | None, pipe.get(key))
            if held is not None and liveness.holds(json.loads(held)):
                return False
            pipe.multi()
            pipe.set(key, value, ex=ttl)
            pipe.execute()
            return True
        except redis.WatchError:
            return False


def release_trino_reservations(team_id: int, node_ids: list[str], workflow_id: str) -> None:
    client = get_client()
    for node_id in node_ids:
        key = _key(team_id, node_id)
        held = client.get(key)
        if held is not None and json.loads(held)["workflow_id"] == workflow_id:
            client.delete(key)


def manually_reserved_trino_models(liveness: Liveness, team_id: int, node_ids: set[str]) -> set[str]:
    """The node ids a live manual run has reserved, which a scheduled run must neither build nor preempt."""
    client = get_client()
    ordered = sorted(node_ids)
    held = client.mget([_key(team_id, node_id) for node_id in ordered]) if ordered else []
    return {
        node_id
        for node_id, value in zip(ordered, held)
        if value is not None and (holder := json.loads(value)).get("manual") and liveness.holds(holder)
    }
