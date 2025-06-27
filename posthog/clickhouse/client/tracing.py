import logging
from functools import wraps
from time import perf_counter

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from posthog.clickhouse.client.connection import Workload, ClickHouseUser
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HOST

logger = logging.getLogger(__name__)


def trace_clickhouse_query_decorator(func):
    """
    Decorator to add ClickHouse query tracing to sync_execute function.
    This decorator handles the complex tracing requirements including:
    - Workload changes during retries
    - Result tracking
    - Exception handling
    - Execution time measurement
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Extract parameters for tracing - handle both positional and keyword args
        query = args[0] if args else kwargs.get("query")
        args_param = kwargs.get("args")
        initial_workload = kwargs.get("workload", Workload.DEFAULT)
        team_id = kwargs.get("team_id")
        readonly = kwargs.get("readonly", False)
        ch_user = kwargs.get("ch_user", ClickHouseUser.DEFAULT)

        # Handle positional arguments for sync_execute signature
        # sync_execute has: query, args=None, settings=None, with_column_types=False, flush=True, *, workload, team_id, readonly, sync_client, ch_user
        if len(args) > 1:
            args_param = args[1]

        # The keyword-only arguments (after *) must be passed as kwargs
        # So we only extract from kwargs for these parameters

        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("clickhouse.query") as span:
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
            # Note: This captures the initial workload value. The workload can change
            # during function execution based on various conditions.
            span.set_attribute("clickhouse.initial_workload", initial_workload.value)
            span.set_attribute("clickhouse.team_id", str(team_id or ""))
            span.set_attribute("clickhouse.readonly", readonly)
            span.set_attribute("clickhouse.query_type", "Other")  # Will be updated by function

            # Add args info if present
            if args_param:
                if isinstance(args_param, dict):
                    span.set_attribute("clickhouse.args_count", len(args_param))
                    span.set_attribute("clickhouse.args_keys", list(args_param.keys()))
                elif isinstance(args_param, list | tuple):
                    span.set_attribute("clickhouse.args_count", len(args_param))

            start_time = perf_counter()
            try:
                # Call the original function
                result = func(*args, **kwargs)
                execution_time = perf_counter() - start_time

                span.set_attribute("clickhouse.execution_time_ms", execution_time * 1000)
                span.set_attribute("clickhouse.success", True)
                span.set_status(Status(StatusCode.OK))

                # Add result info to span
                if isinstance(result, list | tuple):
                    span.set_attribute("clickhouse.result_rows", len(result))
                elif isinstance(result, int):
                    span.set_attribute("clickhouse.written_rows", result)

                return result

            except Exception as e:
                execution_time = perf_counter() - start_time

                span.set_attribute("clickhouse.execution_time_ms", execution_time * 1000)
                span.set_attribute("clickhouse.success", False)
                span.set_attribute("clickhouse.error_type", type(e).__name__)
                span.set_attribute("clickhouse.error_message", str(e))
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)

                raise

    return wrapper
