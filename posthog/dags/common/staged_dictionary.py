"""Staging a ClickHouse dictionary's rows through S3, for a cluster that cannot see its source.

A dictionary's source table reaches every host of one cluster because it is replicated, and
replication is exactly what a cluster boundary stops: a cluster with its own Keeper can never join
that replica set. Any mutation whose predicate joins a dictionary therefore cannot run on such a
cluster until the dictionary is there too.

ClickHouse has no S3 dictionary source, but ``SOURCE(CLICKHOUSE(...))`` runs its query on the local
host and that query can read anything the server can. So the rows go to one Parquet object and every
host on the other cluster loads it for itself, which also means both sides load identical bytes and
comparing their checksums means something.
"""

from collections.abc import Sequence
from functools import partial
from typing import Protocol

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common.s3_staging import S3StagingLocation
from posthog.dataclasses import frozen


@frozen
class StagedDictionary:
    """A dictionary's rows copied to one Parquet object, for clusters that share no Keeper.

    A dictionary's source table reaches every host of one cluster by replication, and replication
    is exactly what a cluster boundary stops: a cluster with its own Keeper can never join that
    replica set. An object each host reads for itself crosses the boundary instead, and both sides
    load identical bytes, which is what makes comparing their checksums meaningful.
    """

    key: str
    columns: str
    structure: str

    @property
    def __args(self) -> str:
        return S3StagingLocation.for_dictionaries().s3_args(self.key, "Parquet", self.structure)

    @property
    def query(self) -> str:
        """The dictionary SOURCE query, for hosts that cannot see the source table."""
        return f"SELECT {self.columns} FROM s3({self.__args})"

    def export(self, client: Client, source_query: str) -> None:
        # Truncate rather than append: a retried run has to leave the object holding this run's
        # rows alone, or the two clusters load different data and the checksum gate fails.
        client.execute(f"INSERT INTO FUNCTION s3({self.__args}) {source_query} SETTINGS s3_truncate_on_insert=1")


class StageableDictionary(Protocol):
    """The part of a dictionary that staging needs, shared by the two dictionary hierarchies."""

    @property
    def name(self) -> str: ...

    @property
    def query(self) -> str: ...

    def staged(self) -> StagedDictionary: ...

    def create(
        self, client: Client, shards: int, max_execution_time: int, max_memory_usage: int, query: str | None = None
    ) -> None: ...

    def recreate(
        self, client: Client, shards: int, max_execution_time: int, max_memory_usage: int, query: str | None = None
    ) -> None: ...

    def load(self, client: Client): ...


def create_on_every_cluster(
    context: dagster.OpExecutionContext,
    clusters: Sequence[ClickhouseCluster],
    dictionary: StageableDictionary,
    *,
    shards: int,
    max_execution_time: int,
    max_memory_usage: int,
) -> None:
    """Create ``dictionary`` on every cluster a mutation joining it will run on.

    ``clusters`` leads with the handle that can see the source table; the rest read a staged object,
    because they share no Keeper with it and so never receive the replicated table.
    """
    first, *rest = clusters
    first.map_all_hosts(
        partial(
            dictionary.create,
            shards=shards,
            max_execution_time=max_execution_time,
            max_memory_usage=max_memory_usage,
        )
    ).result()
    if not rest:
        return

    staged = dictionary.staged()
    first.any_host_by_role(partial(staged.export, source_query=dictionary.query), NodeRole.DATA).result()
    for cluster in rest:
        cluster.map_all_hosts(
            partial(
                dictionary.recreate,
                shards=shards,
                max_execution_time=max_execution_time,
                max_memory_usage=max_memory_usage,
                query=staged.query,
            )
        ).result()

    context.log.info(f"Staged {dictionary.name} to {staged.key} for {[c.data_cluster_name for c in rest]}")


def load_and_verify_on_every_cluster(clusters: Sequence[ClickhouseCluster], dictionary: StageableDictionary) -> None:
    """Load ``dictionary`` everywhere, and prove every host holds the same rows.

    Comparing checksums across clusters is what catches a stale or missing staged object. Without it
    the mutation there joins an empty dictionary, changes nothing, and reports success.

    Loading is serialized per cluster because it can consume a lot of CPU and memory, and running it
    on every host at once raises load across the whole cluster rather than spreading it.
    """
    by_cluster: dict[str, set[int]] = {}
    for cluster in clusters:
        results = cluster.map_all_hosts(dictionary.load, concurrency=1).result()
        by_cluster[cluster.data_cluster_name] = set(results.values())

    if len({checksum for checksums in by_cluster.values() for checksum in checksums}) != 1:
        raise dagster.Failure(
            description=f"{dictionary.name} does not hold the same rows on every host: "
            + ", ".join(f"{name}={sorted(checksums)}" for name, checksums in by_cluster.items())
        )
