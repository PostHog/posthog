"""
Management command to search query_log_archive for a specific query.

The challenge: you can't do WHERE lc_query__query = '<paste>' because of indentation,
whitespace, and literal value differences between what you pasted and what was stored.

The solution: normalizeQuery() on both sides. ClickHouse's normalizeQuery() strips all
literal values ('pageview' → ?, 12345 → ?) and normalizes whitespace, so two queries that
differ only in formatting or constants hash to the same value.

Two modes:

  HogQL (default):
    Searches lc_query__query — the original HogQL the user wrote, stored verbatim in
    log_comment before any compilation or modifier application. Compares
    cityHash64(normalizeQuery(lc_query__query)) = cityHash64(normalizeQuery(<your input>)).
    Modifier-agnostic: finds the query regardless of what personsOnEventsMode, inCohortVia,
    etc. were active. Requires a column scan within the team+date partition.

  --clickhouse-sql:
    For when you have a raw ClickHouse SQL snippet (e.g. from a slow query report or CH
    system.processes). Computes cityHash64(normalizeQuery(<sql>)) via a pure ClickHouse
    expression (zero data scanned), then searches the indexed normalized_query_hash column.

Results always include lc_modifiers so you can see exactly what HogQL modifiers were
added before execution (personsOnEventsMode, inCohortVia, etc.).

Usage examples:

  # Find all executions of a HogQL query for a team
  python manage.py search_query_log --team-id 1234 \\
    --query "SELECT count() FROM events WHERE event = 'pageview'"

  # Find a raw ClickHouse SQL query (e.g. from a slow query report)
  python manage.py search_query_log --clickhouse-sql \\
    --query "SELECT count() FROM posthog_db.sharded_events WHERE ..."

  # Search without team scope (slow on large clusters, adds a warning)
  python manage.py search_query_log --query "SELECT ..."

  # Go back 30 days, return up to 50 results
  python manage.py search_query_log --team-id 1234 --days 30 --limit 50 \\
    --query "SELECT ..."
"""

