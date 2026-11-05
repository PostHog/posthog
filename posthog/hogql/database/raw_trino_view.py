from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING

from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.escape_sql import escape_hogql_identifier

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from sqlglot.tokens import Token as DialectToken

    from posthog.hogql.context import HogQLContext

VIEW_CTE_PREFIX = "__ph_rv_"
MAX_VIEW_DEPTH = 32
MAX_EXPANDED_SQL_LENGTH = 1_000_000


class RawTrinoViewMode(StrEnum):
    EXPAND = "expand"
    # Raw view SQL runs on the organization's warehouse credential, so a caller that may not run raw SQL gets an error.
    REFUSE = "refuse"


@frozen
class RawTrinoView:
    name: str
    sql: str


@frozen
class RawTrinoViewCatalog:
    """The raw Trino views a caller can read. Every key is a lowercase view name, because Trino ignores identifier case."""

    views: Mapping[str, RawTrinoView]
    denied_names: frozenset[str] = frozenset()
    hogql_view_names: frozenset[str] = frozenset()
    deleted_names: frozenset[str] = frozenset()


def raw_trino_view_sql(saved_query_json: object) -> str:
    sql = saved_query_json.get("query") if isinstance(saved_query_json, dict) else None
    return sql if isinstance(sql, str) else ""


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lex(sql: str) -> list["DialectToken"]:
    # The direct_sql package imports the warehouse sources product, which this module must not load at import time.
    from posthog.hogql.direct_sql.raw_sql import lex_direct_sql  # noqa: PLC0415

    return lex_direct_sql(sql, "trino")


def _words(tokens: list["DialectToken"]) -> list["DialectToken"]:
    from posthog.hogql.direct_sql.raw_sql import literal_token_types  # noqa: PLC0415 -- see _lex

    literals = literal_token_types()
    return [token for token in tokens if token.token_type not in literals]


def _statement_end(tokens: list["DialectToken"]) -> int:
    from sqlglot.tokens import TokenType  # noqa: PLC0415 -- load dialect grammars only for Trino queries

    end = len(tokens)
    while end > 0 and tokens[end - 1].token_type == TokenType.SEMICOLON:
        end -= 1
    return end


def _clean_body(view: RawTrinoView) -> str:
    """The view SQL without comments or trailing semicolons, so it can sit inside a subquery.

    Comments go too, because the parameter binder reads a quote inside a comment as the start of a string.
    """
    tokens = _lex(view.sql)
    tokens = tokens[: _statement_end(tokens)]
    if not tokens:
        raise ExposedHogQLError(f"View '{view.name}' has no SQL.")
    pieces: list[str] = []
    previous_end: int | None = None
    for token in tokens:
        if previous_end is not None:
            gap = view.sql[previous_end + 1 : token.start]
            pieces.append(gap if gap.isspace() or not gap else " ")
        pieces.append(view.sql[token.start : token.end + 1])
        previous_end = token.end
    return "".join(pieces)


def _apply(sql: str, edits: list[tuple[int, int, str]]) -> str:
    for start, end, text in sorted(edits, reverse=True):
        sql = sql[:start] + text + sql[end:]
    return sql


