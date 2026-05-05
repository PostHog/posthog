"""Pure-Python tests for the usage report S3 helpers."""

import gzip
import json
from typing import Any

from unittest.mock import patch

from posthog.temporal.usage_report.storage import (
    chunk_key,
    chunks_prefix,
    manifest_key,
    queries_key,
    queries_prefix,
    run_prefix,
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


def test_write_jsonl_chunk_gzip_roundtrip() -> None:
    captured: dict[str, Any] = {}

    def fake_write_stream(key, fileobj, extras=None):  # type: ignore[no-untyped-def]
        captured["key"] = key
        captured["body"] = fileobj.read()
        captured["extras"] = extras

    lines = [
        {"organization_id": "org-1", "usage_report": {"event_count_in_period": 1}},
        {"organization_id": "org-2", "usage_report": {"event_count_in_period": 2}},
        {"organization_id": "org-3", "usage_report": {"event_count_in_period": 3}},
    ]

    with patch("posthog.temporal.usage_report.storage.object_storage.write_stream", side_effect=fake_write_stream):
        count = write_jsonl_chunk_gzip("foo/bar.jsonl.gz", lines)

    assert count == 3
    assert captured["key"] == "foo/bar.jsonl.gz"
    assert captured["extras"] == {"ContentType": "application/x-ndjson", "ContentEncoding": "gzip"}

    decompressed = gzip.decompress(captured["body"]).decode("utf-8")
    decoded = [json.loads(line) for line in decompressed.splitlines()]
    assert decoded == lines


def test_delete_keys_continues_on_failure() -> None:
    from posthog.temporal.usage_report.storage import delete_keys

    calls: list[str] = []

    def fake_delete(key: str) -> None:
        calls.append(key)
        if key == "fail":
            raise RuntimeError("boom")

    with patch("posthog.temporal.usage_report.storage.object_storage.delete", side_effect=fake_delete):
        deleted = delete_keys(["one", "fail", "two"])

    assert calls == ["one", "fail", "two"]
    assert deleted == 2


# ---- streamed_jsonl_gzip_writer (async context manager) ------------------

import pytest  # noqa: E402

from posthog.temporal.usage_report.storage import streamed_jsonl_gzip_writer  # noqa: E402


@pytest.mark.asyncio
async def test_streamed_jsonl_gzip_writer_uploads_on_clean_exit() -> None:
    """`async with` exits cleanly → gzipped JSONL streamed to S3 with the
    right ContentType/ContentEncoding headers.
    """
    captured: dict[str, object] = {}

    def fake_write_stream(key, fileobj, extras=None):  # type: ignore[no-untyped-def]
        captured["key"] = key
        captured["body"] = fileobj.read()
        captured["extras"] = extras

    with patch("posthog.temporal.usage_report.storage.object_storage.write_stream", side_effect=fake_write_stream):
        async with streamed_jsonl_gzip_writer("foo/bar.jsonl.gz") as w:
            w.write({"organization_id": "org-1"})
            w.write_lines([{"organization_id": "org-2"}, {"organization_id": "org-3"}])
            assert w.line_count == 3

    assert captured["key"] == "foo/bar.jsonl.gz"
    assert captured["extras"] == {"ContentType": "application/x-ndjson", "ContentEncoding": "gzip"}

    decompressed = gzip.decompress(captured["body"]).decode("utf-8")  # type: ignore[arg-type]
    rows = [json.loads(line) for line in decompressed.splitlines()]
    assert rows == [
        {"organization_id": "org-1"},
        {"organization_id": "org-2"},
        {"organization_id": "org-3"},
    ]


@pytest.mark.asyncio
async def test_streamed_jsonl_gzip_writer_skips_upload_on_exception() -> None:
    """If the body raises, we must not upload a partial chunk."""
    write_calls: list = []

    def fake_write_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        write_calls.append((args, kwargs))

    with patch("posthog.temporal.usage_report.storage.object_storage.write_stream", side_effect=fake_write_stream):
        with pytest.raises(RuntimeError, match="boom"):
            async with streamed_jsonl_gzip_writer("foo/bar.jsonl.gz") as w:
                w.write({"organization_id": "org-1"})
                raise RuntimeError("boom")

    assert write_calls == []
