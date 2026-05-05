"""Tests for `run_query_to_s3` — the per-query gather activity."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import patch

from posthog.temporal.usage_report.activities import run_query_to_s3
from posthog.temporal.usage_report.queries import QuerySpec
from posthog.temporal.usage_report.types import RunQueryToS3Inputs, WorkflowContext


def _ctx() -> WorkflowContext:
    return WorkflowContext(
        run_id="run-test",
        period_start=datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC),
        date_str="2026-05-04",
    )


@pytest.mark.asyncio
async def test_run_query_to_s3_calls_fn_with_period_and_writes_to_s3(activity_environment) -> None:
    """The activity should pass the workflow context's period through to
    the registered QuerySpec function and persist the result to a key
    derived from the spec name.
    """
    seen_periods: list[tuple[datetime, datetime]] = []
    written: dict[str, bytes] = {}

    def fake_query(begin: datetime, end: datetime) -> list[tuple[int, int]]:
        seen_periods.append((begin, end))
        return [(1, 100), (2, 50)]

    fake_spec = QuerySpec(name="test_query_metric", fn=fake_query)

    def fake_write(key: str, content: Any, extras: dict | None = None) -> None:
        written[key] = content.encode("utf-8") if isinstance(content, str) else content

    with (
        patch.dict(
            "posthog.temporal.usage_report.activities.QUERY_INDEX",
            {"test_query_metric": fake_spec},
            clear=False,
        ),
        patch("posthog.temporal.usage_report.storage.object_storage.write", side_effect=fake_write),
    ):
        result = await activity_environment.run(
            run_query_to_s3,
            RunQueryToS3Inputs(ctx=_ctx(), query_name="test_query_metric"),
        )

    # Period passed through verbatim from WorkflowContext.
    assert seen_periods == [(datetime(2026, 5, 4, tzinfo=UTC), datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC))]

    # Result advertises the right key + name; duration is non-negative.
    assert result.query_name == "test_query_metric"
    assert result.s3_key.endswith("/queries/test_query_metric.json")
    assert result.duration_ms >= 0

    # And the returned key is what got written to S3, with the rows intact.
    assert result.s3_key in written
    assert json.loads(written[result.s3_key]) == [[1, 100], [2, 50]]


@pytest.mark.asyncio
async def test_run_query_to_s3_snapshot_kind_calls_fn_without_period(activity_environment) -> None:
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

    written: dict[str, Any] = {}

    def fake_write(key: str, content: Any, extras: dict | None = None) -> None:
        written[key] = content

    with (
        patch.dict(
            "posthog.temporal.usage_report.activities.QUERY_INDEX",
            {"test_snapshot_count": fake_spec},
            clear=False,
        ),
        patch("posthog.temporal.usage_report.storage.object_storage.write", side_effect=fake_write),
    ):
        result = await activity_environment.run(
            run_query_to_s3,
            RunQueryToS3Inputs(ctx=_ctx(), query_name="test_snapshot_count"),
        )

    assert fn_args == [()], "Snapshot fn should be invoked with no positional args"
    assert result.query_name == "test_snapshot_count"
    assert json.loads(written[result.s3_key]) == [{"team_id": 1, "total": 7}]


@pytest.mark.asyncio
async def test_run_query_to_s3_propagates_query_failure(activity_environment) -> None:
    """If the underlying query raises, the activity must raise too —
    otherwise Temporal can't retry it.
    """
    fake_spec = QuerySpec(name="test_failing_query", fn=lambda b, e: (_ for _ in ()).throw(RuntimeError("boom")))

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
                RunQueryToS3Inputs(ctx=_ctx(), query_name="test_failing_query"),
            )

    # Must not write anything if the query failed — otherwise re-runs see
    # a stale key and skip the gather.
    mock_write.assert_not_called()
