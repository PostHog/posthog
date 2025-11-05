from posthog.temporal.ingestion_limits.activities import (
    query_ingestion_limits_activity,
    report_ingestion_limits_activity,
)
from posthog.temporal.ingestion_limits.workflows import IngestionLimitsWorkflow

WORKFLOWS = [IngestionLimitsWorkflow]

ACTIVITIES = [
    query_ingestion_limits_activity,
    report_ingestion_limits_activity,
]
