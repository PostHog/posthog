"""Helpers for jobs that read and write one ClickHouse shard at a time."""

from collections.abc import Callable
from typing import Any, TypeVar

from clickhouse_driver import Client

from posthog.schema import ProductKey

from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import DagsterTags, Feature, tags_context
from posthog.cloud_utils import is_cloud

T = TypeVar("T")


def shard_workload() -> tuple[Workload, NodeRole]:
    return (Workload.OFFLINE, NodeRole.DATA) if is_cloud() else (Workload.DEFAULT, NodeRole.ALL)


def tagged(query_tags: DagsterTags, fn: Callable[[Client], T], *, product: ProductKey) -> Callable[[Client], T]:
    # The cluster runs fn on a pool thread. The query tags do not cross into that thread.
    def run(client: Client) -> T:
        with tags_context(kind="dagster", dagster=query_tags, product=product, feature=Feature.BACKFILL):
            return fn(client)

    return run


def on_shard_host(
    cluster: ClickhouseCluster,
    shard_num: int,
    fn: Callable[[Client], T],
    query_tags: DagsterTags,
    workload: Workload,
    node_role: NodeRole,
    *,
    product: ProductKey,
) -> T:
    host = cluster.any_host_in_shard_by_roles(shard_num, [node_role], workload)
    return cluster.on_host(host, tagged(query_tags, fn, product=product)).result()


def inserted_rows(result: Any) -> int:
    # sync_execute returns the written row count for an INSERT that wrote rows. It returns
    # an empty result for an INSERT that wrote none.
    return result if isinstance(result, int) else 0
