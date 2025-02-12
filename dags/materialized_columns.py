import concurrent.futures
import datetime
import itertools
from collections.abc import Iterator
from typing import ClassVar

import dagster
from clickhouse_driver import Client
from dateutil.relativedelta import relativedelta
from pydantic import validator

from posthog import settings
from posthog.clickhouse.cluster import ClickhouseCluster, MutationRunner


class PartitionRange(dagster.Config):
    lower: str
    upper: str

    FORMAT: ClassVar[str] = "%Y%m"

    def __iter__(self) -> Iterator[str]:
        date_lower = self.parse_date(self.lower)
        date_upper = self.parse_date(self.upper)
        seq = itertools.count()
        while (cur_date := date_lower + relativedelta(months=next(seq))) <= date_upper:
            yield cur_date.strftime(self.FORMAT)

    @validator("lower", "upper")
    @classmethod
    def validate_format(cls, value: str) -> str:
        cls.parse_date(value)
        return value

    @classmethod
    def parse_date(cls, value: str) -> datetime.date:
        return datetime.datetime.strptime(value, cls.FORMAT).date()


class MaterializeColumnConfig(dagster.Config):
    table: str
    column: str  # TODO: maybe make this a list/set so we can minimize the number of mutations?
    partitions: PartitionRange  # TODO: make optional for non-partitioned tables


@dagster.op
def run_materialize_mutations(
    context: dagster.OpExecutionContext,
    config: MaterializeColumnConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    def materialize_column_for_shard(client: Client) -> None:
        # The primary key column(s) should exist in all parts, so we can determine what parts (and partitions) do not
        # have the target column materialized by finding parts where the key column exists but the target column does
        # not. Since this is only being run on a single host in the shard, we're assuming that the other hosts either
        # have the same set of partitions already materialized, or that a materialization mutation already exists (and
        # is running) if they are lagging behind. (If _this_ host is lagging behind the others, the mutation runner
        # should prevent us from scheduling duplicate mutations on the shard.)
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
            {"database": settings.CLICKHOUSE_DATABASE, "table": config.table},
        )

        requested_partitions = set(config.partitions)
        remaining_partitions = {
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
                    "table": config.table,
                    "key_column": key_column,
                    "column": config.column,
                    "partitions": [*requested_partitions],
                },
            )
        }

        context.log.info(
            "Materializing %s of %s requested partitions (%s already materialized)",
            len(remaining_partitions),
            len(requested_partitions),
            len(requested_partitions - remaining_partitions),
        )
        for partition in remaining_partitions:
            mutation = MutationRunner(
                config.table,
                "MATERIALIZE COLUMN %(column)s IN PARTITION %(partition)s",
                {"column": config.column, "partition": partition},
            ).enqueue(client)
            mutation.wait()

    cluster.map_one_host_per_shard(materialize_column_for_shard).result(
        # avoid getting into a situation where some shards stop making progress while others continue
        return_when=concurrent.futures.FIRST_EXCEPTION,
    )


@dagster.job
def materialize_column():
    run_materialize_mutations()
