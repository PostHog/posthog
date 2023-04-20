from posthog.temporal.workflows.noop import *
from posthog.temporal.workflows.s3_export import *

WORKFLOWS = [NoOpWorkflow, S3ExportWorkflow]
ACTIVITIES = [noop_activity, insert_into_s3_activity]

DESTINATION_WORKFLOWS = {
    "S3": (S3ExportWorkflow, S3ExportInputs),
}
