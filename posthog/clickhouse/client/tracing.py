import logging
from contextlib import contextmanager
from time import perf_counter
from typing import Any, Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from posthog.clickhouse.client.connection import Workload, ClickHouseUser
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HOST

logger = logging.getLogger(__name__)


@contextmanager
def trace_clickhouse_query(
    query: str,
    args: Optional[Any] = None,
    workload: Workload = Workload.DEFAULT,
    team_id: Optional[int] = None,
    readonly: bool = False,
    ch_user: ClickHouseUser = ClickHouseUser.DEFAULT,
    query_type: str = "Other",
    query_id: Optional[str] = None,
):
    """
    Context manager for tracing ClickHouse queries with OpenTelemetry.
    """
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("clickhouse.query") as span:
        if span.is_recording():
            # Set standard database attributes
            span.set_attribute("db.system", "clickhouse")
            span.set_attribute("db.name", CLICKHOUSE_DATABASE)
            span.set_attribute("db.user", ch_user.value)
            span.set_attribute("db.statement", query)

            # Set network attributes
            span.set_attribute("net.peer.name", CLICKHOUSE_HOST)
            span.set_attribute("net.peer.port", 9000)  # Default ClickHouse port

            # Set span kind
            span.set_attribute("span.kind", "client")

            # Add custom attributes for PostHog-specific context
            span.set_attribute("clickhouse.workload", workload.value)
            span.set_attribute("clickhouse.team_id", str(team_id or ""))
            span.set_attribute("clickhouse.readonly", readonly)
            span.set_attribute("clickhouse.query_type", query_type)
            if query_id:
                span.set_attribute("clickhouse.query_id", query_id)

            # Add args info if present
            if args:
                if isinstance(args, dict):
                    span.set_attribute("clickhouse.args_count", len(args))
                    span.set_attribute("clickhouse.args_keys", list(args.keys()))
                elif isinstance(args, list | tuple):
                    span.set_attribute("clickhouse.args_count", len(args))

        start_time = perf_counter()
        try:
            yield span
            execution_time = perf_counter() - start_time

            if span.is_recording():
                span.set_attribute("clickhouse.execution_time_ms", execution_time * 1000)
                span.set_attribute("clickhouse.success", True)
                span.set_status(Status(StatusCode.OK))

        except Exception as e:
            execution_time = perf_counter() - start_time

            if span.is_recording():
                span.set_attribute("clickhouse.execution_time_ms", execution_time * 1000)
                span.set_attribute("clickhouse.success", False)
                span.set_attribute("clickhouse.error_type", type(e).__name__)
                span.set_attribute("clickhouse.error_message", str(e))
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)

            raise


def add_clickhouse_span_attributes(span, **attributes):
    """
    Helper function to add custom attributes to the current ClickHouse span.
    """
    if span.is_recording():
        for key, value in attributes.items():
            span.set_attribute(f"clickhouse.{key}", value)
