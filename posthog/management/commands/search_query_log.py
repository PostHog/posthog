"""
Management command to search query_log_archive for a specific query.

The challenge: you can't just paste a query and do WHERE query = '...' because:
  - ClickHouse adds indentation and formatting when it stores queries
  - HogQL is compiled to ClickHouse SQL before execution, adding team guards, JOINs, etc.
  - Different HogQL modifiers produce structurally different ClickHouse SQL

The solution: normalize first, then match by hash.

Two modes:

  --mode hash (default):
    Computes cityHash64(normalizeQuery(<sql>)) — a pure ClickHouse expression, zero data scanned.
    normalizeQuery() strips all literal values (dates, IDs, strings → '?') and normalizes whitespace.
    The resulting hash matches the normalized_query_hash column in query_log_archive, which ClickHouse
    populates automatically from system.query_log.

    For HogQL input (--hogql flag): compiles the query to ClickHouse SQL first using the full pipeline
    with default modifiers for the given team, then hashes the result.

  --mode hogql_text:
    Searches lc_query__query (the original HogQL stored in log_comment) by comparing
    cityHash64(normalizeQuery(lc_query__query)) on both sides. Catches indentation and whitespace
    differences in stored queries. Slower than hash mode but useful when you have a HogQL query
    and the CH SQL hash doesn't match (e.g., modifiers have changed since the query ran).

Results always include lc_modifiers so you can see exactly what was added before execution.

Usage examples:

  # Search for a HogQL query (compiles to CH SQL first, then matches by normalized hash)
  python manage.py search_query_log --hogql --team-id 1234 --query "SELECT count() FROM events WHERE event = 'pageview'"

  # Search for a raw ClickHouse SQL query you found somewhere
  python manage.py search_query_log --query "SELECT count() FROM posthog_db.sharded_events ..."

  # Search by HogQL text (skips compilation, matches stored lc_query__query by normalized text)
  python manage.py search_query_log --mode hogql_text --team-id 1234 --query "SELECT * FROM events"

  # Search last 30 days, return up to 50 results
  python manage.py search_query_log --hogql --team-id 1234 --days 30 --limit 50 --query "..."
"""

