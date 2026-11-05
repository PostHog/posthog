import re
from typing import TYPE_CHECKING

from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.escape_sql import escape_hogql_identifier

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

_LEADING_WITH = re.compile(
    r"\A((?:\s+|--[^\n]*(?:\n|\Z)|/\*.*?\*/)*)with\b(\s+recursive\b)?", re.IGNORECASE | re.DOTALL
)


def _reference_pattern(name: str) -> re.Pattern[str]:
    # A qualified name such as catalog.schema.name reads a physical table, never a CTE.
    escaped = re.escape(name)
    return re.compile(rf'(?<![\w."])(?:"{escaped}"|{escaped}(?!\w))', re.IGNORECASE)


def _defines_cte(sql: str, name: str) -> bool:
    escaped = re.escape(name)
    return (
        re.search(rf'(?<![\w."])(?:"{escaped}"|{escaped})\s*(?:\([^()]*\)\s*)?as\s*\(', sql, re.IGNORECASE) is not None
    )


def _referenced_views(sql: str, names: list[str]) -> list[str]:
    # A query that defines its own CTE of a view's name reads that CTE, not the view.
    return [name for name in names if _reference_pattern(name).search(sql) and not _defines_cte(sql, name)]


def _view_body(sql: str) -> str:
    return sql.strip().rstrip(";").rstrip()


def raw_trino_view_sql(saved_query_json: object) -> str:
    sql = saved_query_json.get("query") if isinstance(saved_query_json, dict) else None
    return sql if isinstance(sql, str) else ""


def expand_raw_trino_view_references(sql: str, views: dict[str, str]) -> str:
    """Prepend a CTE for each raw Trino view the SQL reads, since Trino has no table of that name.

    Names match as whole words, so a mention in a comment or string adds an unused CTE, which Trino ignores.
    """
    by_lower: dict[str, tuple[str, str]] = {}
    for name, body in views.items():
        if "." not in name:
            by_lower.setdefault(name.lower(), (name, _view_body(body)))
    names = sorted(by_lower)

    ordered: list[str] = []
    done: set[str] = set()

    def visit(name: str, path: list[str]) -> None:
        if name in done:
            return
        if name in path:
            cycle = " -> ".join(by_lower[n][0] for n in [*path[path.index(name) :], name])
            raise ExposedHogQLError(f"Views reference each other in a cycle: {cycle}.")
        for dependency in _referenced_views(by_lower[name][1], names):
            visit(dependency, [*path, name])
        done.add(name)
        ordered.append(name)

    for name in _referenced_views(sql, names):
        visit(name, [])
    if not ordered:
        return sql

    ctes = ", ".join(f'"{by_lower[name][0]}" AS (\n{by_lower[name][1]}\n)' for name in ordered)
    leading_with = _LEADING_WITH.match(sql)
    if leading_with is None:
        return f"WITH {ctes}\n{sql}"
    if leading_with.group(2):
        raise ExposedHogQLError(
            "A WITH RECURSIVE query cannot read a saved view. Copy the view's SQL into the query instead."
        )
    return f"{leading_with.group(1)}WITH {ctes}, {sql[leading_with.end() :].lstrip()}"


class RawTrinoViewTable(FunctionCallTable):
    """A saved view whose SQL is raw Trino SQL. Only the Trino printer can inline it."""

    requires_args: bool = False
    trino_sql: str
    # Every raw Trino view of the team, so the printed body can read other raw views.
    raw_trino_views: dict[str, str]

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name or "")

    def to_printed_trino(self, context: "HogQLContext") -> str:
        return f"(\n{expand_raw_trino_view_references(_view_body(self.trino_sql), self.raw_trino_views)}\n)"

    def _refuse(self, dialect: str) -> str:
        raise QueryError(f"View '{self.name}' runs raw Trino SQL, so it cannot be printed into {dialect} SQL.")

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return self._refuse("ClickHouse")

    def to_printed_postgres(self, context: "HogQLContext") -> str:
        return self._refuse("Postgres")

    def to_printed_duckdb(self, context: "HogQLContext") -> str:
        return self._refuse("DuckDB")
