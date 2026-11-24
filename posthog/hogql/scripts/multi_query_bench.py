"""Benchmark the multi-query planner on the named batches in `multi_query_corpus`.

For each batch this prepares every query the way HogQL execution does, plans it with every sharing rule, runs the
queries once separately and once as planned, and reports executions, rows read, ClickHouse time and whether the
results match.

Two data sources:

- `--synthetic` seeds deterministic events into the pytest test databases and runs there. It never touches the
  development databases.
- `--team-id` reads an existing project in the local development databases. The Postgres schema must match this
  checkout, so run the stack's migrations first; this script only reads.
"""

import os
import sys
import argparse
import subprocess
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import field, replace
from time import perf_counter
from typing import TYPE_CHECKING

import django

from posthog.hogql import ast
from posthog.hogql.batch import BatchQueryResult
from posthog.hogql.multi_query import MultiQueryPlanner, RuleRejection, SharingPlan, SharingQuery, execute_group
from posthog.hogql.scripts.batch_demo import DatabaseClickHouse, ExecutionStatistics
from posthog.hogql.scripts.multi_query_corpus import CorpusBatch, build_corpus, prepare_batch
from posthog.hogql.sharing_rules import CountFusionRule, SameAggregationTopNRule
from posthog.hogql.visitor import clone_expr

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models.team import Team

SYNTHETIC_ROWS_VARIABLE = "MULTI_QUERY_BENCH_ROWS"
SYNTHETIC_BATCHES_VARIABLE = "MULTI_QUERY_BENCH_BATCHES"
SYNTHETIC_BENCHMARK = "posthog/hogql/scripts/multi_query_bench_synthetic.py::SyntheticBenchmark::test_report"


def sharing_planner() -> MultiQueryPlanner:
    return MultiQueryPlanner([SameAggregationTopNRule(), CountFusionRule()])


def lifted_limit_rejections(prepared: Sequence[SharingQuery]) -> tuple[RuleRejection, ...]:
    """Count fusion's reasons for queries with an explicit LIMIT, once the LIMIT is removed.

    Dashboards drop such a LIMIT when the unlimited query would fuse with an identical partner, so this is the
    reason that decides a dashboard tile.
    """
    rejections: list[RuleRejection] = []
    for query in prepared:
        node = query.query
        if not isinstance(node, ast.SelectQuery) or node.limit is None:
            continue
        unlimited = clone_expr(node)
        unlimited.limit = None
        unlimited.offset = None
        candidate = replace(query, query=unlimited, sharing_enabled=True)
        plan = MultiQueryPlanner([CountFusionRule()]).plan(
            [candidate, replace(candidate, query_id=f"{query.query_id}-probe")]
        )
        rejections.extend(rejection for rejection in plan.rejections if rejection.query_id == query.query_id)
    return tuple(rejections)


@frozen
class RunTotals:
    executions: int
    rows_read: int
    server_seconds: float
    wall_seconds: float


@frozen
class BatchReport:
    name: str
    query_count: int
    plan: SharingPlan
    lifted_rejections: tuple[RuleRejection, ...]
    separate: RunTotals
    combined: RunTotals
    mismatches: tuple[str, ...]
    results: dict[str, BatchQueryResult] = field(hash=False, repr=False)


def results_match(
    query: ast.SelectQuery | ast.SelectSetQuery, separate: BatchQueryResult, combined: BatchQueryResult
) -> bool:
    if separate.columns != combined.columns or separate.types != combined.types:
        return False
    if isinstance(query, ast.SelectQuery) and query.order_by:
        return separate.rows == combined.rows
    return Counter(map(repr, separate.rows)) == Counter(map(repr, combined.rows))


def _execute(
    plan: SharingPlan, run_query: Callable[[ast.SelectQuery | ast.SelectSetQuery], BatchQueryResult]
) -> tuple[dict[str, BatchQueryResult], float]:
    # Groups run one at a time: test databases keep their transaction invisible to other threads.
    results: dict[str, BatchQueryResult] = {}
    started = perf_counter()
    for group in plan.groups:
        try:
            results.update(execute_group(group, run_query))
        except Exception as error:
            raise RuntimeError(f"Query [{', '.join(group.query_ids)}] failed: {error}") from error
    return results, perf_counter() - started


def _totals(statistics: list[ExecutionStatistics], wall_seconds: float) -> RunTotals:
    return RunTotals(
        executions=sum(stat.query_count for stat in statistics),
        rows_read=sum(stat.rows_read for stat in statistics),
        server_seconds=sum(stat.elapsed for stat in statistics),
        wall_seconds=wall_seconds,
    )


