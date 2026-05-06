"""Tests for the usage report S3 helpers.

Pure key-formatting tests don't touch storage. Roundtrip and writer tests
hit the real MinIO instance configured for the dev stack — the
`minio_workflow_ctx` fixture cleans up its run prefix at teardown so
the bucket stays tidy. Error-path tests (failed delete, exception
during stream) stay mocked because MinIO won't naturally trigger them.
"""

import gzip
import json

import pytest
from unittest.mock import patch

from posthog.storage import object_storage
from posthog.temporal.usage_report import storage
from posthog.temporal.usage_report.storage import (
    chunk_key,
    chunks_prefix,
    delete_keys,
    manifest_key,
    queries_key,
    queries_prefix,
    run_prefix,
    streamed_jsonl_gzip_writer,
    write_json,
    write_jsonl_chunk_gzip,
)
from posthog.temporal.usage_report.types import WorkflowContext


def _ctx(run_id: str = "abc-123", date_str: str = "2026-05-04") -> WorkflowContext:
    from datetime import UTC, datetime

    return WorkflowContext(
        run_id=run_id,
        period_start=datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC),
        date_str=date_str,
    )


# ---- key formatting (pure) -----------------------------------------------


def test_run_prefix_includes_date_and_run_id() -> None:
    ctx = _ctx()
    prefix = run_prefix(ctx)
    assert prefix.endswith("/billing/usage_reports/2026-05-04/abc-123")


def test_queries_key_uses_query_name() -> None:
    ctx = _ctx()
    assert queries_key(ctx, "teams_with_event_count_in_period").endswith(
        "/queries/teams_with_event_count_in_period.json"
    )


def test_chunk_key_zero_padded() -> None:
    ctx = _ctx()
    assert chunk_key(ctx, 0).endswith("/chunks/chunk_0000.jsonl.gz")
    assert chunk_key(ctx, 12).endswith("/chunks/chunk_0012.jsonl.gz")


def test_manifest_key() -> None:
    ctx = _ctx()
    assert manifest_key(ctx).endswith("/abc-123/manifest.json")


def test_queries_and_chunks_prefix() -> None:
    ctx = _ctx()
    assert queries_prefix(ctx).endswith("/abc-123/queries")
    assert chunks_prefix(ctx).endswith("/abc-123/chunks")


def test_bucket_reads_billing_setting() -> None:
    """`bucket()` reflects the dedicated billing bucket setting."""
    with patch("posthog.temporal.usage_report.storage.settings") as mock_settings:
        mock_settings.BILLING_USAGE_REPORTS_S3_BUCKET = "posthog-billing-usage-reports"
        assert storage.bucket() == "posthog-billing-usage-reports"


# ---- real MinIO roundtrips -----------------------------------------------


def test_write_json_roundtrip_via_minio(minio_workflow_ctx: WorkflowContext) -> None:
    key = queries_key(minio_workflow_ctx, "teams_with_event_count_in_period")
    payload = {"data": [(1, 100), (2, 50)], "meta": {"version": 1}}

    write_json(key, payload)

    decoded = storage.read_json(key)
    # `default=str` coerces tuples to lists during JSON encoding.
    assert decoded == {"data": [[1, 100], [2, 50]], "meta": {"version": 1}}


def test_write_jsonl_chunk_gzip_roundtrip_via_minio(minio_workflow_ctx: WorkflowContext) -> None:
    """End-to-end: gzipped JSONL written via the helper is downloadable
    and decompresses to the original lines.
    """
    key = chunk_key(minio_workflow_ctx, 0)
    lines = [
        {"organization_id": "org-1", "usage_report": {"event_count_in_period": 1}},
        {"organization_id": "org-2", "usage_report": {"event_count_in_period": 2}},
        {"organization_id": "org-3", "usage_report": {"event_count_in_period": 3}},
    ]

    count = write_jsonl_chunk_gzip(key, lines)

    assert count == 3
    body = object_storage.read_bytes(key, bucket=storage.bucket())
    assert body is not None
    decompressed = gzip.decompress(body).decode("utf-8")
    decoded = [json.loads(line) for line in decompressed.splitlines()]
    assert decoded == lines


def test_write_jsonl_chunk_gzip_sets_content_headers_via_minio(minio_workflow_ctx: WorkflowContext) -> None:
    """The chunk object must land with `application/x-ndjson` + `gzip`
    encoding so billing's S3 reader can stream-decompress it.
    """
    key = chunk_key(minio_workflow_ctx, 0)
    write_jsonl_chunk_gzip(key, [{"organization_id": "org-1"}])

    head = object_storage.head_object(key, bucket=storage.bucket())
    assert head is not None
    assert head["ContentType"] == "application/x-ndjson"
    assert head["ContentEncoding"] == "gzip"


