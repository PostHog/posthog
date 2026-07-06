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
from posthog.hogql.database.lazy_join_tags import ACCOUNT_CUSTOM_PROPERTIES, ACCOUNT_NOTEBOOKS, ACCOUNT_TAGS
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DANGEROUS_NoTeamIdCheckTable,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
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
    description="Internal federated junction table (PostgreSQL `posthog_taggeditem`) of tag-to-account links; not for direct querying — use `system.accounts.tags`.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Primary key of the tagged-item junction row."),
        "tag_id": UUIDDatabaseField(name="tag_id", description="Tag applied to the account; join to `system.tags.id`."),
        "account_id": UUIDDatabaseField(
            name="account_id", nullable=True, description="Account the tag is applied to; join to `system.accounts.id`."
        ),
    },
)

_account_resource_notebooks: _AccountScopedPostgresTable = _AccountScopedPostgresTable(
    name="_account_resource_notebooks",
    postgres_table_name="posthog_resourcenotebook",
    description="Internal federated junction table (PostgreSQL `posthog_resourcenotebook`) of notebook-to-account links; not for direct querying — use `system.accounts.notebooks`.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Primary key of the notebook junction row."),
        "notebook_id": StringDatabaseField(name="notebook_id", description="Identifier of the linked notebook."),
        "account_id": UUIDDatabaseField(
            name="account_id",
            nullable=True,
            description="Account the notebook is linked to; join to `system.accounts.id`.",
        ),
    },
)


_account_custom_property_values: _AccountScopedPostgresTable = _AccountScopedPostgresTable(
    name="_account_custom_property_values",
    postgres_table_name="customer_analytics_custompropertyvalue",
    description="Internal federated table (PostgreSQL `customer_analytics_custompropertyvalue`) of custom property values per account; not for direct querying — use `system.accounts.custom_properties`.",
    # Scope through team-filtered accounts (as the other junction tables do) AND prune
    # soft-deleted rows, so superseded `value_*` data can't be read via direct selection
    # of this hidden backing table — matching the `NOT cpv.is_deleted` filter in the lazy join.
    predicates=[
        parse_expr("account_id IN (SELECT id FROM system.accounts)"),
        # `NOT is_deleted` (not `is_deleted != true`): the predicate is pushed into the federated
        # PostgreSQL query, where comparing a boolean column to an integer literal is a type error.
        parse_expr("NOT is_deleted"),
    ],
    fields={
        "id": UUIDDatabaseField(name="id", description="Primary key of the custom property value row."),
        "definition_id": UUIDDatabaseField(
            name="definition_id", description="Custom property definition this value is for."
        ),
        "account_id": UUIDDatabaseField(
            name="account_id", nullable=True, description="Account the value belongs to; join to `system.accounts.id`."
        ),
        "is_deleted": BooleanDatabaseField(
            name="is_deleted", description="Whether this value has been superseded (soft-deleted)."
        ),
        "value_str": StringDatabaseField(name="value_str", nullable=True, description="String value, if a text type."),
        "value_bool": BooleanDatabaseField(
            name="value_bool", nullable=True, description="Boolean value, if a boolean type."
        ),
        "value_num": FloatDatabaseField(
            name="value_num", nullable=True, description="Numeric value, if a numeric type."
        ),
        "value_datetime": DateTimeDatabaseField(
            name="value_datetime", nullable=True, description="Datetime value, if a date/datetime type."
        ),
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


# A custom property value is stored across four typed columns (exactly one non-null per row);
# coalesce them to a single string so any display type round-trips through one column.
_COALESCED_VALUE = (
    "coalesce(cpv.value_str, toString(cpv.value_num), toString(cpv.value_bool), toString(cpv.value_datetime))"
)


def _account_custom_properties_select(fields_accessed: dict[str, list[str | int]]) -> ast.SelectQuery:
    r"""Aggregate each account's active custom property values.

    `values` is a JSON object keyed by definition id. Accessing a single key
    (`accounts.custom_properties.values.\`<id>\``) is requested as a nested field `values___<id>`;
    a lazy-join subquery can't JSON-extract that after the fact, so each requested key is
    materialized here as its own column via `anyIf` filtered to that definition.
    """
    select: list[ast.Expr] = [parse_expr("cpv.account_id AS account_id")]
    for name, chain in fields_accessed.items():
        if chain == ["account_id"]:
            continue
        if len(chain) >= 2 and chain[0] == "values":
            select.append(
                ast.Alias(
                    alias=name,
                    expr=parse_expr(
                        f"anyIf({_COALESCED_VALUE}, toString(cpv.definition_id) = {{key}})",
                        placeholders={"key": ast.Constant(value=str(chain[1]))},
                    ),
                )
            )
        elif chain == ["values"]:
            select.append(
                # nosemgrep: hogql-fstring-audit - only interpolates the module-level _COALESCED_VALUE constant (no user input)
                parse_expr(
                    f"toJSONString(mapFromArrays(groupArray(toString(cpv.definition_id)), groupArray({_COALESCED_VALUE}))) AS values"
                )
            )
    return ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=ast.Field(chain=["system", "_account_custom_property_values"]), alias="cpv"),
        where=parse_expr("NOT cpv.is_deleted"),
        group_by=[ast.Field(chain=["cpv", "account_id"])],
    )


class _AccountTagsTable(LazyTable):
    description: str = (
        "Internal aggregating table backing `system.accounts.tags`: the distinct, sorted tag names per account."
    )
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(
            name="account_id", description="Account these tags belong to; join to `system.accounts.id`."
        ),
        "names": StringArrayDatabaseField(
            name="names", description="Distinct, sorted tag names applied to the account."
        ),
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
    description: str = (
        "Internal aggregating table backing `system.accounts.notebooks`: the count of notebooks linked per account."
    )
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(
            name="account_id", description="Account these notebooks belong to; join to `system.accounts.id`."
        ),
        "count": IntegerDatabaseField(name="count", description="Number of notebooks linked to the account."),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return _account_notebooks_select()

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_notebooks"

    def to_printed_hogql(self) -> str:
        return "account_notebooks"


class _AccountCustomPropertiesTable(LazyTable):
    description: str = (
        "Internal aggregating table backing `system.accounts.custom_properties`: a JSON object of each "
        "account's active custom property values, keyed by definition id."
    )
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(
            name="account_id", description="Account these custom properties belong to; join to `system.accounts.id`."
        ),
        "values": StringJSONDatabaseField(
            name="values",
            description=(
                "JSON object of active custom property values keyed by custom property definition id, "
                "coalesced to strings. Read one property with "
                "accounts.custom_properties.values.`<definition_id>` (backtick-quote the id). "
                "Get definition ids and names from system.custom_property_definitions."
            ),
        ),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return _account_custom_properties_select(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_custom_properties"

    def to_printed_hogql(self) -> str:
        return "account_custom_properties"


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


def account_tags_join(join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.tags`")
    return _join_on_account_id(_account_tags_select(), join_to_add)


def account_notebooks_join(join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.notebooks`")
    return _join_on_account_id(_account_notebooks_select(), join_to_add)


def account_custom_properties_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.custom_properties`")
    return _join_on_account_id(_account_custom_properties_select(join_to_add.fields_accessed), join_to_add)


account_tags_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountTagsTable(),
    resolver=ACCOUNT_TAGS,
)

account_notebooks_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountNotebooksTable(),
    resolver=ACCOUNT_NOTEBOOKS,
)

account_custom_properties_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountCustomPropertiesTable(),
    resolver=ACCOUNT_CUSTOM_PROPERTIES,
)
