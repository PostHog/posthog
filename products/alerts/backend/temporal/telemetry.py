import time
import asyncio

from django.conf import settings

from opentelemetry import trace
from temporalio.exceptions import CancelledError
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from posthog.temporal.common.logger import get_write_only_logger

LOGGER = get_write_only_logger(__name__)


def _monotonic_time() -> float | None:
    try:
        return time.monotonic()
    except Exception:
        return None


async def _log_activity_event(
    event: str,
    *,
    started_at: float | None = None,
    outcome: str | None = None,
    exception_type: str | None = None,
) -> None:
    try:
        fields: dict[str, str | float] = {}
        if outcome is not None:
            fields["outcome"] = outcome
        if started_at is not None:
            fields["duration_ms"] = (time.monotonic() - started_at) * 1000
        if exception_type is not None:
            fields["exception_type"] = exception_type
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            fields["trace_id"] = trace.format_trace_id(span_context.trace_id)
            fields["span_id"] = trace.format_span_id(span_context.span_id)
        log = LOGGER.awarning if outcome == "failure" else LOGGER.ainfo
        await log(event, **fields)
    except Exception:
        pass


class AlertsProductTelemetryInterceptor(Interceptor):
    task_queue = (settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE, settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE)

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _AlertsProductActivityInterceptor(next)


class _AlertsProductActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> object:
        started_at = _monotonic_time()
        outcome = "success"
        exception_type = None
        try:
            await _log_activity_event("alerts_product_activity_started")
            return await super().execute_activity(input)
        except (asyncio.CancelledError, CancelledError):
            outcome = "cancellation"
            raise
        except BaseException as error:
            outcome = "failure"
            exception_type = type(error).__name__
            raise
        finally:
            try:
                await _log_activity_event(
                    "alerts_product_activity_finished",
                    started_at=started_at,
                    outcome=outcome,
                    exception_type=exception_type,
                )
            except asyncio.CancelledError:
                pass
