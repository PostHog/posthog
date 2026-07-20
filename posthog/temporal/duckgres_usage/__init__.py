from posthog.temporal.duckgres_usage.activities import (
    ack_duckgres_usage,
    poll_duckgres_usage,
    set_duckgres_default_team,
)
from posthog.temporal.duckgres_usage.workflow import PollDuckgresUsageWorkflow, UpdateDuckgresDefaultTeamWorkflow

WORKFLOWS = [PollDuckgresUsageWorkflow, UpdateDuckgresDefaultTeamWorkflow]
ACTIVITIES = [poll_duckgres_usage, ack_duckgres_usage, set_duckgres_default_team]
