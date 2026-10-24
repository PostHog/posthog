import re
import logging
from functools import wraps
from time import perf_counter
from typing import Any, cast

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HOST

logger = logging.getLogger(__name__)


def _infer_team_id(query: object, args_param: object) -> object:
    if not isinstance(query, str):
        return None
    if isinstance(args_param, dict) and "team_id" in args_param:
        return args_param["team_id"]
    # Fallback: try to extract team_id from literal in query string
    match = re.search(r"team_id\s*=\s*(\d+)", query)
    return match.group(1) if match else None


def _set_args_attributes(span: Span, args_param: object) -> None:
    if not args_param:
        return
    if isinstance(args_param, dict):
        span.set_attribute("clickhouse.args_count", len(args_param))
        span.set_attribute("clickhouse.args_keys", cast(list[str], list(args_param.keys())))
    elif isinstance(args_param, list | tuple):
        span.set_attribute("clickhouse.args_count", len(args_param))


def _set_query_attributes(
    span: Span, query: object, args_param: object, team_id: object, kwargs: dict[str, Any]
) -> None:
    initial_workload = kwargs.get("workload", Workload.DEFAULT)
    readonly = kwargs.get("readonly", False)
    ch_user = kwargs.get("ch_user", ClickHouseUser.DEFAULT)

    span.set_attribute("db.system", "clickhouse")
    span.set_attribute("db.name", CLICKHOUSE_DATABASE)
    span.set_attribute("db.user", ch_user.value)
    span.set_attribute("db.statement", query if isinstance(query, str) else repr(query))
    span.set_attribute("net.peer.name", CLICKHOUSE_HOST)
    span.set_attribute("net.peer.port", 9000)  # Default ClickHouse port
    span.set_attribute("span.kind", "client")
    span.set_attribute("clickhouse.initial_workload", initial_workload.value)
    span.set_attribute("clickhouse.team_id", str(team_id or ""))
    span.set_attribute("clickhouse.readonly", readonly)
    span.set_attribute("clickhouse.query_type", "Other")  # Will be updated by function
    _set_args_attributes(span, args_param)


def _record_success(span: Span, result: object, execution_time: float) -> None:
    span.set_attribute("clickhouse.execution_time_ms", execution_time * 1000)
    span.set_attribute("clickhouse.success", True)
    span.set_status(Status(StatusCode.OK))

    if isinstance(result, list | tuple):
        span.set_attribute("clickhouse.result_rows", len(result))
    elif isinstance(result, int):
        span.set_attribute("clickhouse.written_rows", result)


def _record_failure(span: Span, error: Exception, execution_time: float) -> None:
    span.set_attribute("clickhouse.execution_time_ms", execution_time * 1000)
    span.set_attribute("clickhouse.success", False)
    span.set_attribute("clickhouse.error_type", type(error).__name__)
    span.set_attribute("clickhouse.error_message", str(error))
    span.set_status(Status(StatusCode.ERROR, str(error)))
    span.record_exception(error)


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
        # sync_execute has: query, args=None, settings=None, with_column_types=False, flush=True, *, workload, team_id, readonly, sync_client, ch_user
        query = args[0] if args else kwargs.get("query")
        args_param = args[1] if len(args) > 1 else kwargs.get("args")
        team_id = kwargs.get("team_id")

        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("clickhouse.query") as span:
            # Ensure team_id is extracted before any attributes are set
            if span.is_recording() and team_id is None:
                team_id = _infer_team_id(query, args_param)

            _set_query_attributes(span, query, args_param, team_id, kwargs)

            start_time = perf_counter()
            try:
                result = func(*args, **kwargs)
                _record_success(span, result, perf_counter() - start_time)
                return result
            except Exception as e:
                _record_failure(span, e, perf_counter() - start_time)
                raise

    return wrapper
