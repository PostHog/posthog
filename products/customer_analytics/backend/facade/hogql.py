"""Customer analytics' federated HogQL system tables (`system.accounts`,
`system.custom_property_definitions`) and the aggregating tables plus lazy joins that
power `system.accounts.tags`, `system.accounts.notebooks`, and
`system.accounts.custom_properties`.

Owned here rather than in core so the coupling between core's HogQL schema and this
product's Postgres tables is import-visible (tach) and facade-gated (CI): core
`schema/system.py` and `lazy_join_registry.py` import these definitions instead of
hardcoding the product's table and column names.

The raw federated junction tables (`_account_tagged_items`, `_account_resource_notebooks`,
`_account_custom_property_values`) have no `team_id` column and should not be reachable
directly from the SQL editor — they exist only so the lazy join subqueries below can be
resolved by the planner.
"""

from posthog.hogql import ast
from posthog.hogql.base import Expr
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.lazy_join_tags import (
    ACCOUNT_CUSTOM_PROPERTIES,
    ACCOUNT_NOTEBOOKS,
    ACCOUNT_RELATIONSHIPS,
    ACCOUNT_TAGS,
)
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DANGEROUS_NoTeamIdCheckTable,
    DateTimeDatabaseField,
    ExpressionField,
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


account_tagged_items: _AccountScopedPostgresTable = _AccountScopedPostgresTable(
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

account_resource_notebooks: _AccountScopedPostgresTable = _AccountScopedPostgresTable(
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


account_custom_property_values: _AccountScopedPostgresTable = _AccountScopedPostgresTable(
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
# Booleans render as 'true'/'false' explicitly: the federated read maps PostgreSQL boolean to
# UInt8, so toString() would yield '1'/'0' — which filters and value suggestions don't speak.
# The isNull guard keeps non-boolean rows falling through the coalesce (ClickHouse if()
# treats a NULL condition as false, which would otherwise coalesce them to 'false').
_COALESCED_VALUE = (
    "coalesce(cpv.value_str, toString(cpv.value_num),"
    " if(isNull(cpv.value_bool), NULL, if(cpv.value_bool, 'true', 'false')),"
    " toString(cpv.value_datetime))"
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


def _account_relationships_select(fields_accessed: dict[str, list[str | int]]) -> ast.SelectQuery:
    r"""Aggregate each account's ACTIVE relationship assignments.

    Inner select: one row per (account, definition) with the array of active user ids.
    Outer select: `values` as a JSON object keyed by definition id; each requested key
    (`accounts.relationships.values.\`<id>\``, arriving as `values___<id>`) is materialized
    as its own column via `anyIf` — a lazy-join subquery can't JSON-extract after the fact.
    """
    inner = parse_select(
        """
        SELECT
            rel.account_id AS account_id,
            toString(rel.definition_id) AS definition_key,
            arraySort(groupArray(rel.user_id)) AS user_ids
        FROM system.account_relationships AS rel
        WHERE isNull(rel.ended_at) AND isNotNull(rel.user_id)
        GROUP BY rel.account_id, rel.definition_id
        """
    )
    select: list[ast.Expr] = [parse_expr("account_id AS account_id")]
    for name, chain in fields_accessed.items():
        if chain == ["account_id"]:
            continue
        if len(chain) >= 2 and chain[0] == "values":
            select.append(
                ast.Alias(
                    alias=name,
                    expr=parse_expr(
                        "anyIf(user_ids, definition_key = {key})",
                        placeholders={"key": ast.Constant(value=str(chain[1]))},
                    ),
                )
            )
        elif chain == ["values"]:
            select.append(
                parse_expr("toJSONString(mapFromArrays(groupArray(definition_key), groupArray(user_ids))) AS values")
            )
    return ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=inner),
        group_by=[ast.Field(chain=["account_id"])],
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


class _AccountRelationshipsTable(LazyTable):
    description: str = (
        "Internal aggregating table backing `system.accounts.relationships`: a JSON object of each "
        "account's active relationship assignments, keyed by definition id."
    )
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(
            name="account_id", description="Account these relationships belong to; join to `system.accounts.id`."
        ),
        "values": StringJSONDatabaseField(
            name="values",
            description=(
                "JSON object of active relationship assignments keyed by definition id; each value is an "
                "array of assigned user ids. Read one definition with "
                "accounts.relationships.values.`<definition_id>` (backtick-quote the id). "
                "Get definition ids and names from system.account_relationship_definitions."
            ),
        ),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return _account_relationships_select(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_relationships"

    def to_printed_hogql(self) -> str:
        return "account_relationships"


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


def account_relationships_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.relationships`")
    return _join_on_account_id(_account_relationships_select(join_to_add.fields_accessed), join_to_add)


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


account_relationships_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountRelationshipsTable(),
    resolver=ACCOUNT_RELATIONSHIPS,
)


account_relationship_definitions: PostgresTable = PostgresTable(
    name="account_relationship_definitions",
    postgres_table_name="customer_analytics_accountrelationshipdefinition",
    # Sub-resource of accounts; gated at the account resource level (see customer_analytics backend CLAUDE.md).
    access_scope="account",
    description="Customer analytics account relationship definitions: team-defined relationship types between PostHog users and accounts (CSM, Account executive, ...), one row per definition. Per-account assignments live in system.account_relationships and via the system.accounts.relationships lazy join.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Relationship definition UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(
            name="name", description="Human-readable name of the relationship; unique within the team."
        ),
        "description": StringDatabaseField(
            name="description", nullable=True, description="What this relationship means."
        ),
        "_is_single_holder": BooleanDatabaseField(name="is_single_holder", hidden=True),
        "is_single_holder": ExpressionField(
            name="is_single_holder",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_single_holder"])]),
            description="1 if only one user can hold this relationship per account at a time, 0 otherwise.",
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="PostHog user who created the definition."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the definition was created."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the definition was last updated."
        ),
    },
)


account_relationships: PostgresTable = PostgresTable(
    name="account_relationships",
    postgres_table_name="customer_analytics_accountrelationship",
    # Sub-resource of accounts; gated at the account resource level (see customer_analytics backend CLAUDE.md).
    access_scope="account",
    # Child rows expose per-account data: object-level denies must filter the account FK,
    # not the assignment's own id, or a denied account's relationships leak.
    access_control_id_field="account_id",
    description="User-to-account relationship assignments (CSM, Account executive, ...), one row per assignment with its effective range — `ended_at` is NULL while active, set when the assignment ends, so historical account management is queryable. Active assignments per account are also exposed as a JSON object via the `system.accounts.relationships` lazy join.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Relationship assignment UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "definition_id": UUIDDatabaseField(
            name="definition_id",
            description="Relationship definition this assignment is for; join to `system.account_relationship_definitions.id`.",
        ),
        "account_id": UUIDDatabaseField(
            name="account_id", description="Account the assignment belongs to; join to `system.accounts.id`."
        ),
        "user_id": IntegerDatabaseField(name="user_id", nullable=True, description="Assigned PostHog user id."),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="PostHog user who made the assignment."
        ),
        "started_at": DateTimeDatabaseField(name="started_at", description="When the assignment became effective."),
        "ended_at": DateTimeDatabaseField(
            name="ended_at", nullable=True, description="When the assignment ended; NULL while active."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the assignment row was created."),
    },
)


accounts: PostgresTable = PostgresTable(
    name="accounts",
    postgres_table_name="customer_analytics_account",
    # Object-level access control filters out ids directly off access_scope, so we use
    # `account` here (where the per-object grants are stored) instead of the
    # `customer_analytics` umbrella. Resource-level gating still works via RESOURCE_INHERITANCE_MAP.
    access_scope="account",
    description="Customer analytics accounts (companies/organizations being tracked); one row per account, with CRM identifiers extracted from properties.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Account UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "external_id": StringDatabaseField(
            name="external_id", nullable=True, description="Identifier of the account in the source system."
        ),
        "name": StringDatabaseField(name="name", description="Display name of the account."),
        "properties": StringJSONDatabaseField(
            name="properties",
            description="JSON map of account properties; the CRM id columns below are extracted from this.",
        ),
        "stripe_customer_id": ExpressionField(
            name="stripe_customer_id",
            expr=parse_expr("JSONExtractString(properties, 'stripe_customer_id')"),
        ),
        "hubspot_deal_id": ExpressionField(
            name="hubspot_deal_id",
            expr=parse_expr("JSONExtractString(properties, 'hubspot_deal_id')"),
        ),
        "billing_id": ExpressionField(
            name="billing_id",
            expr=parse_expr("JSONExtractString(properties, 'billing_id')"),
        ),
        "sfdc_id": ExpressionField(
            name="sfdc_id",
            expr=parse_expr("JSONExtractString(properties, 'sfdc_id')"),
        ),
        "zendesk_id": ExpressionField(
            name="zendesk_id",
            expr=parse_expr("JSONExtractString(properties, 'zendesk_id')"),
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the account record."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the account record was created."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the account record was last updated."
        ),
        "tags": account_tags_lazy_join,
        "notebooks": account_notebooks_lazy_join,
        "custom_properties": account_custom_properties_lazy_join,
        "relationships": account_relationships_lazy_join,
    },
)


custom_property_definitions: PostgresTable = PostgresTable(
    name="custom_property_definitions",
    postgres_table_name="customer_analytics_custompropertydefinition",
    # Sub-resource of accounts; gated at the account resource level (see customer_analytics backend CLAUDE.md).
    access_scope="account",
    description="Customer analytics custom property definitions: team-scoped attribute shapes (the property's name and type), one row per definition. Per-account values are exposed via the system.accounts.custom_properties lazy join.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Custom property definition UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(
            name="name", description="Human-readable name of the custom property; unique within the team."
        ),
        "description": StringDatabaseField(
            name="description", nullable=True, description="Optional description of what the property represents."
        ),
        "display_type": StringDatabaseField(
            name="display_type",
            description="How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', or 'boolean'.",
        ),
        "_is_big_number": BooleanDatabaseField(name="is_big_number", hidden=True),
        "is_big_number": ExpressionField(
            name="is_big_number",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_big_number"])]),
            description="1 if large numeric values are abbreviated (e.g. 10,000 -> 10K), 0 otherwise.",
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="User who created the definition."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the definition was created."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the definition was last updated."
        ),
    },
)
