import datetime
import itertools
from collections import defaultdict
from collections.abc import Iterator, Mapping
from typing import ClassVar, TypeVar, cast

import dagster
import pydantic
from clickhouse_driver import Client
from dateutil.relativedelta import relativedelta

from posthog import settings
from posthog.clickhouse.cluster import AlterTableMutationRunner, ClickhouseCluster, HostInfo

from dags.common import JobOwners

K1 = TypeVar("K1")
K2 = TypeVar("K2")
V = TypeVar("V")


def join_mappings(mappings: Mapping[K1, Mapping[K2, V]]) -> Mapping[K2, Mapping[K1, V]]:
    outer_keys = set()
    for inner_mapping in mappings.values():
        outer_keys.update(inner_mapping.keys())

    result = {}
    for outer_key in outer_keys:
        result[outer_key] = {}
        for inner_key, inner_mapping in mappings.items():
            if outer_key in inner_mapping:
                result[outer_key][inner_key] = inner_mapping[outer_key]

    return result


PartitionId = str


class PartitionRange(dagster.Config):
    lower: str
    upper: str

    FORMAT: ClassVar[str] = "%Y%m"

    def iter_dates(self) -> Iterator[str]:
        date_lower = self.parse_date(self.lower)
        date_upper = self.parse_date(self.upper)
        seq = itertools.count()
        while (date := date_lower + relativedelta(months=next(seq))) <= date_upper:
            yield date

    def iter_ids(self) -> Iterator[PartitionId]:
        for date in self.iter_dates():
            yield date.strftime(self.FORMAT)

    @pydantic.field_validator("lower", "upper")
    @classmethod
    def validate_format(cls, value: str) -> str:
        cls.parse_date(value)
        return value

    @pydantic.model_validator(mode="after")
    def validate_bounds(self):
        if not self.parse_date(self.lower) <= self.parse_date(self.upper):
            raise ValueError("expected lower bound to be less than (or equal to) upper bound")
        return self

    @classmethod
    def parse_date(cls, value: str) -> datetime.date:
        return datetime.datetime.strptime(value, cls.FORMAT).date()


class MaterializationConfig(dagster.Config):
    table: str
    columns: list[str]
    indexes: list[str]
    partitions: PartitionRange  # TODO: make optional for non-partitioned tables
    force: bool = False  # Force re-materialization of all columns even if they already exist

    def get_mutations_to_run(self, client: Client) -> Mapping[PartitionId, AlterTableMutationRunner]:
        columns_remaining_by_partition = defaultdict(set)

        if self.force:
            # When force is True, add all columns for all partitions in the range
            for partition in self.partitions.iter_ids():
                for column in self.columns:
                    columns_remaining_by_partition[partition].add(column)
        else:
            # The primary key column(s) should exist in all parts, so we can determine what parts (and partitions) do not
            # have the target column materialized by finding parts where the key column exists but the target column does
            # not.
            [[key_column]] = client.execute(
                """
                SELECT name
                FROM system.columns
                WHERE
                    database = %(database)s
                    AND table = %(table)s
                    AND is_in_primary_key
                ORDER BY position
                LIMIT 1
                """,
                {"database": settings.CLICKHOUSE_DATABASE, "table": self.table},
            )

            for column in self.columns:
                results = client.execute(
                    """
                    SELECT partition
                    FROM system.parts_columns
                    WHERE
                        database = %(database)s
                        AND table = %(table)s
                        AND part_type != 'Compact'  -- can't get column sizes from compact parts; should be small enough to ignore anyway
                        AND active
                        AND column IN (%(key_column)s, %(column)s)
                        AND partition IN %(partitions)s
                    GROUP BY partition
                    HAVING countIf(column = %(key_column)s) > countIf(column = %(column)s)
                    ORDER BY partition DESC
                    """,
                    {
                        "database": settings.CLICKHOUSE_DATABASE,
                        "table": self.table,
                        "key_column": key_column,
                        "column": column,
                        "partitions": [*self.partitions.iter_ids()],
                    },
                )
                for [partition] in results:
                    columns_remaining_by_partition[partition].add(column)

        mutations = {}

        for partition in self.partitions.iter_ids():
            commands = set()

            for column in columns_remaining_by_partition[partition]:
                commands.add(f"MATERIALIZE COLUMN {column} IN PARTITION %(partition)s")

            # XXX: there is no way to determine whether or not the index already exists, so unfortunately we need to
            # materialize it unconditionally
            for index in self.indexes:
                commands.add(f"MATERIALIZE INDEX {index} IN PARTITION %(partition)s")

            if commands:
                mutations[partition] = AlterTableMutationRunner(
                    table=self.table, commands=commands, parameters={"partition": partition}, force=self.force
                )

        return mutations


T = TypeVar("T")


def _convert_hostinfo_keys_to_shard_num(input: Mapping[HostInfo, T]) -> Mapping[int, T]:
    """Convert the keys of the input mapping to (non-optional) shard numbers."""
    # this is mostly to appease the type checker, as the shard operations on the cluster interface do not have a method
    # to return a shard_num that is non-optional. this should be able to be removed in the future once that is improved
    result = {host.shard_num: value for host, value in input.items()}
    assert None not in result.keys()
    return cast(Mapping[int, T], result)


@dagster.op
def run_materialize_mutations(
    context: dagster.OpExecutionContext,
    config: MaterializationConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    # Since this is only being run on a single host in the shard, we're assuming that the other hosts either have the
    # same set of partitions already materialized, or that a materialization mutation already exists (and is running) if
    # they are lagging behind. (If _this_ host is lagging behind the others, the mutation runner should prevent us from
    # scheduling duplicate mutations on the shard.)
    mutations_to_run_by_shard = _convert_hostinfo_keys_to_shard_num(
        cluster.map_one_host_per_shard(config.get_mutations_to_run).result()
    )

    shard_mutations_to_run_by_partition = join_mappings(mutations_to_run_by_shard)
    for partition_id, shard_mutations in sorted(shard_mutations_to_run_by_partition.items(), reverse=True):
        context.log.info("Starting %s materializations for partition %r...", len(shard_mutations), partition_id)
        shard_waiters = _convert_hostinfo_keys_to_shard_num(cluster.map_any_host_in_shards(shard_mutations).result())
        cluster.map_all_hosts_in_shards(shard_waiters).result()
        context.log.info("Completed materializations for partition %r!", partition_id)


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def materialize_column():
    run_materialize_mutations()
