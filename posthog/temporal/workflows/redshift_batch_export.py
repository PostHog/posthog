import datetime as dt
import json
from dataclasses import dataclass

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.service import RedshiftBatchExportInputs
from posthog.temporal.workflows.base import PostHogWorkflow
from posthog.temporal.workflows.batch_exports import (
    CreateBatchExportRunInputs,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    execute_batch_export_insert_activity,
    get_batch_exports_logger,
    get_data_interval,
)
from posthog.temporal.workflows.postgres_batch_export import (
    PostgresInsertInputs,
    insert_into_postgres_activity,
)


@dataclass
class RedshiftInsertInputs(PostgresInsertInputs):
    """Inputs for Redshift insert activity.

    Inherit from PostgresInsertInputs as they are the same, but
    update fields to account for JSONB not being supported in Redshift.
    """

    fields: list[tuple[str, str]] = [
        ("uuid", "VARCHAR(200)"),
        ("event", "VARCHAR(200)"),
        ("properties", "VARCHAR"),
        ("elements", "VARCHAR"),
        ("set", "VARCHAR"),
        ("set_once", "VARCHAR"),
        ("distinct_id", "VARCHAR(200)"),
        ("team_id", "INTEGER"),
        ("ip", "VARCHAR(200)"),
        ("site_url", "VARCHAR(200)"),
        ("timestamp", "TIMESTAMP WITH TIME ZONE"),
    ]


@workflow.defn(name="redshift-export")
class RedshiftBatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into Postgres.

    This Workflow is intended to be executed both manually and by a Temporal
    Schedule. When ran by a schedule, `data_interval_end` should be set to
    `None` so that we will fetch the end of the interval from the Temporal
    search attribute `TemporalScheduledStartTime`.

    This Workflow executes the same insert activity as the PostgresBatchExportWorkflow,
    as Postgres and AWS Redshift are fairly compatible. The only differences are:
    * Postgres JSONB fields are VARCHAR in Redshift.
    * Non retryable errors can be different between both.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> RedshiftBatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return RedshiftBatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: RedshiftBatchExportInputs):
        logger = get_batch_exports_logger(inputs=inputs)
        data_interval_start, data_interval_end = get_data_interval(inputs.interval, inputs.data_interval_end)
        logger.info("Starting Redshift export batch %s - %s", data_interval_start, data_interval_end)

        create_export_run_inputs = CreateBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )
        run_id = await workflow.execute_activity(
            create_export_run,
            create_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        update_inputs = UpdateBatchExportRunStatusInputs(id=run_id, status="Completed")

        insert_inputs = RedshiftInsertInputs(
            team_id=inputs.team_id,
            user=inputs.user,
            password=inputs.password,
            host=inputs.host,
            port=inputs.port,
            database=inputs.database,
            schema=inputs.schema,
            table_name=inputs.table_name,
            has_self_signed_cert=inputs.has_self_signed_cert,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
        )

        await execute_batch_export_insert_activity(
            insert_into_postgres_activity, insert_inputs, non_retryable_error_types=[], update_inputs=update_inputs
        )