@pytest.mark.asyncio
async def test_streamed_jsonl_gzip_writer_uploads_on_clean_exit_via_minio(
    minio_workflow_ctx: WorkflowContext,
) -> None:
    """Async ctx-mgr happy path: lines written, gzip streamed to MinIO."""
    key = chunk_key(minio_workflow_ctx, 0)

    async with streamed_jsonl_gzip_writer(key) as w:
        w.write({"organization_id": "org-1"})
        w.write_lines([{"organization_id": "org-2"}, {"organization_id": "org-3"}])
        assert w.line_count == 3

    body = object_storage.read_bytes(key, bucket=storage.bucket())
    assert body is not None
    rows = [json.loads(line) for line in gzip.decompress(body).decode("utf-8").splitlines()]
    assert rows == [
        {"organization_id": "org-1"},
        {"organization_id": "org-2"},
        {"organization_id": "org-3"},
    ]


@pytest.mark.asyncio
async def test_streamed_jsonl_gzip_writer_skips_upload_on_exception_via_minio(
    minio_workflow_ctx: WorkflowContext,
) -> None:
    """If the body raises, we must not upload a partial chunk."""
    key = chunk_key(minio_workflow_ctx, 0)

    with pytest.raises(RuntimeError, match="boom"):
        async with streamed_jsonl_gzip_writer(key) as w:
            w.write({"organization_id": "org-1"})
            raise RuntimeError("boom")

    # head_object swallows NoSuchKey and returns None
    assert object_storage.head_object(key, bucket=storage.bucket()) is None


# ---- mocked error paths --------------------------------------------------
# MinIO doesn't error on `delete` of a missing key, so the failure-handling
# branch in `delete_keys` is exercised with a mock — there's no way to
# trigger it against real S3 short of taking the bucket offline.


def test_jsonl_gzip_writer_batches_writes_to_gzip_stream() -> None:
    """Lines should accumulate into the local pending buffer until the
    flush threshold is crossed, *then* be handed to the gzip stream in
    one larger chunk — that's what trims the per-line overhead.
    """
    from posthog.temporal.usage_report.storage import JsonlGzipWriter

    # 100-byte threshold so a small test still exercises multiple flushes.
    writer = JsonlGzipWriter(flush_threshold_bytes=100)
    gz_write_sizes: list[int] = []

    def record_write(payload: bytes) -> int:
        gz_write_sizes.append(len(payload))
        return len(payload)

    with patch.object(writer._gz, "write", side_effect=record_write):
        # 8 lines of ~38 bytes ≈ 300 bytes → expect at least 2 threshold-driven flushes.
        for i in range(8):
            writer.write({"line": i, "padding": "x" * 20})
        flushes_during_writes = len(gz_write_sizes)
        assert flushes_during_writes >= 2, "should flush when the pending buffer crosses the threshold"
        assert all(size >= 100 for size in gz_write_sizes), "every threshold-driven flush must clear the threshold"

        # Final flush should drain whatever's still pending, then a second
        # flush is a no-op.
        writer._flush_pending()
        after_first_finalize = len(gz_write_sizes)
        writer._flush_pending()
        assert len(gz_write_sizes) == after_first_finalize, "no extra gzip.write when nothing is pending"

    assert writer.line_count == 8


def test_delete_keys_continues_on_failure() -> None:
    calls: list[str] = []

    def fake_delete(key, bucket=None):
        calls.append(key)
        if key == "fail":
            raise RuntimeError("boom")

    with patch("posthog.temporal.usage_report.storage.object_storage.delete", side_effect=fake_delete):
        deleted = delete_keys(["one", "fail", "two"])

    assert calls == ["one", "fail", "two"]
    assert deleted == 2


def test_delete_keys_via_minio_removes_real_objects(minio_workflow_ctx: WorkflowContext) -> None:
    """Sanity check the MinIO path of `delete_keys` end-to-end."""
    key_a = queries_key(minio_workflow_ctx, "spec_a")
    key_b = queries_key(minio_workflow_ctx, "spec_b")
    write_json(key_a, {"x": 1})
    write_json(key_b, {"x": 2})

    deleted = delete_keys([key_a, key_b])

    assert deleted == 2
    assert object_storage.head_object(key_a, bucket=storage.bucket()) is None
    assert object_storage.head_object(key_b, bucket=storage.bucket()) is None
