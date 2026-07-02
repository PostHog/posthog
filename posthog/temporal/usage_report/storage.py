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
from collections.abc import Iterable
from typing import Any

from django.conf import settings

import orjson
import structlog

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


def write_json(key: str, obj: Any, *, compress: bool = False) -> None:
    """Write a JSON-encoded object to S3 with `application/json` content type.

    Uses `default=str` to coerce datetimes / Decimal / etc. into strings; the
    aggregation activity reads these back and feeds them through existing
    helpers that already tolerate string ints.

    `compress=True` gzips the body before the PUT. Row-shaped query results
    compress ~8-10x even at level 1 (which costs almost no CPU), cutting both
    the upload here and the download in `load_all_data`. Keep the manifest
    uncompressed — it's part of the billing-facing contract; only the
    per-query intermediates (read back exclusively by `read_json`) opt in.
    """
    serialized = json.dumps(obj, default=str)
    extras = {"ContentType": "application/json"}
    body: str | bytes = serialized
    if compress:
        body = gzip.compress(serialized.encode("utf-8"), compresslevel=1)
        extras["ContentEncoding"] = "gzip"
    object_storage.write(key, body, extras=extras, bucket=bucket())


def read_json(key: str) -> Any:
    """Read a JSON object from S3. Raises if the key is missing.

    Sniffs the gzip magic bytes instead of trusting metadata so it can read
    both compressed and uncompressed payloads — a run can span a deploy where
    the query activities wrote one format and aggregation reads with the other.
    """
    raw = object_storage.read_bytes(key, bucket=bucket())
    if raw is None:
        raise FileNotFoundError(f"S3 key not found: {key}")
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def write_jsonl_chunk_gzip(key: str, lines: Iterable[dict[str, Any]]) -> int:
    """Stream-encode `lines` as JSONL straight into gzip, then upload the
    compressed body to S3 in a single `upload_fileobj` call.

    Per-line: one encoded `bytes` is fed to `gzip.GzipFile.write` and
    immediately compressed into the underlying `BytesIO`. We never hold
    the whole uncompressed payload — peak memory per chunk is roughly
    `compressed_size` plus gzip's 32 KB window and one in-flight encoded
    line. That matters when several chunks are written concurrently, since
    a naive `b"\\n".join(...)` would double-allocate ~25–50 MB per chunk.

    Encoding and compression choices are the hot loop of the whole upload:

    * orjson over stdlib json — several times faster per line.
      `OPT_PASSTHROUGH_DATETIME` + `default=str` keeps datetime coercion
      identical to the legacy `json.dumps(..., default=str)` (`str(dt)`,
      space-separated), and `OPT_NON_STR_KEYS` matches stdlib's int-key
      coercion. Parsed-payload parity with the Celery path is pinned by
      `test_parity.py`.
    * `compresslevel=6` over GzipFile's default 9 — roughly half the
      compression CPU for ~1% larger chunks; zlib also releases the GIL
      here, so concurrent chunk writers genuinely overlap.
    * `write_stream` (multipart `upload_fileobj`) over `put_object` —
      uploads large chunks in concurrent parts and avoids `getvalue()`
      copying the whole compressed body.
    """
    line_count = 0
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6) as gz:
        for line in lines:
            gz.write(
                orjson.dumps(
                    line,
                    default=str,
                    option=orjson.OPT_APPEND_NEWLINE | orjson.OPT_PASSTHROUGH_DATETIME | orjson.OPT_NON_STR_KEYS,
                )
            )
            line_count += 1

    buffer.seek(0)
    object_storage.write_stream(
        key,
        buffer,
        extras={"ContentType": "application/x-ndjson", "ContentEncoding": "gzip"},
        bucket=bucket(),
    )
    return line_count


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
