from posthog.temporal.duckgres_usage.activities import poll_duckgres_usage
from posthog.temporal.duckgres_usage.workflow import PollDuckgresUsageWorkflow

WORKFLOWS = [PollDuckgresUsageWorkflow]
ACTIVITIES = [poll_duckgres_usage]
