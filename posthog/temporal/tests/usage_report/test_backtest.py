"""Tests for the usage-reports backtest workflow.

The pure tests pin the diff semantics: what counts as a difference, how
candidate-only teams are bucketed, and how the baseline run is selected.

The integration test runs the whole loop against the real stack: events in
ClickHouse → a baseline built by the production aggregation activity →
the three backtest activities. It catches what the pure tests can't — S3
key layout, manifest parsing, chunk streaming, and period handling — and
proves one inserted event flips the report from clean to dirty.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async

from posthog.models.event.util import create_event
from posthog.temporal.tests.usage_report.test_aggregate_activity import _instance_metadata, _make_org, _make_team
from posthog.temporal.usage_report.activities import aggregate_and_chunk_org_reports
from posthog.temporal.usage_report.backtest import (
    BACKTESTED_METRICS,
    build_backtest_report,
    diff_backtest,
    extract_baseline_team_values,
    find_backtest_baseline,
    pick_baseline_manifest,
    run_backtest_candidate,
)
from posthog.temporal.usage_report.compiler import run_events_family
from posthog.temporal.usage_report.queries import QUERIES
from posthog.temporal.usage_report.storage import (
    backtest_prefix,
    date_prefix,
    delete_keys,
    list_keys,
    queries_key,
    read_json,
    write_json,
)
from posthog.temporal.usage_report.types import (
    AggregateInputs,
    BacktestCandidateInputs,
    BacktestDiffInputs,
    BacktestUsageReportsInputs,
    RunQueryToS3Result,
    WorkflowContext,
)

PERIOD_START = datetime(2026, 4, 6, 0, 0, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 4, 6, 23, 59, 59, 999999, tzinfo=UTC)

METRICS = ("event_count_in_period", "web_events_count_in_period")


# ---- pure diff semantics --------------------------------------------------


def test_report_is_clean_when_candidate_matches_baseline() -> None:
    baseline = {1: {"event_count_in_period": 5, "web_events_count_in_period": 0}}
    candidate = {"event_count_in_period": [[1, 5]], "web_events_count_in_period": []}

    report = build_backtest_report(baseline, candidate, METRICS)

    assert report["clean"] is True
    assert report["teams_compared"] == 1
    assert report["metrics"]["event_count_in_period"]["teams_differing"] == 0


def test_report_detects_drift_including_teams_the_candidate_missed() -> None:
    baseline = {
        1: {"event_count_in_period": 5, "web_events_count_in_period": 2},
        2: {"event_count_in_period": 7, "web_events_count_in_period": 0},
    }
    # Team 1 drifted by +3; team 2 is absent from the candidate entirely
    # (zero rows are dropped), which must read as candidate=0, not be skipped.
    candidate = {"event_count_in_period": [[1, 8]], "web_events_count_in_period": [[1, 2]]}

    report = build_backtest_report(baseline, candidate, METRICS)

    assert report["clean"] is False
    entry = report["metrics"]["event_count_in_period"]
    assert entry["teams_differing"] == 2
    assert entry["max_abs_delta"] == 7
    assert entry["baseline_total"] == 12
    assert entry["candidate_total"] == 8
    assert entry["samples"][0] == {"team_id": 2, "baseline": 7, "candidate": 0}
    assert report["metrics"]["web_events_count_in_period"]["teams_differing"] == 0


def test_candidate_only_teams_are_bucketed_and_do_not_dirty_the_report() -> None:
    baseline = {1: {"event_count_in_period": 5, "web_events_count_in_period": 0}}
    # Team 99 (an internal/demo team the baseline legitimately excludes)
    # must be surfaced, but not flip `clean`.
    candidate = {"event_count_in_period": [[1, 5], [99, 40]], "web_events_count_in_period": []}

    report = build_backtest_report(baseline, candidate, METRICS)

    assert report["clean"] is True
    assert report["candidate_only_teams"] == {"count": 1, "sample_team_ids": [99]}


def test_extract_baseline_tolerates_missing_fields_and_empty_teams() -> None:
    lines = [
        {"usage_report": {"teams": {"3": {"event_count_in_period": 9}}}},
        {"usage_report": {"teams": None}},
        {"usage_report": {}},
    ]

    teams = extract_baseline_team_values(lines, METRICS)

    assert teams == {3: {"event_count_in_period": 9, "web_events_count_in_period": 0}}


def test_pick_baseline_manifest_prefers_newest_then_key() -> None:
    older = datetime(2026, 4, 6, 4, 45, tzinfo=UTC)
    newer = datetime(2026, 4, 6, 7, 45, tzinfo=UTC)
    assert pick_baseline_manifest(["a", "b"], {"a": older, "b": newer}) == "b"
    # Same timestamp (S3 mtimes have 1s granularity): key breaks the tie,
    # so repeated discovery of the same S3 state picks the same run.
    assert pick_baseline_manifest(["a", "b"], {"a": newer, "b": newer}) == "b"


# ---- end-to-end against the real stack ------------------------------------


async def _insert_event(team: Any, event: str, at: datetime) -> None:
    await sync_to_async(create_event)(
        event_uuid=uuid.uuid4(),
        event=event,
        team=team,
        distinct_id="backtest",
        timestamp=at,
        properties={"$lib": "web"},
    )


async def _build_baseline(ctx: WorkflowContext, activity_environment: Any) -> None:
    """Produce real baseline chunks + manifest the way production does: the
    catalog scan's rows for the events family, empty payloads elsewhere,
    aggregated by the production activity.
    """
    values = await sync_to_async(run_events_family)(ctx.period_start, ctx.period_end)
    query_results = []
    for spec in QUERIES:
        payload: Any = values if spec.name == "events_family" else ({} if spec.output == "multi" else [])
        key = queries_key(ctx, spec.name)
        write_json(key, payload)
        query_results.append(RunQueryToS3Result(query_name=spec.name, s3_key=key, duration_ms=1))

    with patch(
        "posthog.temporal.usage_report.activities.get_instance_metadata",
        return_value=_instance_metadata(),
    ):
        await activity_environment.run(
            aggregate_and_chunk_org_reports,
            AggregateInputs(ctx=ctx, query_results=query_results),
        )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_backtest_is_clean_against_fresh_baseline_and_catches_one_extra_event(
    activity_environment: Any,
) -> None:
    org_a = await _make_org("Backtest A")
    org_b = await _make_org("Backtest B")
    team_a = await _make_team(org_a, "A")
    team_b = await _make_team(org_b, "B")

    date_str = f"bt-{uuid.uuid4().hex[:12]}"
    try:
        await _insert_event(team_a, "$pageview", PERIOD_START + timedelta(hours=2))
        await _insert_event(team_a, "checkout", PERIOD_START + timedelta(hours=3))
        await _insert_event(team_b, "$pageview", PERIOD_START + timedelta(hours=4))

        ctx = WorkflowContext(
            run_id=f"baseline-{uuid.uuid4().hex[:8]}",
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            date_str=date_str,
            organization_ids=[str(org_a.id), str(org_b.id)],
        )
        await _build_baseline(ctx, activity_environment)

        baseline = await activity_environment.run(find_backtest_baseline, BacktestUsageReportsInputs(date=date_str))
        assert baseline.run_id == ctx.run_id
        assert baseline.period_start == PERIOD_START

        candidate = await activity_environment.run(
            run_backtest_candidate, BacktestCandidateInputs(baseline=baseline, backtest_id="bt-1")
        )
        summary = await activity_environment.run(
            diff_backtest,
            BacktestDiffInputs(baseline=baseline, candidate=candidate, backtest_id="bt-1"),
        )

        assert summary.clean is True
        assert summary.metrics_compared == len(BACKTESTED_METRICS)
        assert summary.teams_compared == 2

        # One event arriving after the baseline ran is exactly the drift the
        # backtest exists to catch.
        await _insert_event(team_a, "$pageview", PERIOD_START + timedelta(hours=5))

        candidate2 = await activity_environment.run(
            run_backtest_candidate, BacktestCandidateInputs(baseline=baseline, backtest_id="bt-2")
        )
        summary2 = await activity_environment.run(
            diff_backtest,
            BacktestDiffInputs(baseline=baseline, candidate=candidate2, backtest_id="bt-2"),
        )

        assert summary2.clean is False
        report = read_json(summary2.report_key)
        entry = report["metrics"]["event_count_in_period"]
        assert entry["teams_differing"] == 1
        assert entry["samples"][0]["team_id"] == team_a.id
        assert entry["samples"][0]["candidate"] == entry["samples"][0]["baseline"] + 1
    finally:
        leftovers = list_keys(date_prefix(date_str)) + list_keys(backtest_prefix(date_str, "").rstrip("/"))
        delete_keys(leftovers)
