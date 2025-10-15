import time
import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

import structlog
from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec
from temporalio.common import WorkflowIDReusePolicy

from posthog.constants import MESSAGING_TASK_QUEUE
from posthog.temporal.common.client import async_connect
from posthog.temporal.messaging.behavioral_cohorts_workflow_coordinator import CoordinatorWorkflowInputs

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Run or schedule behavioral cohorts workflow to generate cohort membership data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-matches",
            type=int,
            default=3,
            help="Minimum number of matches required (default: 3)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Number of days to look back (default: 30)",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            help="Optional: Filter to a specific team ID",
        )
        parser.add_argument(
            "--cohort-id",
            type=int,
            help="Optional: Filter to a specific cohort/action ID",
        )
        parser.add_argument(
            "--condition",
            type=str,
            help="Optional: Filter to a specific condition hash",
        )
        parser.add_argument(
            "--parallelism",
            type=int,
            default=10,
            help="Number of parallel child workflows to spawn (default: 10)",
        )
        parser.add_argument(
            "--schedule",
            action="store_true",
            default=False,
            help="Schedule the workflow to run periodically instead of running once",
        )
        parser.add_argument(
            "--duration",
            type=int,
            default=60,
            help="Duration in minutes to run the schedule (only with --schedule, default: 60)",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=5,
            help="Interval in minutes between runs (only with --schedule, default: 5)",
        )

    def handle(self, *args, **options):
        min_matches = options["min_matches"]
        days = options["days"]
        team_id = options.get("team_id")
        cohort_id = options.get("cohort_id")
        condition = options.get("condition")
        parallelism = options.get("parallelism", 10)
        schedule = options.get("schedule", False)
        duration_minutes = options.get("duration", 60)
        interval_minutes = options.get("interval", 5)

        if schedule:
            # Schedule the workflow to run periodically
            logger.info(
                "Creating Temporal schedule for behavioral cohorts",
                duration_minutes=duration_minutes,
                interval_minutes=interval_minutes,
                parallelism=parallelism,
            )

            try:
                asyncio.run(
                    self.create_schedule(
                        duration_minutes=duration_minutes,
                        interval_minutes=interval_minutes,
                        parallelism=parallelism,
                        min_matches=min_matches,
                        days=days,
                        team_id=team_id,
                        cohort_id=cohort_id,
                        condition=condition,
                    )
                )
            except Exception as e:
                logger.exception(f"Failed to create schedule: {e}")
                raise
        else:
            # Run the workflow once
            logger.info(
                "Starting cohort membership generation",
                parallelism=parallelism,
            )

            self.run_temporal_workflow(
                team_id=team_id,
                cohort_id=cohort_id,
                condition=condition,
                min_matches=min_matches,
                days=days,
                parallelism=parallelism,
            )

            logger.info(
                "Coordinator workflow scheduled child workflows",
                parallelism=parallelism,
            )

            self.stdout.write(f"Coordinator workflow scheduled {parallelism} child workflows")
            self.stdout.write(
                "Child workflows are running in the background. Check Temporal UI for progress and results."
            )

    def run_temporal_workflow(
        self,
        team_id: int | None,
        cohort_id: int | None,
        condition: str | None,
        min_matches: int,
        days: int,
        parallelism: int,
    ) -> None:
        """Run the Temporal workflow for parallel processing."""

        async def _run_workflow():
            # Connect to Temporal
            client = await async_connect()

            # Always use coordinator workflow for true parallelism and to avoid GRPC limits
            inputs = CoordinatorWorkflowInputs(
                team_id=team_id,
                cohort_id=cohort_id,
                condition=condition,
                min_matches=min_matches,
                days=days,
                parallelism=parallelism,
            )

            # Generate unique workflow ID
            workflow_id = f"behavioral-cohorts-coordinator-{team_id or 'all'}-{cohort_id or 'all'}-{int(time.time())}"

            logger.info(f"Starting Temporal coordinator workflow: {workflow_id}")

            try:
                # Execute the coordinator workflow (no result expected)
                await client.execute_workflow(
                    "behavioral-cohorts-coordinator",
                    inputs,
                    id=workflow_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    task_queue=MESSAGING_TASK_QUEUE,
                )

                logger.info(f"Workflow {workflow_id} completed successfully")

            except Exception as e:
                logger.exception(f"Workflow execution failed: {e}")
                raise

        try:
            # Run the async function
            asyncio.run(_run_workflow())
        except Exception as e:
            logger.exception(f"Failed to execute Temporal workflow: {e}")

    async def create_schedule(
        self,
        duration_minutes: int,
        interval_minutes: int,
        parallelism: int,
        min_matches: int,
        days: int,
        team_id: int | None = None,
        cohort_id: int | None = None,
        condition: str | None = None,
    ):
        """Create a Temporal schedule to run the workflow at specified intervals."""

        # Connect to Temporal
        client = await async_connect()

        # Create workflow inputs
        inputs = CoordinatorWorkflowInputs(
            team_id=team_id,
            cohort_id=cohort_id,
            condition=condition,
            min_matches=min_matches,
            days=days,
            parallelism=parallelism,
        )

        # Create unique schedule ID
        schedule_id = f"behavioral-cohorts-{interval_minutes}min-{team_id or 'all'}-{int(time.time() * 1000)}"

        # Calculate end time based on duration
        start_time = datetime.utcnow()
        end_time = start_time + timedelta(minutes=duration_minutes)

        # Calculate number of expected runs
        expected_runs = int(duration_minutes / interval_minutes)

        logger.info(
            "Creating Temporal schedule",
            schedule_id=schedule_id,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            expected_runs=expected_runs,
        )

        # Create the schedule
        schedule_handle = await client.create_schedule(
            id=schedule_id,
            schedule=Schedule(
                spec=ScheduleSpec(
                    intervals=[
                        ScheduleIntervalSpec(
                            every=timedelta(minutes=interval_minutes),
                        )
                    ],
                    end_at=end_time,  # Automatically stops after specified duration
                ),
                action=ScheduleActionStartWorkflow(
                    "behavioral-cohorts-coordinator",
                    asdict(inputs),
                    id=f"behavioral-cohorts-scheduled-{int(time.time() * 1000000)}",
                    task_queue=MESSAGING_TASK_QUEUE,
                ),
            ),
        )

        # Get schedule info
        description = await schedule_handle.describe()
        next_run = description.info.next_action_times[0] if description.info.next_action_times else None

        self.stdout.write(self.style.SUCCESS(f"✅ Successfully created schedule: {schedule_id}"))
        self.stdout.write(f"⏰ Running every {interval_minutes} minutes for {duration_minutes} minute(s)")
        self.stdout.write(f"📅 Start: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        self.stdout.write(f"📅 End: {end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        self.stdout.write(f"🔄 Expected runs: {expected_runs}")
        self.stdout.write(f"📊 Parameters:")
        self.stdout.write(f"   - Parallelism: {parallelism}")
        self.stdout.write(f"   - Min matches: {min_matches}")
        self.stdout.write(f"   - Days lookback: {days}")
        if team_id:
            self.stdout.write(f"   - Team ID: {team_id}")
        if cohort_id:
            self.stdout.write(f"   - Cohort ID: {cohort_id}")
        if next_run:
            self.stdout.write(f"⏭️  Next run: {next_run}")
        self.stdout.write(f"\n🛑 To cancel: temporal schedule delete --schedule-id {schedule_id}")

        logger.info(
            "Schedule created successfully",
            schedule_id=schedule_id,
            state=description.schedule.state,
        )
