import json
import asyncio
from datetime import UTC, datetime, timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.weekly_digest.activities import (
    generate_dashboard_lookup,
    generate_event_definition_lookup,
    generate_experiment_lookup,
    generate_external_data_source_lookup,
    generate_feature_flag_lookup,
    generate_survey_lookup,
    generate_user_notification_lookup,
)
from posthog.temporal.weekly_digest.types import GenerateDigestDataInput, WeeklyDigestInput


@workflow.defn(name="weekly-digest")
class WeeklyDigestWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> WeeklyDigestInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return WeeklyDigestInput(**loaded)

    @workflow.run
    async def run(self, input: WeeklyDigestInput) -> None:
        year, week, _ = datetime.now().isocalendar()
        digest_key: str = f"weekly-digest-{year}-{week}"

        period_end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = period_end - timedelta(days=7)

        await workflow.execute_child_workflow(
            GenerateDigestDataWorkflow.run,
            GenerateDigestDataInput(
                digest_key=digest_key,
                period_start=period_start,
                period_end=period_end + timedelta(days=2),
                redis_ttl=input.redis_ttl,
                redis_host=input.redis_host,
                redis_port=input.redis_port,
            ),
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            execution_timeout=timedelta(hours=3),
            run_timeout=timedelta(hours=1),
            task_timeout=timedelta(minutes=30),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
        )


@workflow.defn(name="generate-digest-data")
class GenerateDigestDataWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> GenerateDigestDataInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return GenerateDigestDataInput(**loaded)

    @workflow.run
    async def run(self, input: GenerateDigestDataInput) -> None:
        generators = [
            generate_dashboard_lookup,
            generate_event_definition_lookup,
            generate_experiment_lookup,
            generate_external_data_source_lookup,
            generate_survey_lookup,
            generate_feature_flag_lookup,
            generate_user_notification_lookup,
        ]

        await asyncio.gather(
            *[
                workflow.execute_activity(
                    generator,
                    input,
                    start_to_close_timeout=timedelta(minutes=120),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                    heartbeat_timeout=timedelta(minutes=5),
                )
                for generator in generators
            ]
        )
