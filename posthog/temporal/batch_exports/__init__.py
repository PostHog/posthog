from posthog.temporal.batch_exports.backfill_batch_export import (
    BackfillBatchExportWorkflow,
    backfill_schedule,
    get_schedule_frequency,
)
from posthog.temporal.batch_exports.batch_exports import (
    create_batch_export_backfill_model,
    finish_batch_export_run,
    start_batch_export_run,
    update_batch_export_backfill_model_status,
)
from posthog.temporal.batch_exports.bigquery_batch_export import (
    BigQueryBatchExportWorkflow,
    insert_into_bigquery_activity,
)
from posthog.temporal.batch_exports.http_batch_export import (
    HttpBatchExportWorkflow,
    insert_into_http_activity,
)
from posthog.temporal.batch_exports.noop import NoOpWorkflow, noop_activity
from posthog.temporal.batch_exports.postgres_batch_export import (
    PostgresBatchExportWorkflow,
    insert_into_postgres_activity,
)
from posthog.temporal.batch_exports.redshift_batch_export import (
    RedshiftBatchExportWorkflow,
    insert_into_redshift_activity,
)
from posthog.temporal.batch_exports.s3_batch_export import (
    S3BatchExportWorkflow,
    insert_into_s3_activity,
)
from posthog.temporal.batch_exports.snowflake_batch_export import (
    SnowflakeBatchExportWorkflow,
    insert_into_snowflake_activity,
)
from posthog.temporal.batch_exports.squash_person_overrides import (
    SquashPersonOverridesWorkflow,
    create_table,
    drop_table,
    optimize_person_distinct_id_overrides,
    submit_mutation,
    wait_for_mutation,
    wait_for_table,
)

SYNC_WORKFLOWS = [
    NoOpWorkflow,
    PostgresBatchExportWorkflow,
    S3BatchExportWorkflow,
    SnowflakeBatchExportWorkflow,
    HttpBatchExportWorkflow,
]

WORKFLOWS = [
    NoOpWorkflow,
    BackfillBatchExportWorkflow,
    BigQueryBatchExportWorkflow,
    RedshiftBatchExportWorkflow,
    SquashPersonOverridesWorkflow,
]

ACTIVITIES = [
    backfill_schedule,
    create_batch_export_backfill_model,
    start_batch_export_run,
    create_table,
    drop_table,
    finish_batch_export_run,
    get_schedule_frequency,
    insert_into_bigquery_activity,
    insert_into_redshift_activity,
    noop_activity,
    optimize_person_distinct_id_overrides,
    submit_mutation,
    update_batch_export_backfill_model_status,
    wait_for_mutation,
    wait_for_table,
]

SYNC_ACTIVITIES = [
    backfill_schedule,
    create_batch_export_backfill_model,
    start_batch_export_run,
    create_table,
    drop_table,
    finish_batch_export_run,
    get_schedule_frequency,
    insert_into_http_activity,
    insert_into_postgres_activity,
    insert_into_s3_activity,
    insert_into_snowflake_activity,
    noop_activity,
    optimize_person_distinct_id_overrides,
    submit_mutation,
    update_batch_export_backfill_model_status,
    wait_for_mutation,
    wait_for_table,
]
