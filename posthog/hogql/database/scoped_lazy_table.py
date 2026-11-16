from typing import Optional

from posthog.hogql import ast
from posthog.hogql.database.models import DatabaseField, LazyTable, LazyTableToAdd

from posthog.scopes import APIScopeObject


def json_key_read(chain: list[str | int]) -> ast.Expr:
    """The same JSON key read that a JSON field gets: null and quotes are trimmed from the raw value."""
    raw = ast.Call(
        name="JSONExtractRaw",
        args=[ast.Field(chain=[chain[0]]), *(ast.Constant(value=key) for key in chain[1:])],
    )
    trimmed = ast.Call(
        name="nullIf",
        args=[ast.Call(name="nullIf", args=[raw, ast.Constant(value="")]), ast.Constant(value="null")],
    )
    return ast.Call(name="replaceRegexpAll", args=[trimmed, ast.Constant(value='^"|"$'), ast.Constant(value="")])


class ScopedLazyTable(LazyTable):
    """A system table built from a select over other system tables, gated by `access_scope` like a
    `PostgresTable` is.

    The gate is resource-level only. Row filtering, team scoping and object-level guards come from
    the system tables its select reads, so each of those must carry the same scope.
    """

    access_scope: APIScopeObject

    @property
    def access_control_id(self) -> Optional[str]:
        # No column keys an object grant, so a reader with only object grants on the scope is denied
        # the table rather than shown rows that no grant narrowed.
        return None

    def with_nested_reads(
        self, rows: ast.SelectQuery | ast.SelectSetQuery, table_to_add: LazyTableToAdd
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        """`rows`, plus a column for each nested JSON read the query makes, such as `config.series_index`.
        Lazy table resolution reads each one as its own flat column of the subquery."""
        nested = {alias: chain for alias, chain in table_to_add.fields_accessed.items() if len(chain) > 1}
        if not nested:
            return rows
        columns = [name for name, field in self.fields.items() if isinstance(field, DatabaseField) and not field.hidden]
        return ast.SelectQuery(
            select=[
                *(ast.Alias(alias=name, expr=ast.Field(chain=[name])) for name in columns),
                *(ast.Alias(alias=alias, expr=json_key_read(chain)) for alias, chain in nested.items()),
            ],
            select_from=ast.JoinExpr(table=rows),
        )
