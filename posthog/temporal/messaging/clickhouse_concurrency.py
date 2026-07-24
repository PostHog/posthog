import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from django.conf import settings

from posthog.temporal.common.clickhouse import ClickHouseClient, get_client

# Limits concurrent offline-cluster ClickHouse queries across the messaging workflow family
# (reconcile-precalculated-data, realtime-cohort-calculation, and the precalculated backfills).
# They all run on one worker process with a single event loop, so this module-level semaphore
# gates every messaging activity on the same worker. Acquiring a slot before opening
# `get_client()` turns an over-cap situation into in-process backpressure (waiting) instead of a
# ClickHouse TOO_MANY_SIMULTANEOUS_QUERIES rejection. The cap is per worker process; aggregate =
# this value times messaging worker replicas.
#
# This does not coordinate with other offline consumers: data_modeling runs its own independent
# semaphore against the same offline `default` user, on a separate task queue / worker / event
# loop (see data_modeling/activities/materialize_view.py). The real cluster-wide budget is the
# sum across all such families, so keep this value low enough to leave them headroom under 30.
#
# Floored at 1: a size of 0 (misconfigured env) would deadlock every gated activity forever, since
# no permit is ever released.
messaging_clickhouse_query_semaphore = asyncio.Semaphore(max(1, settings.MESSAGING_CLICKHOUSE_MAX_CONCURRENT_QUERIES))


@asynccontextmanager
async def get_messaging_client(team_id: int) -> AsyncIterator[ClickHouseClient]:
    """Open a ClickHouse client while holding a messaging query slot.

    Every messaging offline-cluster query must go through here so the per-worker concurrency cap
    can't be defeated by a call site that forgets to acquire the semaphore first.
    """
    async with messaging_clickhouse_query_semaphore, get_client(team_id=team_id) as client:
        yield client