class _Expansion:
    """One expansion run. Each view becomes one CTE, so a view read twice or along two paths is hoisted once."""

    def __init__(self, catalog: RawTrinoViewCatalog) -> None:
        self.catalog = catalog
        self.ctes: list[str] = []
        self.cte_names: dict[str, str] = {}
        self.size = 0
        self.lookup_words = {
            word
            for name in (*catalog.views, *catalog.denied_names, *catalog.hogql_view_names, *catalog.deleted_names)
            for word in (name, *name.split("."))
        }

    def statement(self, sql: str, *, owner: RawTrinoView | None = None) -> str:
        tokens = _lex(sql)
        edits = self._rewrite(sql, tokens, path=[owner.name] if owner else [])
        if not self.ctes:
            return _apply(sql, edits)

        from sqlglot.tokens import TokenType  # noqa: PLC0415 -- load dialect grammars only for Trino queries

        ctes = ", ".join(self.ctes)
        first = tokens[0]
        if first.token_type == TokenType.WITH:
            if len(tokens) > 1 and tokens[1].text.upper() == "RECURSIVE":
                # Trino requires column aliases on every CTE of a recursive WITH, and a hoisted view has none.
                raise ExposedHogQLError(
                    "A WITH RECURSIVE query cannot read a saved view. Copy the view's SQL into the query instead."
                )
            edits.append((first.end + 1, first.end + 1, f" {ctes},"))
        else:
            edits.append((first.start, first.start, f"WITH {ctes}\n"))
        return _apply(sql, edits)

    def _rewrite(self, sql: str, tokens: list["DialectToken"], *, path: list[str]) -> list[tuple[int, int, str]]:
        from sqlglot import exp, parse_one  # noqa: PLC0415 -- load dialect grammars only for Trino queries
        from sqlglot.errors import SqlglotError  # noqa: PLC0415
        from sqlglot.optimizer.scope import traverse_scope  # noqa: PLC0415

        words = _words(tokens)
        for token in words:
            if token.text.lower().startswith(VIEW_CTE_PREFIX):
                raise ExposedHogQLError(f"Names that start with {VIEW_CTE_PREFIX} are reserved. Rename '{token.text}'.")
        named = next((token.text for token in words if token.text.lower() in self.lookup_words), None)
        if named is None:
            return []

        end = _statement_end(tokens)
        try:
            tree = parse_one(sql[: tokens[end - 1].end + 1], read="trino") if end else None
            scopes = traverse_scope(tree) if isinstance(tree, exp.Query) else None
        except (SqlglotError, RecursionError):
            scopes = None
        if scopes is None:
            raise ExposedHogQLError(f"Could not parse the query to expand view '{named}'.")

        edits: list[tuple[int, int, str]] = []
        for scope in scopes:
            ctes = {name.lower() for name in scope.cte_sources}
            for table in scope.tables:
                parts = table.parts
                if not isinstance(table.this, exp.Identifier) or not all(isinstance(p, exp.Identifier) for p in parts):
                    continue
                key = ".".join(part.name for part in parts).lower()
                if len(parts) == 1 and key in ctes:
                    continue
                view = self.catalog.views.get(key)
                if view is None:
                    self._refuse_unreadable(key, parts[-1].name, path=path, qualified=len(parts) > 1)
                    continue
                start, stop = parts[0].meta.get("start"), parts[-1].meta.get("end")
                if start is None or stop is None:
                    raise ExposedHogQLError(f"Could not parse the query to expand view '{view.name}'.")
                alias = "" if table.args.get("alias") else f" AS {_quote(parts[-1].name)}"
                edits.append((start, stop + 1, self._hoist(view, path) + alias))
        return edits

    def _refuse_unreadable(self, key: str, name: str, *, path: list[str], qualified: bool) -> None:
        if key in self.catalog.denied_names:
            raise ExposedHogQLError(f"You don't have access to view '{name}'.")
        if key in self.catalog.hogql_view_names:
            raise ExposedHogQLError(
                f"'{name}' is a HogQL view, so raw Trino SQL cannot read it. Open it with Send raw query turned off."
            )
        # At the top level the name passes through, so a real table that shares a deleted view's name stays readable.
        if path and not qualified and key in self.catalog.deleted_names:
            raise ExposedHogQLError(f"View '{path[-1]}' reads view '{name}', which was deleted.")

    def _hoist(self, view: RawTrinoView, path: list[str]) -> str:
        key = view.name.lower()
        lowered = [name.lower() for name in path]
        if key in lowered:
            cycle = " -> ".join([*path[lowered.index(key) :], view.name])
            raise ExposedHogQLError(f"Views reference each other in a cycle: {cycle}.")
        if key in self.cte_names:
            return self.cte_names[key]
        if len(path) >= MAX_VIEW_DEPTH:
            raise ExposedHogQLError(f"Views are nested more than {MAX_VIEW_DEPTH} levels deep: {' -> '.join(path)}.")

        body = _clean_body(view)
        expanded = _apply(body, self._rewrite(body, _lex(body), path=[*path, view.name]))
        self.size += len(expanded)
        if self.size > MAX_EXPANDED_SQL_LENGTH:
            raise ExposedHogQLError("The saved views this query reads expand to too much SQL. Read fewer views.")
        cte_name = f"{VIEW_CTE_PREFIX}{len(self.ctes)}"
        self.ctes.append(f"{cte_name} AS (\n{expanded}\n)")
        self.cte_names[key] = cte_name
        return cte_name


def expand_raw_trino_view_references(sql: str, catalog: RawTrinoViewCatalog) -> str:
    """Hoist each raw Trino view the SQL reads into a leading CTE, since Trino has no table of that name.

    The original text is kept. Only the table references change, so comments, literals and formatting reach Trino as
    written.
    """
    return _Expansion(catalog).statement(sql)


def expand_raw_trino_view(name: str, catalog: RawTrinoViewCatalog) -> str:
    """The view's SQL as a standalone statement, with the views it reads hoisted into its leading WITH."""
    view = catalog.views.get(name.lower())
    if view is None:
        raise QueryError(f"Unknown raw Trino view '{name}'.")
    return _Expansion(catalog).statement(_clean_body(view), owner=view)


class RawTrinoViewTable(FunctionCallTable):
    """A saved view whose SQL is raw Trino SQL. Only the Trino printer can inline it."""

    requires_args: bool = False

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name or "")

    def to_printed_trino(self, context: "HogQLContext") -> str:
        catalog = context.raw_trino_view_catalog
        if context.database is not None and context.database.raw_trino_view_catalog is not None:
            catalog = context.database.raw_trino_view_catalog
        if catalog is None:
            raise QueryError(f"View '{self.name}' runs raw Trino SQL, which this query cannot read.")
        return f"(\n{expand_raw_trino_view(self.name or '', catalog)}\n)"

    def _refuse(self, dialect: str) -> str:
        raise QueryError(f"View '{self.name}' runs raw Trino SQL, so it cannot be printed into {dialect} SQL.")

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return self._refuse("ClickHouse")

    def to_printed_postgres(self, context: "HogQLContext") -> str:
        return self._refuse("Postgres")

    def to_printed_duckdb(self, context: "HogQLContext") -> str:
        return self._refuse("DuckDB")


class RefusedRawTrinoViewTable(RawTrinoViewTable):
    """A raw Trino view that this caller may not run, kept in the catalog so a reference fails with a clear reason."""

    def to_printed_trino(self, context: "HogQLContext") -> str:
        raise ExposedHogQLError(f"View '{self.name}' runs raw Trino SQL. Open it from the SQL editor while signed in.")
