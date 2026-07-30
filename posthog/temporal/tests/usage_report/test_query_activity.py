"""Tests for `run_query_to_s3` — the per-query gather activity.

The dispatch path (period vs snapshot) and result persistence are
verified end-to-end against real MinIO via the `minio_workflow_ctx`
fixture; only the failure-propagation test mocks `object_storage.write`
so we can assert it was *never* called.
"""

import json
from datetime import datetime

import pytest
from unittest.mock import patch

from temporalio.exceptions import ApplicationError

from posthog.storage import object_storage
from posthog.temporal.usage_report import storage
from posthog.temporal.usage_report.activities import run_query_to_s3, summarize_exception_chain
from posthog.temporal.usage_report.queries import QuerySpec
from posthog.temporal.usage_report.storage import queries_key
from posthog.temporal.usage_report.types import RunQueryToS3Inputs, WorkflowContext


@pytest.mark.asyncio
async def test_run_query_to_s3_calls_fn_with_period_and_writes_to_s3(
    minio_workflow_ctx: WorkflowContext, activity_environment
) -> None:
    """Period specs receive (begin, end) and the result lands in MinIO."""
    seen_periods: list[tuple[datetime, datetime]] = []

    def fake_query(begin: datetime, end: datetime) -> list[tuple[int, int]]:
        seen_periods.append((begin, end))
        return [(1, 100), (2, 50)]

    fake_spec = QuerySpec(name="test_query_metric", fn=fake_query)

    with patch.dict(
        "posthog.temporal.usage_report.activities.QUERY_INDEX",
        {"test_query_metric": fake_spec},
        clear=False,
    ):
        result = await activity_environment.run(
            run_query_to_s3,
            RunQueryToS3Inputs(ctx=minio_workflow_ctx, query_name="test_query_metric"),
        )

    # Period passed through verbatim from WorkflowContext.
    assert seen_periods == [(minio_workflow_ctx.period_start, minio_workflow_ctx.period_end)]

    # Result advertises the right key + name; duration is non-negative.
    assert result.query_name == "test_query_metric"
    assert result.s3_key == queries_key(minio_workflow_ctx, "test_query_metric")
    assert result.duration_ms >= 0

    # And the returned key actually has the rows in MinIO.
    body = object_storage.read_bytes(result.s3_key, bucket=storage.bucket())
    assert body is not None
    # `default=str` coerces tuples to lists during JSON encoding.
    assert json.loads(body) == [[1, 100], [2, 50]]


@pytest.mark.asyncio
async def test_run_query_to_s3_snapshot_kind_calls_fn_without_period(
    minio_workflow_ctx: WorkflowContext, activity_environment
) -> None:
    """Snapshot specs declare zero-arg fns — the activity must dispatch
    them without the period, otherwise we'd get a TypeError.
    """
    fn_args: list[tuple] = []

    def fake_snapshot_query() -> list[dict[str, int]]:
        fn_args.append(())
        return [{"team_id": 1, "total": 7}]

    fake_spec = QuerySpec(
        name="test_snapshot_count",
        fn=fake_snapshot_query,
        kind="snapshot",
    )

    with patch.dict(
        "posthog.temporal.usage_report.activities.QUERY_INDEX",
        {"test_snapshot_count": fake_spec},
        clear=False,
    ):
        result = await activity_environment.run(
            run_query_to_s3,
            RunQueryToS3Inputs(ctx=minio_workflow_ctx, query_name="test_snapshot_count"),
        )

    assert fn_args == [()], "Snapshot fn should be invoked with no positional args"
    assert result.query_name == "test_snapshot_count"
    body = object_storage.read_bytes(result.s3_key, bucket=storage.bucket())
    assert body is not None
    assert json.loads(body) == [{"team_id": 1, "total": 7}]


@pytest.mark.asyncio
async def test_run_query_to_s3_propagates_query_failure(
    minio_workflow_ctx: WorkflowContext, activity_environment
) -> None:
    """If the underlying query raises, the activity must raise and not
    write a partial / stale object — otherwise re-runs would skip the
    gather. We mock `write` so we can assert it was *never* called.
    """

    def boom(begin: datetime, end: datetime) -> None:
        raise RuntimeError("boom")

    fake_spec = QuerySpec(name="test_failing_query", fn=boom)

    with (
        patch.dict(
            "posthog.temporal.usage_report.activities.QUERY_INDEX",
            {"test_failing_query": fake_spec},
            clear=False,
        ),
        patch("posthog.temporal.usage_report.storage.object_storage.write") as mock_write,
    ):
        with pytest.raises(Exception, match="boom"):
            await activity_environment.run(
                run_query_to_s3,
                RunQueryToS3Inputs(ctx=minio_workflow_ctx, query_name="test_failing_query"),
            )

    mock_write.assert_not_called()


def test_summarize_exception_chain_flattens_causes() -> None:
    root = ValueError("root cause")
    middle = RuntimeError("middle")
    middle.__cause__ = root
    top = OSError("top")
    top.__cause__ = middle

    summary = summarize_exception_chain(top)

    assert summary == "OSError: top | caused by RuntimeError: middle | caused by ValueError: root cause"


def test_summarize_exception_chain_bounds_depth_and_length() -> None:
    """A chain deeper than the cap is truncated rather than walked to the end,
    which is what makes this safe for the pathological chains that break
    Temporal's recursive converter.
    """
    head = ValueError("level 0")
    current = head
    for level in range(1, 100):
        nxt = ValueError(f"level {level}")
        current.__cause__ = nxt
        current = nxt

    summary = summarize_exception_chain(head, max_depth=3)

    assert summary.startswith("ValueError: level 0 | caused by ValueError: level 1")
    assert "level 3" not in summary
    assert summary.endswith("... (cause chain truncated)")

    assert len(summarize_exception_chain(ValueError("x" * 5_000), max_chars=100)) == 100


def test_summarize_exception_chain_survives_self_referential_chain() -> None:
    a = ValueError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__cause__ = a

    assert summarize_exception_chain(a) == "ValueError: a | caused by ValueError: b"


@pytest.mark.asyncio
async def test_run_query_to_s3_failure_keeps_diagnostic_out_of_temporal_recursion(
    minio_workflow_ctx: WorkflowContext, activity_environment
) -> None:
    """The failure the activity raises must carry the original type, value and
    query name in its message, and must have no `__cause__`/`__context__` for
    Temporal's converter to recurse over.
    """

    def boom(begin: datetime, end: datetime) -> None:
        try:
            raise RecursionError("maximum recursion depth exceeded")
        except RecursionError as err:
            raise RuntimeError("query wrapper failed") from err

    fake_spec = QuerySpec(name="test_recursive_failure", fn=boom)

    with patch.dict(
        "posthog.temporal.usage_report.activities.QUERY_INDEX",
        {"test_recursive_failure": fake_spec},
        clear=False,
    ):
        with pytest.raises(ApplicationError) as exc_info:
            await activity_environment.run(
                run_query_to_s3,
                RunQueryToS3Inputs(ctx=minio_workflow_ctx, query_name="test_recursive_failure"),
            )

    err = exc_info.value
    message = str(err)
    assert "test_recursive_failure" in message
    assert "RuntimeError: query wrapper failed" in message
    assert "RecursionError: maximum recursion depth exceeded" in message
    assert err.__cause__ is None
    assert err.__context__ is None
