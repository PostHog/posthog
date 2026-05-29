"""Internal aggregating tables and lazy joins that power `system.accounts.tags` and
`system.accounts.notebooks`.

The two raw federated tables (`_account_tagged_items`, `_account_resource_notebooks`)
are tag/notebook junction rows from PostgreSQL. They have no `team_id` column and
should not be reachable directly from the SQL editor — they exist only so the lazy
join subqueries below can be resolved by the planner.
"""

from posthog.hogql import ast
from posthog.hogql.base import Expr
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoin,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    StringArrayDatabaseField,
    StringDatabaseField,
    UUIDDatabaseField,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.errors import ResolutionError
from posthog.hogql.parser import parse_expr, parse_select


class _AccountScopedPostgresTable(PostgresTable, DANGEROUS_NoTeamIdCheckTable):
    """PostgresTable variant for FK-only junction tables that lack a `team_id` column.

    The framework's auto-injected `team_id = X` guard is bypassed because the column
    doesn't exist. Security is preserved instead via a predicate (set on the class) that
    scopes through `account_id`, relying on the framework re-applying its team_id guard
    to the inner `system.accounts` reference.

    Direct top-level SELECT remains safe because the predicate prunes rows whose FK
    doesn't resolve to a team-scoped account.
    """

    predicates: list[Expr] = [parse_expr("account_id IN (SELECT id FROM system.accounts)")]


_account_tagged_items: _AccountScopedPostgresTable = _AccountScopedPostgresTable(
    name="_account_tagged_items",
    postgres_table_name="posthog_taggeditem",
    fields={
        "id": UUIDDatabaseField(name="id"),
        "tag_id": UUIDDatabaseField(name="tag_id"),
        "account_id": UUIDDatabaseField(name="account_id", nullable=True),
    },
)

_account_resource_notebooks: _AccountScopedPostgresTable = _AccountScopedPostgresTable(
    name="_account_resource_notebooks",
    postgres_table_name="posthog_resourcenotebook",
    fields={
        "id": UUIDDatabaseField(name="id"),
        "notebook_id": StringDatabaseField(name="notebook_id"),
        "account_id": UUIDDatabaseField(name="account_id", nullable=True),
    },
)


def _account_tags_select() -> ast.SelectQuery | ast.SelectSetQuery:
    return parse_select(
        """
        SELECT
            ati.account_id AS account_id,
            arraySort(arrayDistinct(groupArray(t.name))) AS names
        FROM system._account_tagged_items AS ati
        INNER JOIN system.tags AS t ON t.id = ati.tag_id
        GROUP BY ati.account_id
        """
    )


def _account_notebooks_select() -> ast.SelectQuery | ast.SelectSetQuery:
    return parse_select(
        """
        SELECT
            arn.account_id AS account_id,
            count() AS count
        FROM system._account_resource_notebooks AS arn
        GROUP BY arn.account_id
        """
    )


class _AccountTagsTable(LazyTable):
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(name="account_id"),
        "names": StringArrayDatabaseField(name="names"),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return _account_tags_select()

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_tags"

    def to_printed_hogql(self) -> str:
        return "account_tags"


class _AccountNotebooksTable(LazyTable):
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(name="account_id"),
        "count": IntegerDatabaseField(name="count"),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return _account_notebooks_select()

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_notebooks"

    def to_printed_hogql(self) -> str:
        return "account_notebooks"


def _join_on_account_id(select: ast.SelectQuery | ast.SelectSetQuery, join_to_add: LazyJoinToAdd) -> ast.JoinExpr:
    return ast.JoinExpr(
        alias=join_to_add.to_table,
        table=select,
        join_type="LEFT JOIN",
        constraint=ast.JoinConstraint(
            constraint_type="ON",
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[join_to_add.from_table, "id"]),
                right=ast.Field(chain=[join_to_add.to_table, "account_id"]),
            ),
        ),
    )


def _account_tags_join(join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.tags`")
    return _join_on_account_id(_account_tags_select(), join_to_add)


def _account_notebooks_join(join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.notebooks`")
    return _join_on_account_id(_account_notebooks_select(), join_to_add)


account_tags_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountTagsTable(),
    join_function=_account_tags_join,
)

account_notebooks_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountNotebooksTable(),
    join_function=_account_notebooks_join,
)
