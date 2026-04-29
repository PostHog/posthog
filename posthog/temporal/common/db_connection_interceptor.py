from typing import Any

from django.db import close_old_connections

from asgiref.sync import sync_to_async
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from posthog.temporal.common.interceptor import ALL_TASK_QUEUES


class _DbConnectionActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        await sync_to_async(close_old_connections)()

        try:
            result = await super().execute_activity(input)
        finally:
            await sync_to_async(close_old_connections)()
        return result


class DbConnectionInterceptor(Interceptor):
    """Interceptor that evicts stale Django DB connections around each activity.

    Long-running Temporal workers don't go through Django's request cycle, so the
    `request_started` / `request_finished` signals that normally call
    `close_old_connections()` never fire. Without this, connections that have
    exceeded `CONN_MAX_AGE` or been killed by the database stay in the pool until
    the next query fails. This interceptor mirrors the request-cycle behaviour by
    calling `close_old_connections()` at the start and end of every activity.
    """

    task_queue = ALL_TASK_QUEUES

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _DbConnectionActivityInboundInterceptor(super().intercept_activity(next))
