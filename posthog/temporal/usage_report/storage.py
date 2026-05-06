"""S3 path conventions and IO helpers for the usage reports workflow.

All keys are scoped under
`{OBJECT_STORAGE_TASKS_FOLDER}/billing/usage_reports/{YYYY-MM-DD}/{run_id}/`
so multiple runs on the same date never collide. The bucket is
`settings.BILLING_USAGE_REPORTS_S3_BUCKET`, which falls back to
`OBJECT_STORAGE_BUCKET` so dev / self-hosted keep working without extra
configuration.
"""

import io
import gzip
import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async

from posthog.storage import object_storage
from posthog.temporal.usage_report.types import WorkflowContext

logger = structlog.get_logger(__name__)


def bucket() -> str:
    """The S3 bucket all usage-report artifacts go into. Read at call time
    rather than module import so tests can `override_settings` cleanly.
    """
    return settings.BILLING_USAGE_REPORTS_S3_BUCKET


def run_prefix(ctx: WorkflowContext) -> str:
    """The S3 prefix for everything written by a single workflow run."""
    return f"{settings.OBJECT_STORAGE_TASKS_FOLDER}/billing/usage_reports/{ctx.date_str}/{ctx.run_id}"


def queries_prefix(ctx: WorkflowContext) -> str:
    return f"{run_prefix(ctx)}/queries"


def chunks_prefix(ctx: WorkflowContext) -> str:
    return f"{run_prefix(ctx)}/chunks"


def queries_key(ctx: WorkflowContext, query_name: str) -> str:
    return f"{queries_prefix(ctx)}/{query_name}.json"


def chunk_key(ctx: WorkflowContext, index: int) -> str:
    return f"{chunks_prefix(ctx)}/chunk_{index:04d}.jsonl.gz"


def manifest_key(ctx: WorkflowContext) -> str:
    return f"{run_prefix(ctx)}/manifest.json"


def write_json(key: str, obj: Any) -> None:
    """Write a JSON-encoded object to S3 with `application/json` content type.

    Uses `default=str` to coerce datetimes / Decimal / etc. into strings; the
    aggregation activity reads these back and feeds them through existing
    helpers that already tolerate string ints.
    """
    object_storage.write(
        key,
        json.dumps(obj, default=str),
        extras={"ContentType": "application/json"},
        bucket=bucket(),
    )


def read_json(key: str) -> Any:
    """Read a JSON object from S3. Raises if the key is missing."""
    raw = object_storage.read_bytes(key, bucket=bucket())
    if raw is None:
        raise FileNotFoundError(f"S3 key not found: {key}")
    return json.loads(raw)


# Encoded JSONL bytes are buffered up to this size before being handed
# to `gzip.GzipFile.write`. The per-call overhead of gzip.write is small
# but non-zero, so batching ~256KB at a time noticeably trims the cost
# of writing 10k lines per chunk without growing memory pressure.
_GZIP_FLUSH_THRESHOLD_BYTES = 256 * 1024


class JsonlGzipWriter:
    """Buffer used by `streamed_jsonl_gzip_writer`. Encodes JSONL lines
    into an in-memory `bytearray`, flushes to the gzip stream in
    `_GZIP_FLUSH_THRESHOLD_BYTES`-sized batches, and the gzip stream
    then flushes to S3 on context-manager exit.
    """

    def __init__(self, flush_threshold_bytes: int = _GZIP_FLUSH_THRESHOLD_BYTES) -> None:
        self._buffer = io.BytesIO()
        self._gz = gzip.GzipFile(fileobj=self._buffer, mode="wb")
        self._pending = bytearray()
        self._flush_threshold = flush_threshold_bytes
        self.line_count = 0

    def write(self, line: dict[str, Any]) -> None:
        self._pending += json.dumps(line, separators=(",", ":"), default=str).encode("utf-8")
        self._pending += b"\n"
        self.line_count += 1
        if len(self._pending) >= self._flush_threshold:
            self._flush_pending()

    def write_lines(self, lines: Iterable[dict[str, Any]]) -> None:
        for line in lines:
            self.write(line)

    def _flush_pending(self) -> None:
        if not self._pending:
            return
        self._gz.write(bytes(self._pending))
        self._pending.clear()

    def _finalize(self) -> bytes:
        self._flush_pending()
        self._gz.close()
        return self._buffer.getvalue()


@asynccontextmanager
async def streamed_jsonl_gzip_writer(key: str) -> AsyncIterator[JsonlGzipWriter]:
    """Async context manager that yields a `JsonlGzipWriter`. On clean exit
    the gzipped JSONL bytes are streamed to S3 at `key` with the
    `application/x-ndjson` + `gzip` headers billing's reader expects. If
    the body raises, nothing gets uploaded.

        async with streamed_jsonl_gzip_writer(key) as w:
            w.write_lines(lines)
            # or w.write({...}) per line
    """
    writer = JsonlGzipWriter()
    yield writer
    body = writer._finalize()
    await sync_to_async(_upload_gzipped_jsonl)(key, body)


def _upload_gzipped_jsonl(key: str, body: bytes) -> None:
    object_storage.write_stream(
        key,
        io.BytesIO(body),
        extras={"ContentType": "application/x-ndjson", "ContentEncoding": "gzip"},
        bucket=bucket(),
    )


def write_jsonl_chunk_gzip(key: str, lines: Iterable[dict[str, Any]]) -> int:
    """Sync one-shot variant of `streamed_jsonl_gzip_writer` for callers
    (tests, scripts) that just want to gzip-and-upload a list of lines.
    """
    writer = JsonlGzipWriter()
    writer.write_lines(lines)
    body = writer._finalize()
    _upload_gzipped_jsonl(key, body)
    return writer.line_count


def delete_keys(keys: Iterable[str]) -> int:
    """Best-effort delete; missing keys are logged and skipped."""
    deleted = 0
    target_bucket = bucket()
    for key in keys:
        try:
            object_storage.delete(key, bucket=target_bucket)
            deleted += 1
        except Exception as err:
            logger.warning("usage_reports.cleanup.delete_failed", key=key, error=str(err))
    return deleted
