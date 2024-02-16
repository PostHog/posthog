from posthog.temporal.batch_exports.backfill_batch_export import (
    BackfillBatchExportWorkflow,
    backfill_schedule,
    get_schedule_frequency,
)
from posthog.temporal.batch_exports.batch_exports import (
    create_batch_export_backfill_model,
    create_export_run,
    update_batch_export_backfill_model_status,
    update_export_run_status,
)
from posthog.temporal.batch_exports.bigquery_batch_export import (
    BigQueryBatchExportWorkflow,
    insert_into_bigquery_activity,
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
from posthog.temporal.batch_exports.http_batch_export import (
    HttpBatchExportWorkflow,
    insert_into_http_activity,
)
from posthog.temporal.batch_exports.squash_person_overrides import *

WORKFLOWS = [
    BackfillBatchExportWorkflow,
    BigQueryBatchExportWorkflow,
    NoOpWorkflow,
    PostgresBatchExportWorkflow,
    RedshiftBatchExportWorkflow,
    S3BatchExportWorkflow,
    SnowflakeBatchExportWorkflow,
    HttpBatchExportWorkflow,
    SquashPersonOverridesWorkflow,
]

ACTIVITIES = [
    attach_person_overrides_kafka_table,
    backfill_schedule,
    create_batch_export_backfill_model,
    create_export_run,
    deattach_person_overrides_kafka_table,
    delete_squashed_person_overrides_from_clickhouse,
    drop_dictionary,
    get_schedule_frequency,
    insert_into_bigquery_activity,
    insert_into_postgres_activity,
    insert_into_redshift_activity,
    insert_into_s3_activity,
    insert_into_snowflake_activity,
    insert_into_http_activity,
    noop_activity,
    optimize_person_distinct_id_overrides,
    prepare_dictionary,
    squash_events_partition,
    update_batch_export_backfill_model_status,
    update_export_run_status,
]