def run_batch(
    batch: CorpusBatch, team: "Team", *, force_sharing: bool = True, timeout: int = 30, max_result_rows: int = 1_000_000
) -> BatchReport:
    prepared = prepare_batch(batch, team, scope_key=f"multi-query-bench:{batch.name}", force_sharing=force_sharing)
    planner = sharing_planner()
    separate_plan = planner.plan(prepared, combine=False)
    combined_plan = planner.plan(prepared)
    separate_runner = DatabaseClickHouse(team=team, timeout=timeout, max_result_rows=max_result_rows)
    combined_runner = DatabaseClickHouse(team=team, timeout=timeout, max_result_rows=max_result_rows)
    separate, separate_wall = _execute(separate_plan, separate_runner.run)
    combined, combined_wall = _execute(combined_plan, combined_runner.run)
    return BatchReport(
        name=batch.name,
        query_count=len(prepared),
        plan=combined_plan,
        lifted_rejections=lifted_limit_rejections(prepared),
        separate=_totals(separate_runner.statistics, separate_wall),
        combined=_totals(combined_runner.statistics, combined_wall),
        mismatches=tuple(
            query.query_id
            for query in prepared
            if not results_match(query.query, separate[query.query_id], combined[query.query_id])
        ),
        results=combined,
    )


def format_reports(reports: Sequence[BatchReport]) -> str:
    header = f"{'batch':<22} {'queries':>7} {'executions':>11} {'rows read':>19} {'CH ms':>15} {'wall ms':>15}  results"
    lines = [header, "-" * len(header)]
    for report in reports:
        s, c = report.separate, report.combined
        lines.append(
            f"{report.name:<22} {report.query_count:>7} {f'{s.executions} -> {c.executions}':>11} "
            f"{f'{s.rows_read:,} -> {c.rows_read:,}':>19} "
            f"{f'{s.server_seconds * 1000:.0f} -> {c.server_seconds * 1000:.0f}':>15} "
            f"{f'{s.wall_seconds * 1000:.0f} -> {c.wall_seconds * 1000:.0f}':>15}  "
            f"{'match' if not report.mismatches else 'MISMATCH ' + ', '.join(report.mismatches)}"
        )
    for report in reports:
        lines.append(f"\n{report.name}")
        for group in report.plan.groups:
            lines.append(f"  {group.rule}: {', '.join(group.query_ids)}")
        for rejection in report.plan.rejections:
            lines.append(f"  - {rejection.query_id} not shared by {rejection.rule}: {rejection.reason}")
        for rejection in report.lifted_rejections:
            lines.append(f"  - {rejection.query_id} without its LIMIT, {rejection.rule}: {rejection.reason}")
    return "\n".join(lines)


def run_corpus(team: "Team", *, force_sharing: bool = True, batches: Sequence[str] = ()) -> list[BatchReport]:
    selected = [batch for batch in build_corpus() if not batches or batch.name in batches]
    return [run_batch(batch, team, force_sharing=force_sharing) for batch in selected]


def _run_development(team_id: int, *, force_sharing: bool, batches: Sequence[str]) -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    django.setup()
    from django.conf import settings  # noqa: PLC0415

    from posthog.models.team import Team  # noqa: PLC0415 -- requires django.setup()

    if not settings.DEBUG or settings.TEST:
        raise SystemExit("Development mode requires DEBUG=1 and a local development database")
    team = Team.objects.get(pk=team_id)
    print(f"Database: {settings.CLICKHOUSE_HOST}/{settings.CLICKHOUSE_DATABASE}, project {team.pk}\n")  # noqa: T201
    reports = run_corpus(team, force_sharing=force_sharing, batches=batches)
    print(format_reports(reports))  # noqa: T201
    print("\nLive data: concurrent ingestion can make separate and combined results differ.")  # noqa: T201
    return 1 if any(report.mismatches for report in reports) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic", action="store_true", help="Seed events into the pytest test databases")
    source.add_argument("--team-id", type=int, help="Existing project in the local development databases")
    parser.add_argument("--rows", type=int, default=60_000, help="Synthetic events to seed, from 1 to 1000000")
    parser.add_argument("--batch", action="append", default=[], help="Only run this batch; repeatable")
    parser.add_argument(
        "--respect-flag",
        action="store_true",
        help="Development mode only: share only where the team's query sharing flag is on",
    )
    args = parser.parse_args()
    names = {batch.name for batch in build_corpus()}
    if unknown := set(args.batch) - names:
        parser.error(f"Unknown batch: {', '.join(sorted(unknown))}. Choose from {', '.join(sorted(names))}")
    if args.synthetic:
        if not 1 <= args.rows <= 1_000_000:
            parser.error("--rows must be between 1 and 1000000")
        environment = {**os.environ, SYNTHETIC_ROWS_VARIABLE: str(args.rows)}
        if args.batch:
            environment[SYNTHETIC_BATCHES_VARIABLE] = ",".join(args.batch)
        command = [sys.executable, "-m", "pytest", SYNTHETIC_BENCHMARK, "-s", "-q", "-p", "no:randomly"]
        raise SystemExit(subprocess.run(command, env=environment, check=False).returncode)
    raise SystemExit(_run_development(args.team_id, force_sharing=not args.respect_flag, batches=args.batch))


if __name__ == "__main__":
    main()
