"""Backtest the metric catalog against a past production usage-report run.

Answers "does the current catalog produce the numbers we actually sent to
billing for date X?" — the safety gate for porting metric families into the
catalog, and after that, for any change to a metric's definition.

The baseline is the selected run's JSONL chunks: the exact per-org payload
billing consumed, whose field names are the stable metric names. That makes
the comparison independent of which query registry produced the run. The
candidate side re-runs the compiled catalog families for the baseline's
exact period, so only catalog metrics — all `kind="period"`, re-run safe by
definition — are diffed; snapshot metrics are excluded by construction.

Two caveats readers of a report should know:

* Late-arriving events and ClickHouse merges since the baseline ran can
  produce small legitimate deltas; a diff is a finding to explain, not
  automatically a bug.
* Baseline chunks only contain orgs that had billable usage, and exclude
  internal/demo teams. Teams the candidate scan finds beyond that set are
  reported separately (`candidate_only_teams`) and do not affect `clean` —
  eyeball them, since PostHog's own internal orgs are expected there.

Trigger manually (never scheduled) on the billing task queue:

    python manage.py execute_temporal_workflow backtest-usage-reports \
        '{"date": "2026-07-01"}' --task-queue billing-task-queue
"""

import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

import structlog
from temporalio import activity, common, workflow
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.usage_report.catalog import EVENTS_METRICS
from posthog.temporal.usage_report.compiler import run_events_family
from posthog.temporal.usage_report.storage import (
    backtest_prefix,
    date_prefix,
    last_modified,
    list_keys,
    read_json,
    read_jsonl_gzip,
    write_json,
)
from posthog.temporal.usage_report.types import (
    BacktestBaseline,
    BacktestCandidateInputs,
    BacktestCandidateResult,
    BacktestDiffInputs,
    BacktestSummary,
    BacktestUsageReportsInputs,
)

logger = structlog.get_logger(__name__)

BACKTESTED_METRICS: tuple[str, ...] = tuple(metric.name for metric in EVENTS_METRICS)

SAMPLE_LIMIT = 10
CANDIDATE_ONLY_SAMPLE_LIMIT = 20


def run_candidate_families(begin: datetime, end: datetime) -> dict[str, list[tuple[int, int]]]:
    """Every compiled catalog family for the period, merged into one
    metric-name → rows map. Extend as families are ported.
    """
    return run_events_family(begin, end)


def pick_baseline_manifest(manifest_keys: list[str], modified_by_key: dict[str, Any]) -> str:
    """The most recently written manifest; key as tiebreaker so re-listing
    the same S3 state always picks the same run.
    """
    return max(
        manifest_keys,
        key=lambda key: (modified_by_key[key].isoformat() if modified_by_key.get(key) else "", key),
    )


def extract_baseline_team_values(
    chunk_lines: Iterable[dict[str, Any]], metric_names: tuple[str, ...]
) -> dict[int, dict[str, int]]:
    """Per-team values for the backtested metrics, pulled from the `teams`
    breakdown of each org report in the baseline chunks.
    """
    teams: dict[int, dict[str, int]] = {}
    for line in chunk_lines:
        for team_id, counters in (line["usage_report"].get("teams") or {}).items():
            teams[int(team_id)] = {name: counters.get(name) or 0 for name in metric_names}
    return teams


def build_backtest_report(
    baseline_teams: dict[int, dict[str, int]],
    candidate_rows: dict[str, list[Any]],
    metric_names: tuple[str, ...],
) -> dict[str, Any]:
    """Diff candidate values against the baseline, per metric per team.

    Teams absent from the candidate rows count as 0 (the fused scan drops
    zero rows), so a baseline team the candidate misses shows up as a normal
    diff. Candidate teams absent from the baseline are bucketed separately —
    see the module docstring.
    """
    candidate_by_metric: dict[str, dict[int, int]] = {
        name: {int(team_id): value for team_id, value in candidate_rows.get(name, [])} for name in metric_names
    }
    candidate_team_ids = {team_id for rows in candidate_by_metric.values() for team_id in rows}
    candidate_only = sorted(candidate_team_ids - set(baseline_teams))

    metrics: dict[str, Any] = {}
    for name in metric_names:
        candidate = candidate_by_metric[name]
        baseline_total = 0
        candidate_total = 0
        diffs: list[dict[str, int]] = []
        for team_id, values in baseline_teams.items():
            baseline_value = values.get(name, 0)
            candidate_value = candidate.get(team_id, 0)
            baseline_total += baseline_value
            candidate_total += candidate_value
            if baseline_value != candidate_value:
                diffs.append({"team_id": team_id, "baseline": baseline_value, "candidate": candidate_value})
        diffs.sort(key=lambda diff: -abs(diff["candidate"] - diff["baseline"]))
        metrics[name] = {
            "teams_differing": len(diffs),
            "max_abs_delta": abs(diffs[0]["candidate"] - diffs[0]["baseline"]) if diffs else 0,
            "baseline_total": baseline_total,
            "candidate_total": candidate_total,
            "samples": diffs[:SAMPLE_LIMIT],
        }

    return {
        "metric_names": list(metric_names),
        "teams_compared": len(baseline_teams),
        "candidate_only_teams": {
            "count": len(candidate_only),
            "sample_team_ids": candidate_only[:CANDIDATE_ONLY_SAMPLE_LIMIT],
        },
        "metrics": metrics,
        "clean": all(entry["teams_differing"] == 0 for entry in metrics.values()),
    }


