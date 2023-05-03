from typing import Callable, Sequence

from posthog.temporal.workflows.base import *
from posthog.temporal.workflows.noop import *
from posthog.temporal.workflows.s3_batch_export import *
from posthog.temporal.workflows.squash_person_overrides import *

DESTINATION_WORKFLOWS = {
    "S3": (S3BatchExportWorkflow, S3BatchExportInputs),
}

WORKFLOWS = [NoOpWorkflow, SquashPersonOverridesWorkflow, S3BatchExportWorkflow]

ACTIVITIES: Sequence[Callable] = [
    create_export_run,
    delete_squashed_person_overrides_from_clickhouse,
    delete_squashed_person_overrides_from_postgres,
    drop_dictionary,
    insert_into_s3_activity,
    noop_activity,
    prepare_dictionary,
    prepare_person_overrides,
    re_attach_person_overrides,
    select_persons_to_delete,
    squash_events_partition,
    update_export_run_status,
]
