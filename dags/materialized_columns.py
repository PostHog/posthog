import concurrent.futures
import datetime
import itertools
from collections.abc import Iterator

import dagster
from clickhouse_driver import Client
from dateutil.relativedelta import relativedelta


from posthog import settings
from posthog.clickhouse.cluster import ClickhouseCluster, MutationRunner


class MaterializeColumnConfig(dagster.Config):
    table: str
    column: str  # TODO: maybe make this a list/set so we can minimize the number of mutations?
    from_partition: str
    to_partition: str

    def partitions(self) -> Iterator[str]:
        format = "%Y%m"
        [from_date, to_date] = [
            datetime.datetime.strptime(partition_str, format).date()
            for partition_str in [self.from_partition, self.to_partition]
        ]
        seq = itertools.count()
        while (cur_date := from_date + relativedelta(months=next(seq))) <= to_date:
            yield cur_date.strftime(format)


@dagster.op
def run_materialize_mutations(config: MaterializeColumnConfig, cluster: dagster.ResourceParam[ClickhouseCluster]):
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

        remaining_partitions = client.execute(
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
                "partitions": config.partitions,
            },
        )

        for [partition] in remaining_partitions:
            mutation = MutationRunner(
                config.table,
                "MATERIALIZE COLUMN %(column)s IN PARTITION %(partition)s",
                {"column": settings.column, "partition": partition},
            ).enqueue(client)
            mutation.wait()

    cluster.map_one_host_per_shard(materialize_column_for_shard).result(
        # avoid getting into a situation where some shards stop making progress while others continue
        return_when=concurrent.futures.FIRST_EXCEPTION,
    )


@dagster.job
def materialize_column():
    run_materialize_mutations()
