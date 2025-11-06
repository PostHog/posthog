import asyncio
from datetime import timedelta

import structlog
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.synthetic_monitoring.activities import (
        execute_http_check_via_lambda,
        get_monitors_due_for_check,
    )

logger = structlog.get_logger(__name__)


@workflow.defn
class SyntheticMonitorSchedulerWorkflow:
    """Scheduler workflow that polls for monitors due for checks and executes them."""

    @workflow.run
    async def run(self) -> None:
        """
        Query database for monitors due for check and execute checks in parallel.
        This workflow runs every 60 seconds via Temporal schedule.
        """
        workflow.logger.info("🔄 Synthetic monitoring scheduler started")

        monitors_to_check = await workflow.execute_activity(
            get_monitors_due_for_check,
            start_to_close_timeout=timedelta(seconds=10),
            schedule_to_close_timeout=timedelta(seconds=30),
        )

        if not monitors_to_check:
            workflow.logger.info("✓ No monitors due for check - scheduler complete")
            return

        workflow.logger.info(f"📊 Found {len(monitors_to_check)} monitor checks to execute")

        tasks = []
        for monitor_id, region in monitors_to_check:
            workflow.logger.info(f"  → Queuing check for monitor {monitor_id} in {region}")
            task = workflow.execute_activity(
                execute_http_check_via_lambda,
                args=[monitor_id, region],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
            )
            tasks.append(task)

        workflow.logger.info(f"⏳ Executing {len(tasks)} checks in parallel...")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log results
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        error_count = len(results) - success_count

        workflow.logger.info(
            f"✓ Completed {len(tasks)} monitor checks (✓ {success_count} success, ✗ {error_count} errors)"
        )
