from typing import TYPE_CHECKING

from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.escape_sql import escape_hogql_identifier

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

VIEW_CTE_PREFIX = "__ph_rv_"


def raw_trino_view_sql(saved_query_json: object) -> str:
    sql = saved_query_json.get("query") if isinstance(saved_query_json, dict) else None
    return sql if isinstance(sql, str) else ""


def raw_trino_view_body(name: str, sql: str) -> str:
    """The view SQL as one subquery body: no comments, no trailing semicolons, and balanced parentheses.

    Comments go because the parameter binder reads a quote inside a comment as the start of a string.
    Unbalanced parentheses could close the CTE early and add SQL outside it.
    """
    # The direct_sql package imports the warehouse sources product, which this module must not load at import time.
    from sqlglot.tokens import TokenType  # noqa: PLC0415

    from posthog.hogql.direct_sql.raw_sql import lex_direct_sql  # noqa: PLC0415

    tokens = lex_direct_sql(sql, "trino")
    while tokens and tokens[-1].token_type == TokenType.SEMICOLON:
        tokens.pop()
    if not tokens:
        raise ExposedHogQLError(f"View '{name}' has no SQL.")
    depth = 0
    pieces: list[str] = []
    previous_end: int | None = None
    for token in tokens:
        if token.token_type == TokenType.SEMICOLON:
            raise ExposedHogQLError(f"View '{name}' must hold a single SELECT statement.")
        depth += {TokenType.L_PAREN: 1, TokenType.R_PAREN: -1}.get(token.token_type, 0)
        if depth < 0:
            raise ExposedHogQLError(f"View '{name}' has unbalanced parentheses.")
        if previous_end is not None:
            gap = sql[previous_end + 1 : token.start]
            pieces.append(gap if gap.isspace() or not gap else " ")
        pieces.append(sql[token.start : token.end + 1])
        previous_end = token.end
    if depth != 0:
        raise ExposedHogQLError(f"View '{name}' has unbalanced parentheses.")
    return "".join(pieces)


class RawTrinoViewTable(FunctionCallTable):
    """A saved view whose SQL is raw Trino SQL. Only the Trino printer can read it, as a hoisted CTE."""

    requires_args: bool = False
    # None when the caller may not run the view, because its SQL runs on the organization's warehouse credential.
    sql: str | None = None

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name or "")

    def _refuse(self, dialect: str) -> str:
        raise QueryError(f"View '{self.name}' runs raw Trino SQL, so it cannot be printed into {dialect} SQL.")

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return self._refuse("ClickHouse")

    def to_printed_postgres(self, context: "HogQLContext") -> str:
        return self._refuse("Postgres")

    def to_printed_duckdb(self, context: "HogQLContext") -> str:
        return self._refuse("DuckDB")
