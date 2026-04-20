from typing import Literal

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners
from posthog.settings import TEST

from ee.clickhouse.materialized_columns.columns import (
    BloomFilterIndex,
    MaterializedColumn,
    MinMaxIndex,
    NgramLowerIndex,
    check_index_exists,
    get_materialized_columns,
    tables,
)


class AddIndexConfig(dagster.Config):
    table: Literal["events", "person"] = "events"
    column_names: list[str]
    add_minmax_index: bool = False
    add_bloom_filter_index: bool = False
    add_ngram_lower_index: bool = False
    dry_run: bool = False


class AddIndexTask:
    def __init__(
        self,
        table: str,
        column_name: str,
        is_nullable: bool,
        add_minmax: bool,
        add_bloom_filter: bool,
        add_ngram_lower: bool,
        dry_run: bool,
        logger: dagster.DagsterLogManager,
    ):
        self.table = table
        self.column_name = column_name
        self.is_nullable = is_nullable
        self.add_minmax = add_minmax
        self.add_bloom_filter = add_bloom_filter
        self.add_ngram_lower = add_ngram_lower
        self.dry_run = dry_run
        self.logger = logger

    def execute(self, client: Client) -> None:
        actions = []

        if self.add_minmax:
            minmax_index = MinMaxIndex(self.column_name)
            if check_index_exists(client, self.table, minmax_index.name):
                self.logger.info(f"Skipping minmax index {minmax_index.name}, already exists")
            else:
                actions.append(minmax_index.as_add_sql())

        if self.add_bloom_filter:
            bloom_index = BloomFilterIndex(self.column_name)
            if check_index_exists(client, self.table, bloom_index.name):
                self.logger.info(f"Skipping bloom_filter index {bloom_index.name}, already exists")
            else:
                actions.append(bloom_index.as_add_sql())

        if self.add_ngram_lower:
            ngram_index = NgramLowerIndex(self.column_name, self.is_nullable)
            if check_index_exists(client, self.table, ngram_index.name):
                self.logger.info(f"Skipping ngram_bf_lower index {ngram_index.name}, already exists")
            else:
                actions.append(ngram_index.as_add_sql())

        if not actions:
            self.logger.info(f"No indexes to add for column {self.column_name}")
            return

        sql = f"ALTER TABLE {self.table} " + ", ".join(actions)

        if self.dry_run:
            self.logger.info(f"Dry run - would execute: {sql}")
        else:
            self.logger.info(f"Executing: {sql}")
            client.execute(sql, settings={"alter_sync": 2 if TEST else 1})


def find_materialized_column(table: str, column_name: str) -> MaterializedColumn | None:
    for column in get_materialized_columns(table).values():
        if column.name == column_name:
            return column
    return None


@dagster.op
def add_indexes_to_columns(
    context: dagster.OpExecutionContext,
    config: AddIndexConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    if not config.add_minmax_index and not config.add_bloom_filter_index and not config.add_ngram_lower_index:
        context.log.warning("No index types selected. Nothing to do.")
        return

    table_info = tables[config.table]
    data_table = table_info.data_table

    for column_name in config.column_names:
        context.log.info(f"Processing column: {column_name}")

        column = find_materialized_column(config.table, column_name)
        if column is None:
            raise ValueError(
                f"Column '{column_name}' does not exist as a materialized column in table '{config.table}'"
            )

        context.log.info(f"Column {column_name} exists (nullable={column.is_nullable})")

        task = AddIndexTask(
            table=data_table,
            column_name=column_name,
            is_nullable=column.is_nullable,
            add_minmax=config.add_minmax_index,
            add_bloom_filter=config.add_bloom_filter_index,
            add_ngram_lower=config.add_ngram_lower_index,
            dry_run=config.dry_run,
            logger=context.log,
        )

        table_info.map_data_nodes(cluster, task.execute).result()
        context.log.info(f"Finished processing column: {column_name}")


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def add_index_to_materialized_column():
    add_indexes_to_columns()
