import logging
import logging.config

from opentelemetry import (
    context as otel_context,
    trace,
)
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from posthog.settings import logs


def _record(level: int) -> logging.LogRecord:
    return logging.LogRecord("test", level, __file__, 1, "message", args=(), exc_info=None)


def test_level_filters_split_info_from_warnings() -> None:
    max_info = logs.MaxLevelFilter(logging.INFO)

    assert max_info.filter(_record(logging.INFO))
    assert not max_info.filter(_record(logging.WARNING))


def test_add_otel_trace_context_binds_ids_from_active_span() -> None:
    span_context = SpanContext(
        trace_id=0x4BF92F3577B34DA6A3CE929D0E0E4736,
        span_id=0x00F067AA0BA902B7,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    token = otel_context.attach(trace.set_span_in_context(NonRecordingSpan(span_context)))
    try:
        event_dict = logs.add_otel_trace_context(logging.getLogger("test"), "info", {"event": "x"})
    finally:
        otel_context.detach(token)
    assert event_dict["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert event_dict["span_id"] == "00f067aa0ba902b7"


def test_add_otel_trace_context_is_noop_without_active_span() -> None:
    event_dict = logs.add_otel_trace_context(logging.getLogger("test"), "info", {"event": "x"})
    assert "trace_id" not in event_dict
    assert "span_id" not in event_dict


def test_logging_config_can_be_applied() -> None:
    config = dict(logs.LOGGING)
    config["disable_existing_loggers"] = False
    logging.config.dictConfig(config)


def test_default_console_logging_handler_keeps_default_stream() -> None:
    assert "stream" not in logs.LOGGING["handlers"]["console"]


def test_hypercache_info_logs_route_to_stdout_with_warnings_on_stderr() -> None:
    assert logs.LOGGING["handlers"]["console_stdout_info"]["stream"] == "ext://sys.stdout"
    assert "stream" not in logs.LOGGING["handlers"]["console_stderr_warning"]
    assert logs.LOGGING["loggers"]["posthog.storage.hypercache_verifier"]["handlers"] == [
        "console_stdout_info",
        "console_stderr_warning",
    ]
    assert logs.LOGGING["loggers"]["posthog.tasks.hypercache_verification"]["handlers"] == [
        "console_stdout_info",
        "console_stderr_warning",
    ]
