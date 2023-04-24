from posthog.temporal.workflows.base import *
from posthog.temporal.workflows.noop import *
from posthog.temporal.workflows.s3_export import *

WORKFLOWS = [NoOpWorkflow, S3ExportWorkflow]
ACTIVITIES = [create_export_run, noop_activity, insert_into_s3_activity, update_export_run_status]

DESTINATION_WORKFLOWS = {
    "S3": (S3ExportWorkflow, S3ExportInputs),
}
