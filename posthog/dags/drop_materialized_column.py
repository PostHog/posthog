from typing import Literal

import dagster

from posthog.dags.common import JobOwners


class DropMaterializedColumnConfig(dagster.Config):
    table: Literal["events", "person"] = "events"
    column_names: list[str]
    dry_run: bool = True


@dagster.op
def drop_materialized_columns_op(
    context: dagster.OpExecutionContext,
    config: DropMaterializedColumnConfig,
):
    from ee.clickhouse.materialized_columns.columns import drop_column

    if config.dry_run:
        context.log.warning(
            f"Dry run: would drop {len(config.column_names)} columns from {config.table}: {config.column_names}"
        )
        return

    context.log.info(f"Dropping {len(config.column_names)} columns from {config.table}: {config.column_names}")
    drop_column(config.table, config.column_names)
    context.log.info("Done.")


@dagster.job(tags={"owner": JobOwners.TEAM_CLICKHOUSE.value})
def drop_materialized_column():
    drop_materialized_columns_op()
