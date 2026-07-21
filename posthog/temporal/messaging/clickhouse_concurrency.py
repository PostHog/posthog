import asyncio

from django.conf import settings

# Limits concurrent offline-cluster ClickHouse queries across the messaging workflow family
# (reconcile-precalculated-data and realtime-cohort-calculation). They all run on one worker
# process with a single event loop, so this module-level semaphore gates every messaging activity
# on the same worker. Acquiring a slot before opening `get_client()` turns an over-cap situation
# into in-process backpressure (waiting) instead of a ClickHouse TOO_MANY_SIMULTANEOUS_QUERIES
# rejection. The cap is per worker process; aggregate = this value times messaging worker replicas.
#
# Floored at 1: a size of 0 (misconfigured env) would deadlock every gated activity forever, since
# no permit is ever released.
messaging_clickhouse_query_slot = asyncio.Semaphore(max(1, settings.MESSAGING_CLICKHOUSE_MAX_CONCURRENT_QUERIES))
