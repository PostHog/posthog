"""Compare separate and batched HogQL queries against an existing local PostHog database."""

import json
import argparse
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast

import django
from django.conf import settings

from posthog.hogql import ast
from posthog.hogql.batch import BatchPlan, BatchQueryResult, CountBatchPlanner
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.multi_query import (
    MultiQueryPlanner,
    SharingPlan,
    SharingQuery,
    execute_group,
    is_query_sharing_enabled,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.hogql import HogQLPrinter
from posthog.hogql.query_stats import query_stats_scope
from posthog.hogql.sharing_rules import CountFusionRule, SameAggregationTopNRule
from posthog.hogql.visitor import CloningVisitor, clone_expr

from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models.team import Team

DEMO_QUERIES = {
    "purchases": """SELECT toDate(timestamp) AS day, count() AS purchases FROM events
        WHERE event = 'purchase' AND timestamp >= '2026-01-01' AND timestamp < '2026-01-08'
        GROUP BY toDate(timestamp) ORDER BY day""",
    "chrome_purchases": """SELECT toDate(timestamp) AS day, count() AS chrome_purchases FROM events
        WHERE event = 'purchase' AND timestamp >= '2026-01-01' AND timestamp < '2026-01-08'
        AND properties.browser = 'Chrome' GROUP BY toDate(timestamp) ORDER BY day""",
    "missing_browser": """SELECT toDate(timestamp) AS day, count() AS missing_browser FROM events
        WHERE event = 'purchase' AND timestamp >= '2026-01-01' AND timestamp < '2026-01-08'
        AND properties.browser = 'NeverPresent' GROUP BY toDate(timestamp) ORDER BY day""",
    "unique_people": """SELECT uniqExact(distinct_id) AS people FROM events
        WHERE event = 'purchase' AND timestamp >= '2026-01-01' AND timestamp < '2026-01-08'""",
}

DATABASE_QUERIES = {
    "all_events": "SELECT count() AS n FROM events WHERE timestamp >= '2020-01-01' AND timestamp < '2100-01-01'",
    "chrome_events": """SELECT count() AS n FROM events
        WHERE timestamp >= '2020-01-01' AND timestamp < '2100-01-01' AND properties.$browser = 'Chrome'""",
    "recent_events": "SELECT timestamp, event, properties.$browser AS browser FROM events ORDER BY timestamp DESC LIMIT 10",
}

TOP_N_QUERIES = {
    "most_calls": """SELECT properties.tool AS tool, count() AS calls, uniqExact(distinct_id) AS people
        FROM events GROUP BY tool ORDER BY calls DESC, tool LIMIT 5""",
    "most_people": """SELECT properties.tool AS tool, count() AS calls, uniqExact(distinct_id) AS people
        FROM events GROUP BY tool ORDER BY people DESC, tool LIMIT 5""",
}


def print_query(query: ast.SelectQuery | ast.SelectSetQuery) -> str:
    return HogQLPrinter(context=HogQLContext(enable_select_queries=True, limit_top_select=False), pretty=True).visit(
        query
    )


class _SyntheticEvents(CloningVisitor):
    def __init__(self, rows: int) -> None:
        super().__init__()
        self.source = parse_select(
            """SELECT
                addSeconds(toDateTime('2026-01-01', 'UTC'), (number % 7) * 86400) AS timestamp,
                if(number % 2 = 0, 'purchase', 'signup') AS event,
                toString(if(number % 4 = 0, number % 5, number % 1000)) AS distinct_id,
                map('browser', if(number % 7 < 3, 'Chrome', 'Firefox'),
                    'tool', if(number % 4 = 0, 'frequent', concat('tool_', toString(number % 31)))) AS properties
            FROM (SELECT number FROM system.numbers LIMIT {rows})""",
            placeholders={"rows": ast.Constant(value=rows)},
        )

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        if isinstance(node.table, ast.SelectQuery | ast.SelectSetQuery):
            return super().visit_join_expr(node)
        if not isinstance(node.table, ast.Field) or node.table.chain != ["events"] or node.table_args:
            raise ValueError("The playground only reads its synthetic events source")
        replacement = clone_expr(node)
        replacement.table = clone_expr(self.source)
        replacement.alias = node.alias or "events"
        if node.next_join:
            replacement.next_join = self.visit(node.next_join)
        return replacement

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if len(node.chain) == 2 and node.chain[0] == "properties":
            return ast.ArrayAccess(array=ast.Field(chain=["properties"]), property=ast.Constant(value=node.chain[1]))
        return super().visit_field(node)


@frozen
class ExecutionStatistics:
    query_count: int
    rows_read: int
    elapsed: float
    bytes_read: int | None = None


class DatabaseClickHouse:
    def __init__(self, *, team: "Team", timeout: int, max_result_rows: int, show_sql: bool = False) -> None:
        self.team = team
        self.timeout = timeout
        self.max_result_rows = max_result_rows
        self.show_sql = show_sql
        self.statistics: list[ExecutionStatistics] = []

    def prepare(self, query_id: str, sql: str) -> SharingQuery:
        from posthog.hogql.query import HogQLQueryExecutor  # noqa: PLC0415 -- requires django.setup()

        return HogQLQueryExecutor(query=sql, team=self.team).prepare_for_sharing(
            query_id=query_id, scope_key="local-demo"
        )

    def run(self, query: ast.SelectQuery | ast.SelectSetQuery) -> BatchQueryResult:
        # Django-backed imports must wait until the CLI has initialized the app registry.
        from posthog.hogql.query import HogQLQueryExecutor  # noqa: PLC0415

        from posthog.clickhouse.client.execute import sync_execute  # noqa: PLC0415
        from posthog.clickhouse.query_tagging import Feature, Product, tags_context  # noqa: PLC0415

        with tags_context(product=Product.INTERNAL, feature=Feature.DEBUG_QUERY), query_stats_scope() as stats:
            executor = HogQLQueryExecutor(
                query=clone_expr(query),
                team=self.team,
                settings=HogQLGlobalSettings(
                    max_execution_time=self.timeout,
                    timeout_overflow_mode="throw",
                    read_overflow_mode="throw",
                    max_memory_usage=536_870_912,
                ),
            )
            # Embedding compilation preserves explicit limits without inserting a preview limit.
            compiled = executor.generate_clickhouse_subquery_sql()
            settings = dict(compiled.settings)
            settings.update(
                max_execution_time=self.timeout,
                timeout_overflow_mode="throw",
                read_overflow_mode="throw",
                max_memory_usage=536_870_912,
                max_result_rows=self.max_result_rows,
                max_result_bytes=134_217_728,
                result_overflow_mode="throw",
            )
            if self.show_sql:
                print(compiled.sql)  # noqa: T201
            rows, columns = sync_execute(
                compiled.sql,
                compiled.context.values,
                settings=settings,
                with_column_types=True,
                team_id=self.team.pk,
                readonly=True,
                workload=compiled.context.workload or Workload.DEFAULT,
                external_tables=list(compiled.context.external_tables.values()) or None,
            )
        self.statistics.append(
            ExecutionStatistics(
                query_count=stats.query_count, rows_read=stats.rows_read, elapsed=stats.duration_ms / 1000
            )
        )
        return BatchQueryResult(
            columns=tuple(executor.print_columns),
            types=tuple(column_type for _, column_type in columns),
            rows=tuple(tuple(row) for row in rows),
        )


class SyntheticClickHouse:
    def __init__(self, *, container: str, rows: int) -> None:
        self.container = container
        self.rows = rows
        self.statistics: list[ExecutionStatistics] = []

    def run(self, query: ast.SelectQuery | ast.SelectSetQuery) -> BatchQueryResult:
        synthetic = _SyntheticEvents(self.rows).visit(query)
        sql = print_query(synthetic)
        process = subprocess.run(
            [
                "docker",
                "exec",
                self.container,
                "clickhouse-client",
                "--readonly",
                "1",
                "--max_execution_time",
                "15",
                "--max_memory_usage",
                "268435456",
                "--output_format_json_quote_64bit_integers",
                "0",
                "--format",
                "JSONCompact",
                "--query",
                sql,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or f"clickhouse-client exited with {process.returncode}")
        response = json.loads(process.stdout)
        stats = response["statistics"]
        self.statistics.append(
            ExecutionStatistics(
                query_count=1,
                rows_read=stats["rows_read"],
                elapsed=stats["elapsed"],
                bytes_read=stats["bytes_read"],
            )
        )
        return BatchQueryResult(
            columns=tuple(column["name"] for column in response["meta"]),
            types=tuple(column["type"] for column in response["meta"]),
            rows=tuple(tuple(row) for row in response["data"]),
        )


def compare_results(sql: str, baseline: BatchQueryResult, combined: BatchQueryResult) -> bool:
    if baseline.columns != combined.columns or baseline.types != combined.types:
        return False
    query = parse_select(sql)
    if isinstance(query, ast.SelectQuery) and query.order_by:
        return baseline.rows == combined.rows
    return Counter(map(repr, baseline.rows)) == Counter(map(repr, combined.rows))


def describe_plan(plan: BatchPlan) -> None:
    for step in plan.steps:
        print(f"\n[{', '.join(step.query_ids)}] {step.reason}")  # noqa: T201
        print(print_query(step.query))  # noqa: T201


def execute_plan(plan: BatchPlan, runner: DatabaseClickHouse | SyntheticClickHouse) -> dict[str, BatchQueryResult]:
    results: dict[str, BatchQueryResult] = {}
    for step in plan.steps:
        try:
            results.update(step.split(runner.run(clone_expr(step.query))))
        except Exception as error:
            raise RuntimeError(f"Query [{', '.join(step.query_ids)}] failed: {error}") from error
    return results


def execute_sharing_plan(
    plan: SharingPlan, runner: DatabaseClickHouse | SyntheticClickHouse
) -> dict[str, BatchQueryResult]:
    results: dict[str, BatchQueryResult] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(execute_group, group, runner.run): group.query_ids for group in plan.groups}
        for future in as_completed(futures):
            try:
                results.update(future.result())
            except Exception as error:
                raise RuntimeError(f"Query [{', '.join(futures[future])}] failed: {error}") from error
    return results


def describe_sharing_plan(plan: SharingPlan, query_count: int) -> None:
    print(f"{query_count} input queries → {len(plan.groups)} executions")  # noqa: T201
    for group in plan.groups:
        print(f"\n[{', '.join(group.query_ids)}] {group.rule}\n{print_query(group.query)}")  # noqa: T201
    for rejection in plan.rejections:
        print(f"{rejection.query_id}: {rejection.rule}: {rejection.reason}")  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, help="JSON object mapping query IDs to HogQL strings")
    parser.add_argument("--sharing", action="store_true", help="Try extensible sharing rules; defaults to a top-N pair")
    parser.add_argument("--team-id", type=int, help="Existing PostHog project ID (required for database execution)")
    parser.add_argument(
        "--synthetic", action="store_true", help="Use generated events instead of the existing database"
    )
    parser.add_argument("--timeout", type=int, default=15, help="Database query timeout in seconds")
    parser.add_argument(
        "--max-result-rows", type=int, default=1_000_000, help="Fail above this row count; never truncate"
    )
    parser.add_argument("--show-sql", action="store_true", help="Print compiled ClickHouse SQL for database execution")
    parser.add_argument("--rows", type=int, default=100_000, help="Synthetic rows, from 0 to 10000000")
    parser.add_argument("--container", default="posthog-clickhouse-1", help="Local Docker ClickHouse container")
    parser.add_argument("--plan-only", action="store_true", help="Print the plan without connecting to ClickHouse")
    parser.add_argument("--max-group-size", type=int, default=8)
    args = parser.parse_args()
    if not 0 <= args.rows <= 10_000_000:
        parser.error("--rows must be between 0 and 10000000")
    if args.timeout <= 0 or args.max_result_rows <= 0:
        parser.error("--timeout and --max-result-rows must be positive")
    if not args.synthetic and not args.plan_only and args.team_id is None:
        parser.error("--team-id is required for the existing database; use --synthetic for generated data")
    queries = (
        json.loads(args.queries.read_text())
        if args.queries
        else (TOP_N_QUERIES if args.sharing else DEMO_QUERIES if args.synthetic else DATABASE_QUERIES)
    )
    if (
        not isinstance(queries, dict)
        or not queries
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in queries.items())
    ):
        parser.error("--queries must contain a nonempty JSON object of query IDs to SQL strings")
    queries = cast(dict[str, str], queries)
    planner = CountBatchPlanner(max_group_size=args.max_group_size)
    separate_plan = planner.plan(queries, combine=False)
    combined_plan = planner.plan(queries, combine=args.synthetic or args.plan_only)
    sharing_planner = MultiQueryPlanner([SameAggregationTopNRule(), CountFusionRule()])
    sharing_inputs = (
        [
            SharingQuery(
                query_id=key,
                query=parse_select(sql),
                context_key="local-demo",
                sharing_enabled=args.synthetic or args.plan_only,
            )
            for key, sql in queries.items()
        ]
        if args.sharing
        else []
    )
    separate_sharing = sharing_planner.plan(sharing_inputs, combine=False)
    combined_sharing = sharing_planner.plan(sharing_inputs)
    if args.sharing:
        if args.synthetic or args.plan_only:
            describe_sharing_plan(combined_sharing, len(queries))
    elif args.synthetic or args.plan_only:
        print(f"{len(queries)} input queries → {len(combined_plan.steps)} executions")  # noqa: T201
        describe_plan(combined_plan)
    if args.plan_only:
        return

    separate_runner: DatabaseClickHouse | SyntheticClickHouse
    combined_runner: DatabaseClickHouse | SyntheticClickHouse
    if args.synthetic:
        separate_runner = SyntheticClickHouse(container=args.container, rows=args.rows)
        combined_runner = SyntheticClickHouse(container=args.container, rows=args.rows)
    else:
        if not settings.DEBUG:
            parser.error("This playground requires DEBUG=1 and a local development database")
        django.setup()
        from posthog.models.team import Team  # noqa: PLC0415 -- requires django.setup()

        try:
            team = Team.objects.get(pk=args.team_id)
        except Team.DoesNotExist:
            parser.error(f"Project {args.team_id} does not exist in the configured Postgres database")
        print(f"\nDatabase: {settings.CLICKHOUSE_HOST}/{settings.CLICKHOUSE_DATABASE}, project {team.pk}")  # noqa: T201
        separate_runner = DatabaseClickHouse(
            team=team, timeout=args.timeout, max_result_rows=args.max_result_rows, show_sql=args.show_sql
        )
        combined_runner = DatabaseClickHouse(
            team=team, timeout=args.timeout, max_result_rows=args.max_result_rows, show_sql=args.show_sql
        )
        if args.sharing:
            sharing_inputs = [combined_runner.prepare(key, sql) for key, sql in queries.items()]
            separate_sharing = sharing_planner.plan(sharing_inputs, combine=False)
            combined_sharing = sharing_planner.plan(sharing_inputs)
            describe_sharing_plan(combined_sharing, len(queries))
        else:
            combined_plan = planner.plan(queries, combine=is_query_sharing_enabled(team))
            print(f"{len(queries)} input queries → {len(combined_plan.steps)} executions")  # noqa: T201
            describe_plan(combined_plan)
    baseline_start = perf_counter()
    baseline = (
        execute_sharing_plan(separate_sharing, separate_runner)
        if args.sharing
        else execute_plan(separate_plan, separate_runner)
    )
    baseline_wall = perf_counter() - baseline_start
    combined_start = perf_counter()
    combined = (
        execute_sharing_plan(combined_sharing, combined_runner)
        if args.sharing
        else execute_plan(combined_plan, combined_runner)
    )
    combined_wall = perf_counter() - combined_start
    matches = {
        query_id: compare_results(sql, baseline[query_id], combined[query_id]) for query_id, sql in queries.items()
    }
    for query_id, result in combined.items():
        print(f"\n{query_id}: {'MATCH' if matches[query_id] else 'MISMATCH'}")  # noqa: T201
        print(f"{len(result.rows):,} rows (showing up to 10)", result.columns, result.rows[:10])  # noqa: T201
    for label, runner in (("separate", separate_runner), ("combined", combined_runner)):
        print(  # noqa: T201
            f"\n{label}: {sum(stat.query_count for stat in runner.statistics)} executions, "
            f"{sum(stat.rows_read for stat in runner.statistics):,} rows read, "
            f"{sum(stat.elapsed for stat in runner.statistics):.4f}s summed server time"
        )
        if all(stat.bytes_read is not None for stat in runner.statistics):
            print(f"{sum(stat.bytes_read or 0 for stat in runner.statistics):,} bytes read")  # noqa: T201
    print(f"\nWall time: separate {baseline_wall:.4f}s; combined {combined_wall:.4f}s")  # noqa: T201
    if args.synthetic:
        print("\nSynthetic numbers source: these measurements demonstrate sharing, not production savings.")  # noqa: T201
    else:
        print("\nLive database: concurrent ingestion, volatile functions, and unordered LIMITs can cause mismatches.")  # noqa: T201
    if not all(matches.values()):
        raise SystemExit("Separate and combined results differ")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(str(error)) from None
