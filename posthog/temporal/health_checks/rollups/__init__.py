from posthog.temporal.health_checks.rollups.activities import (
    apply_daily_rollup_retention,
    plan_daily_rollup_run,
    run_daily_rollup_step,
)
from posthog.temporal.health_checks.rollups.workflows import DailyRollupWorkflow

WORKFLOWS = [DailyRollupWorkflow]
ACTIVITIES = [plan_daily_rollup_run, run_daily_rollup_step, apply_daily_rollup_retention]
