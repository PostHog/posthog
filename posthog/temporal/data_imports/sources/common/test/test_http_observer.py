import time

import pytest
from unittest.mock import patch

import structlog
from requests import PreparedRequest, Response
from structlog.testing import capture_logs

from posthog.temporal.data_imports.sources.common.http import context as ctx_mod
from posthog.temporal.data_imports.sources.common.http.context import scoped_job_context
from posthog.temporal.data_imports.sources.common.http.observer import RequestRecord, record_request


def _make_request(
    url: str = "https://api.example.com/v1/users", method: str = "GET", body: bytes | str | None = None
) -> PreparedRequest:
    req = PreparedRequest()
    req.prepare(method=method, url=url, data=body)
    return req


def _make_response(status_code: int = 200, body: bytes = b"", content_length: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = body
    if content_length is not None:
        resp.headers["Content-Length"] = content_length
    return resp


@pytest.fixture(autouse=True)
def _reset_contextvar():
    token = ctx_mod._current_job_context.set(None)
    structlog.contextvars.clear_contextvars()
    try:
        yield
    finally:
        ctx_mod._current_job_context.reset(token)
        structlog.contextvars.clear_contextvars()


@pytest.fixture
def captured_logs():
    """Use structlog's own capture_logs — caplog flattens the event_dict on the way through stdlib."""
    with capture_logs() as logs:
        yield logs


def _entries(logs: list[dict]) -> list[dict]:
    return [entry for entry in logs if entry.get("event", "").startswith("data_imports.http.request")]


@pytest.fixture
def job_ctx():
    with scoped_job_context(
        team_id=99,
        source_type="stripe",
        external_data_source_id="src",
        external_data_schema_id="sch",
        external_data_job_id="run",
    ) as ctx:
        yield ctx


# ---------------------------------------------------------------------------
# Logging behavior
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status_code,expected_level",
    [
        (200, "debug"),
        (201, "debug"),
        (301, "debug"),
        (400, "warning"),
        (404, "warning"),
        (500, "warning"),
        (503, "warning"),
    ],
)
def test_log_level_by_status(captured_logs, status_code: int, expected_level: str):
    request = _make_request()
    response = _make_response(status_code=status_code)

    record_request(request, response, started_at_monotonic=time.monotonic())

    entries = _entries(captured_logs)
    assert entries
    assert entries[-1]["log_level"] == expected_level


def test_log_level_warning_on_exception(captured_logs):
    request = _make_request()

    record_request(
        request,
        None,
        started_at_monotonic=time.monotonic(),
        exception=ConnectionError("boom"),
    )

    entries = _entries(captured_logs)
    assert entries
    assert entries[-1]["log_level"] == "warning"
    assert entries[-1]["error_class"] == "ConnectionError"


def test_log_includes_full_url_and_template(captured_logs):
    """Full URL is logged (not just template); template is also emitted alongside for grouping."""
    request = _make_request(url="https://api.example.com/v1/users/12345?cursor=abc")
    response = _make_response(status_code=200)

    record_request(request, response, started_at_monotonic=time.monotonic())

    entries = _entries(captured_logs)
    assert entries
    entry = entries[-1]
    assert entry["url"] == "https://api.example.com/v1/users/12345?cursor=abc"
    assert entry["url_template"] == "https://api.example.com/v1/users/{id}"


def test_log_redacts_auth_query_params(captured_logs):
    request = _make_request(url="https://api.example.com/?token=secret&page=2")
    response = _make_response(status_code=200)

    record_request(request, response, started_at_monotonic=time.monotonic())

    entry = _entries(captured_logs)[-1]
    assert "secret" not in entry["url"]
    assert "REDACTED" in entry["url"]


def test_log_includes_job_context_fields(captured_logs, job_ctx):
    request = _make_request()
    response = _make_response(status_code=200)

    record_request(request, response, started_at_monotonic=time.monotonic())

    entry = _entries(captured_logs)[-1]
    assert entry["team_id"] == 99
    assert entry["source_type"] == "stripe"
    assert entry["external_data_job_id"] == "run"


# ---------------------------------------------------------------------------
# RequestRecord shape
# ---------------------------------------------------------------------------


def test_request_record_captures_method_and_sizes(captured_logs):
    request = _make_request(method="POST", body=b"hello world")
    response = _make_response(status_code=200, content_length="42")

    record_request(request, response, started_at_monotonic=time.monotonic() - 0.01)

    entry = _entries(captured_logs)[-1]
    assert entry["method"] == "POST"
    assert entry["request_bytes"] == len(b"hello world")
    assert entry["response_bytes"] == 42
    assert entry["latency_ms"] >= 0


def test_request_record_response_bytes_zero_when_no_content_length(captured_logs):
    """We never touch `.content` (would break streaming) — missing CL → 0."""
    request = _make_request()
    response = _make_response(status_code=200, body=b"hello", content_length=None)

    record_request(request, response, started_at_monotonic=time.monotonic())

    entry = _entries(captured_logs)[-1]
    assert entry["response_bytes"] == 0


