from typing import Callable, Sequence

from posthog.temporal.workflows.base import *
from posthog.temporal.workflows.noop import *
from posthog.temporal.workflows.s3_batch_export import (
    S3BatchExportActivities,
    S3BatchExportWorkflow,
)
from posthog.temporal.workflows.snowflake_batch_export import (
    SnowflakeBatchExportActivities,
    SnowflakeBatchExportWorkflow,
)
from posthog.temporal.workflows.squash_person_overrides import *

WORKFLOWS = [NoOpWorkflow, SquashPersonOverridesWorkflow, S3BatchExportWorkflow, SnowflakeBatchExportWorkflow]

ACTIVITIES: Sequence[Callable] = [
    create_export_run,
    delete_squashed_person_overrides_from_clickhouse,
    delete_squashed_person_overrides_from_postgres,
    drop_dictionary,
    S3BatchExportActivities().insert_into_s3_activity,
    SnowflakeBatchExportActivities().insert_into_snowflake_activity,
    noop_activity,
    prepare_dictionary,
    prepare_person_overrides,
    select_persons_to_delete,
    squash_events_partition,
    update_export_run_status,
]
