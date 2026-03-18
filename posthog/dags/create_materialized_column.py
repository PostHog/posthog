from typing import Literal

import dagster

from posthog.dags.common import JobOwners


class MaterializeColumnConfig(dagster.Config):
    table: Literal["events", "person"] = "events"
    table_column: Literal["properties", "group_properties", "person_properties"] = "properties"
    properties: list[str]
    backfill_period_days: int = 90
    dry_run: bool = False
    is_nullable: bool = True


@dagster.op
def create_materialized_columns_op(
    context: dagster.OpExecutionContext,
    config: MaterializeColumnConfig,
):
    from ee.clickhouse.materialized_columns.analyze import materialize_properties_task

    if config.dry_run:
        context.log.warning("Dry run: No changes to the tables will be made!")

    context.log.info(f"Materializing column. table={config.table}, properties={config.properties}")

    materialize_properties_task(
        properties_to_materialize=[(config.table, config.table_column, prop) for prop in config.properties],
        backfill_period_days=config.backfill_period_days,
        dry_run=config.dry_run,
        is_nullable=config.is_nullable,
    )


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def create_materialized_column():
    create_materialized_columns_op()
