from typing import Callable, Sequence

from posthog.temporal.workflows.backfill_batch_export import (
    BackfillBatchExportWorkflow,
    backfill_schedule,
    get_schedule_frequency,
)
from posthog.temporal.workflows.batch_exports import (
    create_batch_export_backfill_model,
    create_export_run,
    update_batch_export_backfill_model_status,
    update_export_run_status,
)
from posthog.temporal.workflows.bigquery_batch_export import (
    BigQueryBatchExportWorkflow,
    insert_into_bigquery_activity,
)
from posthog.temporal.workflows.noop import NoOpWorkflow, noop_activity
from posthog.temporal.workflows.postgres_batch_export import (
    PostgresBatchExportWorkflow,
    insert_into_postgres_activity,
)
from posthog.temporal.workflows.redshift_batch_export import (
    RedshiftBatchExportWorkflow,
    insert_into_redshift_activity,
)
from posthog.temporal.workflows.s3_batch_export import (
    S3BatchExportWorkflow,
    insert_into_s3_activity,
)
from posthog.temporal.workflows.snowflake_batch_export import (
    SnowflakeBatchExportWorkflow,
    insert_into_snowflake_activity,
)
from posthog.temporal.workflows.squash_person_overrides import *

WORKFLOWS = [
    BackfillBatchExportWorkflow,
    BigQueryBatchExportWorkflow,
    NoOpWorkflow,
    PostgresBatchExportWorkflow,
    RedshiftBatchExportWorkflow,
    S3BatchExportWorkflow,
    SnowflakeBatchExportWorkflow,
    SquashPersonOverridesWorkflow,
]

ACTIVITIES: Sequence[Callable] = [
    backfill_schedule,
    create_batch_export_backfill_model,
    create_export_run,
    delete_squashed_person_overrides_from_clickhouse,
    delete_squashed_person_overrides_from_postgres,
    drop_dictionary,
    get_schedule_frequency,
    insert_into_bigquery_activity,
    insert_into_postgres_activity,
    insert_into_redshift_activity,
    insert_into_s3_activity,
    insert_into_snowflake_activity,
    noop_activity,
    prepare_dictionary,
    prepare_person_overrides,
    select_persons_to_delete,
    squash_events_partition,
    update_batch_export_backfill_model_status,
    update_export_run_status,
]
