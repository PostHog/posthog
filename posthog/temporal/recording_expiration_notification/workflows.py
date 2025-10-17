import json
import asyncio
from collections.abc import Awaitable, Iterable
from datetime import timedelta
from itertools import batched, chain

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.recording_expiration_notification.activities import (
    generate_notifications,
    query_organizations,
    query_recordings,
    send_notifications,
)
from posthog.temporal.recording_expiration_notification.types import (
    Notification,
    Organization,
    SendExpirationNotificationsInput,
)


@workflow.defn(name="send-expiration-notifications")
class SendExpirationNotificationsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(input: list[str]) -> SendExpirationNotificationsInput:
        """Parse input from the management command CLI."""
        loaded = json.loads(input[0])
        return SendExpirationNotificationsInput(**loaded)

    @workflow.run
    async def run(self, input: SendExpirationNotificationsInput) -> None:
        organizations: list[Organization] = await workflow.execute_activity(
            query_organizations,
            start_to_close_timeout=timedelta(minutes=120),
            retry_policy=common.RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(minutes=1),
            ),
            heartbeat_timeout=timedelta(minutes=5),
        )

        def _query_batch(batch: list[Organization]) -> Awaitable[list[Organization]]:
            return workflow.execute_activity(
                query_recordings,
                batch,
                start_to_close_timeout=timedelta(minutes=120),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(minutes=1),
                ),
                heartbeat_timeout=timedelta(minutes=5),
            )

        batches: Iterable[list[Organization]] = await asyncio.gather(
            *map(_query_batch, batched(organizations, input.batch_size))
        )

        def _generate_notifications(organization: Organization) -> Awaitable[list[Notification]]:
            return workflow.execute_activity(
                generate_notifications,
                organization,
                start_to_close_timeout=timedelta(minutes=120),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(minutes=1),
                ),
                heartbeat_timeout=timedelta(minutes=5),
            )

        for batch in batches:
            notifications: list[Notification] = list(
                chain.from_iterable(await asyncio.gather(*map(_generate_notifications, batch)))
            )
            await workflow.execute_activity(
                send_notifications,
                notifications,
                start_to_close_timeout=timedelta(minutes=120),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(minutes=1),
                ),
                heartbeat_timeout=timedelta(minutes=5),
            )
