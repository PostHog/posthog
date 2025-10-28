import os
import json
import asyncio
import itertools
from datetime import UTC, datetime, timedelta

from django.conf import settings

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.weekly_digest.activities import (
    count_organizations,
    count_teams,
    generate_dashboard_lookup,
    generate_event_definition_lookup,
    generate_experiment_completed_lookup,
    generate_experiment_launched_lookup,
    generate_external_data_source_lookup,
    generate_feature_flag_lookup,
    generate_filter_lookup,
    generate_organization_digest_batch,
    generate_recording_lookup,
    generate_survey_lookup,
    generate_user_notification_lookup,
    send_weekly_digest_batch,
)
from posthog.temporal.weekly_digest.types import (
    Digest,
    GenerateDigestDataBatchInput,
    GenerateDigestDataInput,
    GenerateOrganizationDigestInput,
    SendWeeklyDigestBatchInput,
    SendWeeklyDigestInput,
    WeeklyDigestInput,
)


@workflow.defn(name="weekly-digest")
class WeeklyDigestWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> WeeklyDigestInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        parsed_input = WeeklyDigestInput(**loaded)

        if parsed_input.common.django_redis_url is None:
            parsed_input.common.django_redis_url = settings.REDIS_URL

        return parsed_input

    @workflow.run
    async def run(self, input: WeeklyDigestInput) -> None:
        if input.common.redis_host is None:
            input.common.redis_host = os.getenv("WEEKLY_DIGEST_REDIS_HOST", "localhost")

        if input.common.redis_port is None:
            input.common.redis_port = int(os.getenv("WEEKLY_DIGEST_REDIS_PORT", "6379"))

        year, week, _ = datetime.now().isocalendar()
        period_end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = period_end - timedelta(days=7)

        digest = Digest(
            key=f"weekly-digest-{year}-{week}",
            period_start=period_start,
            period_end=period_end,
        )

        await workflow.execute_child_workflow(
            GenerateDigestDataWorkflow.run,
            GenerateDigestDataInput(
                digest=digest,
                common=input.common,
            ),
            parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
            execution_timeout=timedelta(hours=15),
            run_timeout=timedelta(hours=6),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=10),
            ),
        )

        await workflow.execute_child_workflow(
            SendWeeklyDigestWorkflow.run,
            SendWeeklyDigestInput(
                dry_run=input.dry_run,
                digest=digest,
                common=input.common,
            ),
            parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
            execution_timeout=timedelta(hours=15),
            run_timeout=timedelta(hours=6),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=10),
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
        batch_size = input.common.batch_size

        team_count = await workflow.execute_activity(
            count_teams,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=1),
        )

        team_batches = [(i, i + batch_size) for i in range(0, team_count, batch_size)]

        generators = [
            generate_dashboard_lookup,
            generate_event_definition_lookup,
            generate_experiment_completed_lookup,
            generate_experiment_launched_lookup,
            generate_external_data_source_lookup,
            generate_survey_lookup,
            generate_feature_flag_lookup,
            generate_user_notification_lookup,
            generate_filter_lookup,
            generate_recording_lookup,
        ]

        await asyncio.gather(
            *[
                workflow.execute_activity(
                    generator,
                    GenerateDigestDataBatchInput(
                        batch=batch,
                        digest=input.digest,
                        common=input.common,
                    ),
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                    heartbeat_timeout=timedelta(minutes=2),
                )
                for batch, generator in itertools.product(team_batches, generators)
            ]
        )

        organization_count = await workflow.execute_activity(
            count_organizations,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=1),
        )

        org_batches = [(i, i + batch_size) for i in range(0, organization_count, batch_size)]

        await asyncio.gather(
            *[
                workflow.execute_activity(
                    generate_organization_digest_batch,
                    GenerateOrganizationDigestInput(
                        batch=batch,
                        digest=input.digest,
                        common=input.common,
                    ),
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                    heartbeat_timeout=timedelta(minutes=2),
                )
                for batch in org_batches
            ]
        )


@workflow.defn(name="send-weekly-digest")
class SendWeeklyDigestWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> SendWeeklyDigestInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return SendWeeklyDigestInput(**loaded)

    @workflow.run
    async def run(self, input: SendWeeklyDigestInput) -> None:
        organization_count = await workflow.execute_activity(
            count_organizations,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=1),
        )

        batch_size = input.common.batch_size
        batches = [(i, i + batch_size) for i in range(0, organization_count, batch_size)]

        await asyncio.gather(
            *[
                workflow.execute_activity(
                    send_weekly_digest_batch,
                    SendWeeklyDigestBatchInput(
                        batch=batch, dry_run=input.dry_run, digest=input.digest, common=input.common
                    ),
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                    heartbeat_timeout=timedelta(minutes=2),
                )
                for batch in batches
            ]
        )