@activity.defn(name="usage-reports-backtest-find-baseline")
async def find_backtest_baseline(inputs: BacktestUsageReportsInputs) -> BacktestBaseline:
    """Locate the production run to compare against: the pinned run_id if
    given, else the most recently written manifest for the date.
    """
    async with Heartbeater():

        @database_sync_to_async_pool
        def find() -> BacktestBaseline:
            prefix = date_prefix(inputs.date)
            manifest_keys = [key for key in list_keys(prefix) if key.endswith("/manifest.json")]
            if inputs.baseline_run_id:
                manifest_keys = [key for key in manifest_keys if f"/{inputs.baseline_run_id}/" in key]
            if not manifest_keys:
                raise ApplicationError(
                    f"No usage-report baseline found under {prefix!r}"
                    + (f" for run_id {inputs.baseline_run_id!r}" if inputs.baseline_run_id else ""),
                    non_retryable=True,
                )

            chosen = pick_baseline_manifest(manifest_keys, {key: last_modified(key) for key in manifest_keys})
            manifest = read_json(chosen)
            return BacktestBaseline(
                date=inputs.date,
                run_id=manifest["run_id"],
                manifest_key=chosen,
                chunk_keys=manifest["chunk_keys"],
                period_start=manifest["period_start"],
                period_end=manifest["period_end"],
            )

        return await find()


@activity.defn(name="usage-reports-backtest-run-candidate")
async def run_backtest_candidate(inputs: BacktestCandidateInputs) -> BacktestCandidateResult:
    """Run the compiled catalog families for the baseline's period and
    persist the raw rows to S3 (by reference — the result can exceed
    Temporal's payload limit at production scale).
    """
    async with Heartbeater():

        @database_sync_to_async_pool
        def run() -> str:
            rows = run_candidate_families(inputs.baseline.period_start, inputs.baseline.period_end)
            key = f"{backtest_prefix(inputs.baseline.date, inputs.backtest_id)}/candidate.json"
            write_json(key, rows)
            return key

        return BacktestCandidateResult(candidate_key=await run(), metric_count=len(BACKTESTED_METRICS))


@activity.defn(name="usage-reports-backtest-diff")
async def diff_backtest(inputs: BacktestDiffInputs) -> BacktestSummary:
    """Stream the baseline chunks, diff against the candidate rows, and
    write the full report next to the candidate artifact.
    """
    async with Heartbeater():

        @database_sync_to_async_pool
        def diff() -> BacktestSummary:
            candidate_rows = read_json(inputs.candidate.candidate_key)
            baseline_teams = extract_baseline_team_values(
                (line for key in inputs.baseline.chunk_keys for line in read_jsonl_gzip(key)),
                BACKTESTED_METRICS,
            )
            report = build_backtest_report(baseline_teams, candidate_rows, BACKTESTED_METRICS)
            report.update(
                date=inputs.baseline.date,
                baseline_run_id=inputs.baseline.run_id,
                backtest_id=inputs.backtest_id,
                period_start=inputs.baseline.period_start.isoformat(),
                period_end=inputs.baseline.period_end.isoformat(),
            )
            report_key = f"{backtest_prefix(inputs.baseline.date, inputs.backtest_id)}/report.json"
            write_json(report_key, report)
            return BacktestSummary(
                report_key=report_key,
                clean=report["clean"],
                metrics_compared=len(BACKTESTED_METRICS),
                metrics_with_diffs=sum(1 for entry in report["metrics"].values() if entry["teams_differing"] > 0),
                teams_compared=report["teams_compared"],
                candidate_only_teams=report["candidate_only_teams"]["count"],
            )

        return await diff()


@workflow.defn(name="backtest-usage-reports")
class BacktestUsageReportsWorkflow(PostHogWorkflow):
    """Manually triggered; never scheduled. Compares the current catalog
    against what a past production run actually reported.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BacktestUsageReportsInputs:
        loaded = json.loads(inputs[0])
        return BacktestUsageReportsInputs(**loaded)

    @workflow.run
    async def run(self, inputs: BacktestUsageReportsInputs) -> dict:
        baseline = await workflow.execute_activity(
            find_backtest_baseline,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
            heartbeat_timeout=timedelta(minutes=1),
        )

        backtest_id = workflow.info().run_id
        candidate = await workflow.execute_activity(
            run_backtest_candidate,
            BacktestCandidateInputs(baseline=baseline, backtest_id=backtest_id),
            start_to_close_timeout=timedelta(minutes=60),
            retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
            heartbeat_timeout=timedelta(minutes=5),
        )

        summary = await workflow.execute_activity(
            diff_backtest,
            BacktestDiffInputs(baseline=baseline, candidate=candidate, backtest_id=backtest_id),
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=30)),
            heartbeat_timeout=timedelta(minutes=5),
        )

        workflow.logger.info(
            "Usage reports backtest complete",
            extra={
                "date": inputs.date,
                "baseline_run_id": baseline.run_id,
                "clean": summary.clean,
                "metrics_with_diffs": summary.metrics_with_diffs,
                "candidate_only_teams": summary.candidate_only_teams,
                "report_key": summary.report_key,
            },
        )
        return summary.model_dump()