import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Search query_log_archive for a specific query using normalizeQuery() matching"

    def add_arguments(self, parser):
        parser.add_argument(
            "--query",
            required=True,
            help="Query to search for (HogQL by default, or ClickHouse SQL with --clickhouse-sql).",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            dest="team_id",
            help="Restrict search to a specific team. Without it, scans all teams (slow).",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="How many days back to search (default: 7).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Max results to return (default: 20).",
        )
        parser.add_argument(
            "--clickhouse-sql",
            action="store_true",
            dest="clickhouse_sql",
            help=(
                "Treat --query as raw ClickHouse SQL rather than HogQL. "
                "Uses normalized_query_hash for a fast indexed lookup instead of scanning lc_query__query."
            ),
        )

    def handle(self, *args, **options):
        query_input: str = options["query"]
        team_id: int | None = options.get("team_id")
        days: int = options["days"]
        limit: int = options["limit"]
        clickhouse_sql: bool = options["clickhouse_sql"]

        if not team_id:
            self.stderr.write(
                "Warning: no --team-id specified. Searching across all teams may be slow on large clusters.\n"
            )

        if clickhouse_sql:
            self._search_by_ch_hash(query_input, team_id, days, limit)
        else:
            self._search_by_hogql(query_input, team_id, days, limit)

    def _search_by_hogql(self, hogql_query: str, team_id: int | None, days: int, limit: int) -> None:
        """
        Search lc_query__query using normalizeQuery() on both sides.

        lc_query__query stores the original HogQL the user wrote, before compilation or modifier
        application. normalizeQuery() handles whitespace and literal differences, so the query you
        paste doesn't need to match formatting exactly.
        """
        from posthog.clickhouse.client.execute import sync_execute

        conditions = [
            "lc_query__query != ''",
            "is_initial_query = 1",
            "cityHash64(normalizeQuery(lc_query__query)) = cityHash64(normalizeQuery(%(query)s))",
            "event_date >= today() - %(days)s",
        ]
        params: dict = {"query": hogql_query, "days": days, "limit": limit}

        if team_id:
            conditions.append("team_id = %(team_id)s")
            params["team_id"] = team_id

        where = " AND ".join(conditions)

        sql = f"""
            SELECT
                query_id,
                initial_query_id,
                query_start_time,
                query_duration_ms,
                read_rows,
                read_bytes,
                result_rows,
                type,
                exception_code,
                exception,
                lc_query__kind,
                lc_query__query,
                lc_modifiers,
                lc_product,
                lc_workload,
                team_id
            FROM query_log_archive
            WHERE {where}
            ORDER BY query_start_time DESC
            LIMIT %(limit)s
        """

        try:
            rows = sync_execute(sql, params)
        except Exception as e:
            raise CommandError(f"Search query failed: {e}") from e

        self._print_results(rows)

    def _search_by_ch_hash(self, ch_sql: str, team_id: int | None, days: int, limit: int) -> None:
        """
        Compute the normalized_query_hash for the given ClickHouse SQL, then search by it.

        The hash computation is a pure ClickHouse expression — no table scan, no data access.
        The normalized_query_hash column in query_log_archive is populated by ClickHouse from
        system.query_log using the same cityHash64(normalizeQuery(query)) formula.
        """
        from posthog.clickhouse.client.execute import sync_execute

        try:
            result = sync_execute(
                "SELECT cityHash64(normalizeQuery(%(query)s)) AS hash",
                {"query": ch_sql},
            )
            normalized_hash = result[0][0]
        except Exception as e:
            raise CommandError(f"Failed to compute normalized hash via ClickHouse: {e}") from e

        self.stdout.write(f"\nnormalized_query_hash = {normalized_hash}\n")

        conditions = [
            "normalized_query_hash = %(hash)s",
            "event_date >= today() - %(days)s",
        ]
        params: dict = {"hash": normalized_hash, "days": days, "limit": limit}

        if team_id:
            conditions.append("team_id = %(team_id)s")
            params["team_id"] = team_id

        where = " AND ".join(conditions)

        sql = f"""
            SELECT
                query_id,
                initial_query_id,
                query_start_time,
                query_duration_ms,
                read_rows,
                read_bytes,
                result_rows,
                type,
                exception_code,
                exception,
                lc_query__kind,
                lc_query__query,
                lc_modifiers,
                lc_product,
                lc_workload,
                team_id
            FROM query_log_archive
            WHERE {where}
            ORDER BY query_start_time DESC
            LIMIT %(limit)s
        """

        try:
            rows = sync_execute(sql, params)
        except Exception as e:
            raise CommandError(f"Search query failed: {e}") from e

        self._print_results(rows)

    def _print_results(self, rows: list) -> None:
        columns = [
            "query_id",
            "initial_query_id",
            "query_start_time",
            "query_duration_ms",
            "read_rows",
            "read_bytes",
            "result_rows",
            "type",
            "exception_code",
            "exception",
            "lc_query__kind",
            "lc_query__query",
            "lc_modifiers",
            "lc_product",
            "lc_workload",
            "team_id",
        ]

        if not rows:
            self.stdout.write("No results found.\n")
            return

        self.stdout.write(f"\nFound {len(rows)} result(s):\n")
        sep = "-" * 80

        for row in rows:
            data = dict(zip(columns, row))
            self.stdout.write(sep)
            self.stdout.write(f"query_id:         {data['query_id']}")
            self.stdout.write(f"initial_query_id: {data['initial_query_id']}")
            self.stdout.write(f"time:             {data['query_start_time']}")
            self.stdout.write(f"duration_ms:      {data['query_duration_ms']:,}")
            self.stdout.write(f"read_rows:        {data['read_rows']:,}")
            self.stdout.write(f"read_bytes:       {_fmt_bytes(data['read_bytes'])}")
            self.stdout.write(f"result_rows:      {data['result_rows']:,}")
            self.stdout.write(f"status:           {data['type']}")
            self.stdout.write(f"team_id:          {data['team_id']}")
            self.stdout.write(f"product:          {data['lc_product']}")
            self.stdout.write(f"workload:         {data['lc_workload']}")
            self.stdout.write(f"query_kind:       {data['lc_query__kind']}")

            if data["lc_query__query"]:
                preview = data["lc_query__query"]
                if len(preview) > 300:
                    preview = preview[:300] + "..."
                self.stdout.write(f"hogql_query:\n  {preview}")

            if data["lc_modifiers"]:
                self.stdout.write(f"modifiers:        {_format_modifiers(data['lc_modifiers'])}")

            exception_code = data["exception_code"]
            if exception_code and int(exception_code) != 0:
                self.stdout.write(f"exception_code:   {exception_code}")
                if data["exception"]:
                    self.stdout.write(f"exception:        {data['exception'][:200]}")

        self.stdout.write(sep)


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"


def _format_modifiers(raw: str) -> str:
    """Pretty-print modifiers JSON, showing only non-null values."""
    try:
        parsed = json.loads(raw)
        non_null = {k: v for k, v in parsed.items() if v is not None}
        if not non_null:
            return "{}"
        return json.dumps(non_null, separators=(", ", ": "))
    except (json.JSONDecodeError, TypeError, AttributeError):
        return raw
