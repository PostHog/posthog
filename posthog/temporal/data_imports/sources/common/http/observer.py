"""Per-request observer for the tracked HTTP transport.

The transport calls `record_request` once per outbound HTTP request — both
successful responses and exceptions. The observer:

- emits a structlog log line with the scrubbed full URL, status, latency
  and request/response sizes, plus all `JobContext` labels;
- updates OTel counters/histograms labelled by `team_id`, `source_type`,
  `host`, and `status_class`;
- delegates to the sampling subsystem, which is a cheap no-op when
  capture is disabled in Redis.

Both the metrics call and the sampling call are wrapped in `try/except`
that logs at debug — the observer must never raise into the request
path. A broken telemetry layer cannot become a sync failure.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass

import structlog
from requests import PreparedRequest, Response

from posthog.temporal.data_imports.sources.common.http.context import JobContext, current_job_context
from posthog.temporal.data_imports.sources.common.http.metrics import (
    get_http_latency_histogram,
    get_http_requests_counter,
    get_http_response_bytes_histogram,
    status_class,
)
from posthog.temporal.data_imports.sources.common.http.sampling import maybe_capture
from posthog.temporal.data_imports.sources.common.http.url_utils import host_of, scrub_url, url_template

logger = structlog.get_logger(__name__)
_fallback_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestRecord:
    method: str
    url: str
    request_bytes: int
    response_bytes: int
    status_code: int | None
    latency_ms: int
    error_class: str | None


def _request_size(request: PreparedRequest) -> int:
    body = request.body
    if body is None:
        return 0
    if isinstance(body, str):
        return len(body.encode("utf-8", errors="ignore"))
    # `requests` types `body` as `str | bytes | None` but at runtime a
    # caller can hand it a bytearray, file-like, or generator. Anything
    # we can `len()` directly is fine; anything else (file/generator)
    # would force the stream into memory, so we report 0 instead.
    try:
        return len(body)
    except TypeError:
        return 0


def _response_size(response: Response | None) -> int:
    if response is None:
        return 0
    content_length = response.headers.get("Content-Length")
    if content_length and content_length.isdigit():
        return int(content_length)
    # Touching `.content` would force the body into memory and break
    # streaming. Return 0 if Content-Length is missing — better to lose a
    # data point than to break a streaming download.
    return 0


def record_request(
    request: PreparedRequest,
    response: Response | None,
    *,
    started_at_monotonic: float,
    exception: BaseException | None = None,
) -> None:
    """Log + meter a single outbound request. Never raises."""
    elapsed_ms = max(0, int((time.monotonic() - started_at_monotonic) * 1000))
    method = (request.method or "GET").upper()
    raw_url = request.url or ""
    scrubbed_url = scrub_url(raw_url)
    template = url_template(raw_url)
    host = host_of(raw_url)
    status_code = response.status_code if response is not None else None
    error_class = type(exception).__name__ if exception is not None else None
    request_bytes = _request_size(request)
    response_bytes = _response_size(response)

    record = RequestRecord(
        method=method,
        url=scrubbed_url,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
        status_code=status_code,
        latency_ms=elapsed_ms,
        error_class=error_class,
    )

    ctx = current_job_context()
    _emit_log(record, host=host, url_template=template, ctx=ctx)
    _emit_metrics(record, host=host, ctx=ctx)
    _maybe_capture_sample(request, response, record=record, ctx=ctx, exception=exception)


def _emit_log(
    record: RequestRecord,
    *,
    host: str,
    url_template: str,
    ctx: JobContext | None,
) -> None:
    fields = {
        "method": record.method,
        "url": record.url,
        "url_template": url_template,
        "host": host,
        "status_code": record.status_code,
        "latency_ms": record.latency_ms,
        "request_bytes": record.request_bytes,
        "response_bytes": record.response_bytes,
        "error_class": record.error_class,
    }
    # Activity already binds team_id; we add the rest here so a request
    # logged from outside an activity (e.g. a unit test) still carries
    # source/job labels. `bind_job_context()` does the same via
    # contextvars, so this is belt-and-braces.
    if ctx is not None:
        fields.update(ctx.as_log_fields())

    if record.error_class is not None:
        logger.warning(f"data_imports.http.request {record.url}", **fields)
    elif record.status_code is not None and record.status_code >= 400:
        logger.warning(f"data_imports.http.request {record.url}", **fields)
    else:
        logger.debug(f"data_imports.http.request {record.url}", **fields)


def _emit_metrics(record: RequestRecord, *, host: str, ctx: JobContext | None) -> None:
    if ctx is None:
        return
    try:
        attrs = {"host": host, "status_class": status_class(record.status_code)}
        get_http_requests_counter(ctx.team_id, ctx.source_type).add(1, attrs)
        get_http_latency_histogram(ctx.team_id, ctx.source_type).record(record.latency_ms, attrs)
        if record.response_bytes:
            get_http_response_bytes_histogram(ctx.team_id, ctx.source_type).record(record.response_bytes, attrs)
    except Exception:
        _fallback_logger.debug("Failed to record HTTP metric", exc_info=True)


def _maybe_capture_sample(
    request: PreparedRequest,
    response: Response | None,
    *,
    record: RequestRecord,
    ctx: JobContext | None,
    exception: BaseException | None,
) -> None:
    if ctx is None or exception is not None:
        return
    try:
        maybe_capture(request=request, response=response, record=record, ctx=ctx)
    except Exception:
        _fallback_logger.debug("Failed to capture HTTP sample", exc_info=True)
