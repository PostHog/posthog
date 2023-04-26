from posthog.temporal.workflows.base import *
from posthog.temporal.workflows.noop import *
from posthog.temporal.workflows.s3_batch_export import *

WORKFLOWS = [NoOpWorkflow, S3BatchExportWorkflow]
ACTIVITIES = [create_export_run, noop_activity, insert_into_s3_activity, update_export_run_status]

DESTINATION_WORKFLOWS = {
    "S3": (S3BatchExportWorkflow, S3BatchExportInputs),
}
