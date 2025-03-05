import datetime
import itertools
from collections.abc import Iterator
from functools import reduce
from typing import ClassVar

import dagster
import pydantic
from clickhouse_driver import Client
from dateutil.relativedelta import relativedelta

from dags.common import JobOwners
from posthog import settings
from posthog.clickhouse.cluster import ClickhouseCluster, AlterTableMutationRunner


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

    def iter_ids(self) -> Iterator[str]:
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


class MaterializeColumnConfig(dagster.Config):
    table: str
    column: str  # TODO: maybe make this a list/set so we can minimize the number of mutations?
    partitions: PartitionRange  # TODO: make optional for non-partitioned tables

    def get_remaining_partitions(self, client: Client) -> set[str]:
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

        return {
            partition
            for [partition] in client.execute(
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
                    "column": self.column,
                    "partitions": [*self.partitions.iter_ids()],
                },
            )
        }


@dagster.op
def run_materialize_mutations(
    context: dagster.OpExecutionContext,
    config: MaterializeColumnConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    # Since this is only being run on a single host in the shard, we're assuming that the other hosts either have the
    # same set of partitions already materialized, or that a materialization mutation already exists (and is running) if
    # they are lagging behind. (If _this_ host is lagging behind the others, the mutation runner should prevent us from
    # scheduling duplicate mutations on the shard.)
    remaining_partitions_by_shard = {
        host.shard_num: partitions
        for host, partitions in cluster.map_one_host_per_shard(config.get_remaining_partitions).result().items()
    }

    requested_partitions = set(config.partitions.iter_ids())
    remaining_partitions = reduce(lambda x, y: x | y, remaining_partitions_by_shard.values())
    context.log.info(
        "Materializing %s of %s requested partitions (%s already materialized in all shards)",
        len(remaining_partitions),
        len(requested_partitions),
        len(requested_partitions - remaining_partitions),
    )

    # Step through the remaining partitions, materializing the column in any shards where the column hasn't already been
    # materialized.
    for partition in sorted(remaining_partitions, reverse=True):
        AlterTableMutationRunner(
            config.table,
            f"MATERIALIZE COLUMN {config.column} IN PARTITION %(partition)s",
            parameters={"partition": partition},
        ).run_on_shards(
            cluster,
            shards={
                shard_num
                for shard_num, remaining_partitions_for_shard in remaining_partitions_by_shard.items()
                if partition in remaining_partitions_for_shard
            },
        )


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def materialize_column():
    run_materialize_mutations()
