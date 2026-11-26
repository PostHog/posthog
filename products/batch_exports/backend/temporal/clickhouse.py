"""The ClickHouse endpoint a batch export query connects to.

`get_client` connects a project's query to the events cluster when the switches that move the rest of PostHog to
events_json include the project. A batch export can read a table those switches did not choose: the events model reads
the table of `batch_exports_read_new_events_table`, and the persons and sessions models read tables of the main
cluster. Batch exports connect through this module, which follows the table the query reads.
"""

import typing
import contextlib
import collections.abc

from django.conf import settings

from posthog.clickhouse.workload import PINNED_CLUSTER_WORKLOADS, Workload
from posthog.dataclasses import frozen
from posthog.temporal.common.clickhouse import ClickHouseClient, get_client


@frozen
class ClickHouseEndpoint:
    url: str
    cluster: str


def resolve_clickhouse_endpoint(
    *,
    reads_new_events_table: bool,
    reads_recent_events: bool = False,
) -> ClickHouseEndpoint:
    """The offline endpoint for a batch export query on the main, events or batch exports cluster.

    Arguments:
        reads_new_events_table: Whether the query reads events_json or events_json_recent. The events model
            decides this with `batch_exports_read_new_events_table`, and a HogQL export with its printed context.
            A query that reads no events table, such as a persons or sessions query, passes False.
        reads_recent_events: Whether the query reads a recent events table, which the batch exports cluster stores.
    """
    if reads_recent_events and settings.CLICKHOUSE_BATCH_EXPORTS_HTTP_URL:
        return ClickHouseEndpoint(
            url=settings.CLICKHOUSE_BATCH_EXPORTS_HTTP_URL, cluster=settings.CLICKHOUSE_BATCH_EXPORTS_CLUSTER
        )

    if reads_new_events_table and settings.CLICKHOUSE_EVENTS_OFFLINE_HTTP_URL:
        return ClickHouseEndpoint(
            url=settings.CLICKHOUSE_EVENTS_OFFLINE_HTTP_URL, cluster=settings.CLICKHOUSE_EVENTS_CLUSTER
        )

    return ClickHouseEndpoint(url=settings.CLICKHOUSE_OFFLINE_HTTP_URL, cluster=settings.CLICKHOUSE_CLUSTER)


@contextlib.asynccontextmanager
async def get_batch_exports_client(
    *,
    team_id: int,
    reads_new_events_table: bool,
    reads_recent_events: bool = False,
    workload: Workload = Workload.OFFLINE,
    **kwargs: typing.Any,
) -> collections.abc.AsyncIterator[ClickHouseClient]:
    """A `get_client` client connected to the endpoint of `resolve_clickhouse_endpoint`.

    Every batch export query from a Temporal activity connects through this function, never through
    `get_client(team_id=...)` alone. The debugger builds a sync client for `resolve_clickhouse_endpoint` instead.
    """
    # A HogQL export that reads logs or metrics reads tables that only their own cluster stores.
    if workload in PINNED_CLUSTER_WORKLOADS:
        async with get_client(team_id=team_id, workload=workload, **kwargs) as client:
            yield client
        return

    # The resolver only knows the offline hosts, because no person waits on a batch export.
    if workload not in (Workload.DEFAULT, Workload.OFFLINE):
        raise ValueError(f"Batch exports run OFFLINE queries, not {workload}")

    endpoint = resolve_clickhouse_endpoint(
        reads_new_events_table=reads_new_events_table,
        reads_recent_events=reads_recent_events,
    )
    async with get_client(
        team_id=team_id, workload=workload, clickhouse_url=endpoint.url, cluster=endpoint.cluster, **kwargs
    ) as client:
        yield client