def test_request_record_handles_string_body(captured_logs):
    request = _make_request(method="POST", body="hello")  # str, not bytes
    response = _make_response(status_code=200)

    record_request(request, response, started_at_monotonic=time.monotonic())

    entry = _entries(captured_logs)[-1]
    assert entry["request_bytes"] == 5


def test_request_record_dataclass_round_trip():
    record = RequestRecord(
        method="GET",
        url="https://example.com/",
        request_bytes=0,
        response_bytes=10,
        status_code=200,
        latency_ms=5,
        error_class=None,
    )
    assert record.method == "GET"
    assert record.status_code == 200


# ---------------------------------------------------------------------------
# Metrics behavior
# ---------------------------------------------------------------------------


def test_metrics_no_op_when_no_job_context():
    """Without a JobContext, metrics path is skipped silently."""
    request = _make_request()
    response = _make_response(status_code=200)

    with patch("posthog.temporal.data_imports.sources.common.http.observer.get_http_requests_counter") as counter:
        record_request(request, response, started_at_monotonic=time.monotonic())

    counter.assert_not_called()


def test_metrics_emitted_when_job_context_set(job_ctx):
    request = _make_request(url="https://api.stripe.com/v1/charges")
    response = _make_response(status_code=200, content_length="100")

    with (
        patch(
            "posthog.temporal.data_imports.sources.common.http.observer.get_http_requests_counter"
        ) as counter_factory,
        patch(
            "posthog.temporal.data_imports.sources.common.http.observer.get_http_latency_histogram"
        ) as latency_factory,
        patch(
            "posthog.temporal.data_imports.sources.common.http.observer.get_http_response_bytes_histogram"
        ) as bytes_factory,
    ):
        record_request(request, response, started_at_monotonic=time.monotonic())

    counter_factory.assert_called_once_with(99, "stripe")
    latency_factory.assert_called_once_with(99, "stripe")
    bytes_factory.assert_called_once_with(99, "stripe")

    counter_factory.return_value.add.assert_called_once()
    latency_factory.return_value.record.assert_called_once()
    bytes_factory.return_value.record.assert_called_once()

    counter_attrs = counter_factory.return_value.add.call_args.args[1]
    assert counter_attrs["host"] == "api.stripe.com"
    assert counter_attrs["status_class"] == "2xx"


def test_metrics_no_response_bytes_histogram_when_zero(job_ctx):
    """If response bytes is 0 (missing CL), don't record a 0 in the bytes histogram."""
    request = _make_request()
    response = _make_response(status_code=200, content_length=None)

    with patch(
        "posthog.temporal.data_imports.sources.common.http.observer.get_http_response_bytes_histogram"
    ) as bytes_factory:
        record_request(request, response, started_at_monotonic=time.monotonic())

    bytes_factory.return_value.record.assert_not_called()


def test_observer_swallows_metric_failures(job_ctx, captured_logs):
    """A broken metric backend must not propagate into the request path."""
    request = _make_request()
    response = _make_response(status_code=200)

    with patch(
        "posthog.temporal.data_imports.sources.common.http.observer.get_http_requests_counter",
        side_effect=RuntimeError("metric broken"),
    ):
        record_request(request, response, started_at_monotonic=time.monotonic())


# ---------------------------------------------------------------------------
# Sample capture wiring
# ---------------------------------------------------------------------------


def test_sample_capture_skipped_without_context():
    request = _make_request()
    response = _make_response(status_code=200)

    with patch("posthog.temporal.data_imports.sources.common.http.observer.maybe_capture") as capture:
        record_request(request, response, started_at_monotonic=time.monotonic())

    capture.assert_not_called()


def test_sample_capture_skipped_on_exception(job_ctx):
    request = _make_request()

    with patch("posthog.temporal.data_imports.sources.common.http.observer.maybe_capture") as capture:
        record_request(
            request,
            None,
            started_at_monotonic=time.monotonic(),
            exception=ConnectionError("boom"),
        )

    capture.assert_not_called()


def test_sample_capture_called_with_context_and_response(job_ctx):
    request = _make_request()
    response = _make_response(status_code=200)

    with patch("posthog.temporal.data_imports.sources.common.http.observer.maybe_capture") as capture:
        record_request(request, response, started_at_monotonic=time.monotonic())

    capture.assert_called_once()
    kwargs = capture.call_args.kwargs
    assert kwargs["request"] is request
    assert kwargs["response"] is response
    assert kwargs["ctx"].team_id == 99


def test_observer_swallows_sampling_failures(job_ctx):
    """Sampling exception must not leak."""
    request = _make_request()
    response = _make_response(status_code=200)

    with patch(
        "posthog.temporal.data_imports.sources.common.http.observer.maybe_capture",
        side_effect=RuntimeError("sampling broken"),
    ):
        record_request(request, response, started_at_monotonic=time.monotonic())