import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Search query_log_archive for a specific query using normalized hash matching"

    def add_arguments(self, parser):
        parser.add_argument(
            "--query",
            required=True,
            help="Query to search for. HogQL if --hogql is set, otherwise raw ClickHouse SQL.",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            dest="team_id",
            help="Restrict search to a specific team. Required with --hogql. Without it, scans all teams (slow).",
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
            "--hogql",
            action="store_true",
            help=(
                "Treat --query as HogQL. Compiles it to ClickHouse SQL using the PostHog pipeline "
                "with default modifiers for --team-id, then searches by the resulting normalized hash. "
                "Requires --team-id."
            ),
        )
        parser.add_argument(
            "--mode",
            choices=["hash", "hogql_text"],
            default="hash",
            help=(
                "Search mode. "
                "'hash' (default): match via normalized_query_hash (fast, indexed). "
                "'hogql_text': match via normalizeQuery(lc_query__query) text comparison (slower, no index)."
            ),
        )
        parser.add_argument(
            "--show-sql",
            action="store_true",
            dest="show_sql",
            help="Print the compiled ClickHouse SQL before searching (only relevant with --hogql).",
        )

    def handle(self, *args, **options):
        query_input: str = options["query"]
        team_id: int | None = options.get("team_id")
        days: int = options["days"]
        limit: int = options["limit"]
        is_hogql: bool = options["hogql"]
        mode: str = options["mode"]
        show_sql: bool = options["show_sql"]

        if is_hogql and not team_id:
            raise CommandError("--team-id is required when --hogql is specified (needed to compile the query).")

        if mode == "hogql_text" and is_hogql:
            # hogql_text mode searches lc_query__query directly; no compilation needed
            self._search_by_hogql_text(query_input, team_id, days, limit)
            return

        if is_hogql:
            ch_sql = self._compile_hogql(query_input, team_id)
            if show_sql:
                preview = ch_sql[:1000] + ("..." if len(ch_sql) > 1000 else "")
                self.stdout.write(f"\nCompiled ClickHouse SQL:\n{preview}\n")
        else:
            ch_sql = query_input

        self._search_by_hash(ch_sql, team_id, days, limit)

    def _compile_hogql(self, hogql_query: str, team_id: int) -> str:
        """Compile a HogQL query to ClickHouse SQL using the full PostHog pipeline."""
        from posthog.hogql.context import HogQLContext
        from posthog.hogql.modifiers import create_default_modifiers_for_team
        from posthog.hogql.parser import parse_select
        from posthog.hogql.printer.utils import prepare_and_print_ast

        from posthog.models.team import Team

        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found.")

        modifiers = create_default_modifiers_for_team(team)
        context = HogQLContext(
            team_id=team_id,
            team=team,
            enable_select_queries=True,
            modifiers=modifiers,
        )

        try:
            node = parse_select(hogql_query)
        except Exception as e:
            raise CommandError(f"Failed to parse HogQL query: {e}") from e

        try:
            sql, _ = prepare_and_print_ast(node, context=context, dialect="clickhouse")
        except Exception as e:
            raise CommandError(f"Failed to compile HogQL to ClickHouse SQL: {e}") from e

        return sql

    def _compute_normalized_hash(self, ch_sql: str) -> int:
        """
        Compute cityHash64(normalizeQuery(ch_sql)) via ClickHouse.

        This is a pure expression — ClickHouse evaluates it without scanning any table.
        The result matches the normalized_query_hash column in query_log_archive.
        """
        from posthog.clickhouse.client.execute import sync_execute

        result = sync_execute(
            "SELECT cityHash64(normalizeQuery(%(query)s)) AS hash",
            {"query": ch_sql},
        )
        return result[0][0]

    def _search_by_hash(self, ch_sql: str, team_id: int | None, days: int, limit: int) -> None:
        from posthog.clickhouse.client.execute import sync_execute

        if not team_id:
            self.stderr.write(
                "Warning: no --team-id specified. Searching across all teams may be slow on large clusters.\n"
            )

        try:
            normalized_hash = self._compute_normalized_hash(ch_sql)
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
                is_initial_query,
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

        self._print_results(rows, mode="hash")

    def _search_by_hogql_text(self, hogql_query: str, team_id: int | None, days: int, limit: int) -> None:
        """
        Search by comparing normalizeQuery() of the stored lc_query__query against the user input.

        normalizeQuery() replaces literal values with '?' so queries that differ only in constants
        (dates, IDs, event names) hash to the same value. Whitespace and indentation differences
        are also absorbed.

        Requires scanning the lc_query__query column within the team+date partition — no index help
        beyond the partition pruning. Still fast for a single team over a short date range.
        """
        from posthog.clickhouse.client.execute import sync_execute

        if not team_id:
            self.stderr.write("Warning: no --team-id specified. hogql_text mode without a team will scan all teams.\n")

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
                is_initial_query,
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

        self._print_results(rows, mode="hogql_text")

    def _print_results(self, rows: list, mode: str) -> None:
        columns = [
            "query_id",
            "initial_query_id",
            "is_initial_query",
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
            if mode == "hash":
                self.stdout.write(
                    "Tip: if you provided HogQL, try --mode hogql_text which searches the stored "
                    "HogQL text directly (handles cases where modifiers changed the compiled SQL).\n"
                )
            return

        self.stdout.write(f"\nFound {len(rows)} result(s):\n")
        sep = "-" * 80

        for row in rows:
            data = dict(zip(columns, row))
            self.stdout.write(sep)
            self.stdout.write(f"query_id:         {data['query_id']}")
            self.stdout.write(f"initial_query_id: {data['initial_query_id']}")
            self.stdout.write(f"is_initial:       {bool(data['is_initial_query'])}")
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
                modifiers_str = _format_modifiers(data["lc_modifiers"])
                self.stdout.write(f"modifiers:        {modifiers_str}")

            exception_code = data["exception_code"]
            if exception_code and int(exception_code) != 0:
                self.stdout.write(f"exception_code:   {exception_code}")
                if data["exception"]:
                    exc_preview = data["exception"][:200]
                    self.stdout.write(f"exception:        {exc_preview}")

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
