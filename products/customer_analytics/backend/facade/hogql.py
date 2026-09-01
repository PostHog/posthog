"""Customer analytics' federated HogQL system tables for accounts, custom
properties, relationships, and feature requests. This module also owns the aggregating
tables and lazy joins that power `system.accounts.tags`, `system.accounts.notebooks`,
and `system.accounts.custom_properties`.

Owned here rather than in core so the coupling between core's HogQL schema and this
product's Postgres tables is import-visible (tach) and facade-gated (CI): core
`schema/system.py` and `lazy_join_registry.py` import these definitions instead of
hardcoding the product's table and column names.

The raw federated junction tables (`_account_tagged_items`, `_account_resource_notebooks`,
`_account_custom_property_values`, `_account_custom_property_values_history`) have no
`team_id` column and should not be reachable directly from the SQL editor — they exist only
so the lazy join subqueries below can be resolved by the planner.
"""

from posthog.hogql import ast
from posthog.hogql.base import Expr
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.lazy_join_tags import (
    ACCOUNT_CUSTOM_PROPERTIES,
    ACCOUNT_CUSTOM_PROPERTIES_HISTORY,
    ACCOUNT_EMAIL_THREADS,
    ACCOUNT_FEATURE_REQUESTS,
    ACCOUNT_MEETINGS,
    ACCOUNT_NOTEBOOKS,
    ACCOUNT_RELATIONSHIPS,
    ACCOUNT_SLACK_SUMMARIES,
    ACCOUNT_SUPPORT_TICKETS,
    ACCOUNT_TAGS,
)
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DANGEROUS_NoTeamIdCheckTable,
    DateDatabaseField,
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
from posthog.hogql.errors import ResolutionError, TableAccessDeniedError
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


account_meetings: PostgresTable = PostgresTable(
    name="_account_meetings",
    postgres_table_name="customer_analytics_meeting",
    access_scope="account",
    access_control_id_field="account_id",
    description="Internal table of account meetings. Use `system.accounts.meetings` instead.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Meeting UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "account_id": UUIDDatabaseField(name="account_id", nullable=True),
        "title": StringDatabaseField(name="title"),
        "start_time": DateTimeDatabaseField(name="start_time"),
        "end_time": DateTimeDatabaseField(name="end_time", nullable=True),
        "organizer_email": StringDatabaseField(name="organizer_email"),
        "status": StringDatabaseField(name="status"),
    },
)


account_channel_summaries: PostgresTable = PostgresTable(
    name="_account_channel_summaries",
    postgres_table_name="customer_analytics_accountchannelsummary",
    access_scope="account",
    access_control_id_field="account_id",
    description="Internal table of account Slack summaries. Use `system.accounts.slack_summaries` instead.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Summary UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "account_id": UUIDDatabaseField(name="account_id"),
        "slack_channel_id": StringDatabaseField(name="slack_channel_id"),
        "cadence": StringDatabaseField(name="cadence"),
        "period_start": DateTimeDatabaseField(name="period_start"),
        "period_end": DateTimeDatabaseField(name="period_end"),
        "content": StringDatabaseField(name="content"),
        "message_count": IntegerDatabaseField(name="message_count"),
        "generated_at": DateTimeDatabaseField(name="generated_at"),
    },
)


account_email_threads: PostgresTable = PostgresTable(
    name="_account_email_threads",
    postgres_table_name="posthog_conversations_email_thread",
    access_scope="ticket",
    resource_level_access_only=True,
    predicates=[parse_expr("id IN (SELECT thread_id FROM system._account_email_thread_links)")],
    description="Internal table of customer email threads. Use `system.accounts.email_threads` instead.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Email thread UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "subject": StringDatabaseField(name="subject"),
        "first_message_at": DateTimeDatabaseField(name="first_message_at", nullable=True),
        "last_message_at": DateTimeDatabaseField(name="last_message_at", nullable=True),
        "message_count": IntegerDatabaseField(name="message_count"),
        "preview": StringDatabaseField(name="preview"),
        "created_at": DateTimeDatabaseField(name="created_at"),
    },
)


account_email_thread_links: PostgresTable = PostgresTable(
    name="_account_email_thread_links",
    postgres_table_name="posthog_conversations_email_thread_account_link",
    access_scope="ticket",
    resource_level_access_only=True,
    predicates=[parse_expr("account_id IN (SELECT toString(id) FROM system.accounts)")],
    description="Internal table linking customer email threads to accounts. Use `system.accounts.email_threads` instead.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Email thread account link UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "thread_id": UUIDDatabaseField(name="thread_id"),
        "account_id": StringDatabaseField(name="account_id"),
    },
)


account_custom_property_values: PostgresTable = PostgresTable(
    name="_account_custom_property_values",
    postgres_table_name="customer_analytics_custompropertyvalue",
    # Per-account deny filters used to arrive via the account-subquery predicate; with the
    # direct team guard they must be declared explicitly, filtering on the account FK.
    access_scope="account",
    access_control_id_field="account_id",
    description="Internal federated table (PostgreSQL `customer_analytics_custompropertyvalue`) of custom property values per account; not for direct querying — use `system.accounts.custom_properties`.",
    # Unlike the FK-only junction tables, this table has a real `team_id` column, so the
    # framework's standard `team_id = X` guard scopes it, and as a plain column comparison it is
    # pushed down into the federated PostgreSQL read, where the account-subquery predicate
    # cannot be. Soft-deleted rows stay pruned so superseded `value_*` data can't be read via
    # direct selection of this hidden backing table, matching the lazy join's filter.
    predicates=[
        # `NOT is_deleted` (not `is_deleted != true`): the predicate is pushed into the federated
        # PostgreSQL query, where comparing a boolean column to an integer literal is a type error.
        parse_expr("NOT is_deleted"),
    ],
    fields={
        "id": UUIDDatabaseField(name="id", description="Primary key of the custom property value row."),
        "team_id": IntegerDatabaseField(name="team_id"),
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


account_custom_property_values_history: PostgresTable = PostgresTable(
    name="_account_custom_property_values_history",
    postgres_table_name="customer_analytics_custompropertyvalue",
    access_scope="account",
    access_control_id_field="account_id",
    description="Internal federated table (PostgreSQL `customer_analytics_custompropertyvalue`) of every custom property value write per account, superseded rows included; not for direct querying — use `system.accounts.custom_properties_history`.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Primary key of the custom property value row."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "definition_id": UUIDDatabaseField(
            name="definition_id", description="Custom property definition this value is for."
        ),
        "account_id": UUIDDatabaseField(
            name="account_id", nullable=True, description="Account the value belongs to; join to `system.accounts.id`."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the value was written."),
        "is_deleted": BooleanDatabaseField(
            name="is_deleted", description="Whether this value has been superseded (soft-deleted)."
        ),
        "value_num": FloatDatabaseField(
            name="value_num", nullable=True, description="Numeric value, if a numeric type."
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


def _account_custom_properties_history_select(fields_accessed: dict[str, list[str | int]]) -> ast.SelectQuery:
    r"""Aggregate each account's numeric custom property value writes into ordered histories.

    Inner select: one row per (account, definition) with the sorted array of
    (unix timestamp, value) points — active and superseded rows alike, since every write is
    a data point. Outer select: each requested key
    (`accounts.custom_properties_history.values.\`<id>\``, arriving as `values___<id>`) is
    materialized as its own column via `anyIf` — a lazy-join subquery can't JSON-extract
    after the fact.
    """
    inner = parse_select(
        # The 180-day horizon caps the federated scan; UI look-back presets top out at 90 days.
        # The active (non-deleted) row is always included — at most one per (account, definition) —
        # so a value last written before the horizon still reaches the cell as the current value.
        """
        SELECT
            cpv.account_id AS account_id,
            toString(cpv.definition_id) AS definition_key,
            arraySort(groupArray(tuple(toUnixTimestamp(cpv.created_at), cpv.value_num))) AS points
        FROM system._account_custom_property_values_history AS cpv
        WHERE isNotNull(cpv.value_num) AND (cpv.created_at >= now() - INTERVAL 180 DAY OR NOT cpv.is_deleted)
        GROUP BY cpv.account_id, cpv.definition_id
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
                        "anyIf(points, definition_key = {key})",
                        placeholders={"key": ast.Constant(value=str(chain[1]))},
                    ),
                )
            )
        elif chain == ["values"]:
            select.append(
                parse_expr("toJSONString(mapFromArrays(groupArray(definition_key), groupArray(points))) AS values")
            )
    return ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=inner),
        group_by=[ast.Field(chain=["account_id"])],
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


def _account_meetings_select() -> ast.SelectQuery | ast.SelectSetQuery:
    return parse_select(
        """
        SELECT
            account_id,
            count() AS count,
            max(start_time) AS latest_start_time,
            toJSONString(arrayMap(row -> map(
                'id', row.2,
                'title', row.3,
                'start_time', row.1,
                'end_time', row.4,
                'status', row.5,
                'organizer_email', row.6
            ), arraySlice(arrayReverseSort(groupArray(tuple(
                toString(start_time),
                toString(id),
                title,
                ifNull(toString(end_time), ''),
                status,
                organizer_email
            ))), 1, 10))) AS recent
        FROM system._account_meetings
        WHERE isNotNull(account_id)
        GROUP BY account_id
        """
    )


def _account_slack_summaries_select() -> ast.SelectQuery | ast.SelectSetQuery:
    return parse_select(
        """
        SELECT
            account_id,
            count() AS count,
            max(generated_at) AS latest_generated_at,
            toJSONString(arrayMap(row -> map(
                'id', row.2,
                'slack_channel_id', row.3,
                'cadence', row.4,
                'period_start', row.5,
                'period_end', row.1,
                'content', row.6,
                'message_count', row.7,
                'generated_at', row.8
            ), arraySlice(arrayReverseSort(groupArray(tuple(
                toString(period_end),
                toString(id),
                slack_channel_id,
                cadence,
                toString(period_start),
                content,
                toString(message_count),
                toString(generated_at)
            ))), 1, 10))) AS recent
        FROM system._account_channel_summaries
        GROUP BY account_id
        """
    )


def _account_feature_requests_select() -> ast.SelectQuery | ast.SelectSetQuery:
    return parse_select(
        """
        SELECT
            link.account_id AS account_id,
            count() AS count,
            max(request.updated_at) AS last_updated_at,
            toJSONString(arrayMap(row -> map(
                'id', row.2,
                'title', row.3,
                'status', row.4,
                'priority', row.5,
                'updated_at', row.1
            ), arraySlice(arrayReverseSort(groupArray(tuple(
                toString(request.updated_at),
                toString(request.id),
                request.title,
                request.status,
                ifNull(request.priority, '')
            ))), 1, 10))) AS recent
        FROM system.feature_request_account_links AS link
        INNER JOIN system.feature_requests AS request ON request.id = link.feature_request_id
        WHERE isNull(request.archived_at)
        GROUP BY link.account_id
        """
    )


def _account_support_tickets_select() -> ast.SelectQuery | ast.SelectSetQuery:
    return parse_select(
        """
        SELECT
            account.id AS account_id,
            count() AS count,
            max(ticket.last_message_at) AS last_message_at,
            toJSONString(arrayMap(row -> map(
                'id', row.2,
                'ticket_number', row.3,
                'channel_source', row.4,
                'status', row.5,
                'priority', row.6,
                'last_message_at', row.1
            ), arraySlice(arrayReverseSort(groupArray(tuple(
                toString(ifNull(ticket.last_message_at, ticket.created_at)),
                ticket.id,
                toString(ticket.ticket_number),
                ticket.channel_source,
                ticket.status,
                ifNull(ticket.priority, '')
            ))), 1, 10))) AS recent
        FROM system.accounts AS account
        INNER JOIN system.support_tickets AS ticket ON ticket.organization_id = account.external_id
        WHERE isNotNull(account.external_id)
        GROUP BY account.id
        """
    )


def _account_email_threads_select() -> ast.SelectQuery | ast.SelectSetQuery:
    return parse_select(
        """
        SELECT
            toUUID(link.account_id) AS account_id,
            count() AS count,
            max(thread.last_message_at) AS last_message_at,
            toJSONString(arrayMap(row -> map(
                'id', row.2,
                'subject', row.3,
                'preview', row.4,
                'first_message_at', row.5,
                'last_message_at', row.1,
                'message_count', row.6
            ), arraySlice(arrayReverseSort(groupArray(tuple(
                toString(ifNull(thread.last_message_at, thread.created_at)),
                toString(thread.id),
                thread.subject,
                thread.preview,
                ifNull(toString(thread.first_message_at), ''),
                toString(thread.message_count)
            ))), 1, 10))) AS recent
        FROM system._account_email_thread_links AS link
        INNER JOIN system._account_email_threads AS thread ON thread.id = link.thread_id
        GROUP BY link.account_id
        """
    )


def _require_ticket_access(context: HogQLContext, table_name: str) -> None:
    database = context.database
    if database is None or database.is_table_access_denied("system.support_tickets"):
        raise TableAccessDeniedError(table_name)
    if database.user_access_control and not database.user_access_control.check_access_level_for_resource(
        "ticket", "viewer"
    ):
        raise TableAccessDeniedError(table_name)


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


class _AccountCustomPropertiesHistoryTable(LazyTable):
    description: str = (
        "Internal aggregating table backing `system.accounts.custom_properties_history`: each "
        "account's numeric custom property write history, keyed by definition id."
    )
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(
            name="account_id", description="Account this history belongs to; join to `system.accounts.id`."
        ),
        "values": StringJSONDatabaseField(
            name="values",
            description=(
                "JSON object keyed by custom property definition id; each value is the property's "
                "write history over the last 180 days (plus the current value, however old) as "
                "[unix timestamp, value] pairs sorted ascending — numeric properties only. Read one "
                "property with accounts.custom_properties_history.values.`<definition_id>` "
                "(backtick-quote the id). Get definition ids and names from "
                "system.custom_property_definitions."
            ),
        ),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return _account_custom_properties_history_select(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_custom_properties_history"

    def to_printed_hogql(self) -> str:
        return "account_custom_properties_history"


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


class _AccountMeetingsTable(LazyTable):
    description: str = "Meeting summaries for each account. `recent` contains the newest 10 meetings."
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(name="account_id", description="Account the meetings belong to."),
        "count": IntegerDatabaseField(name="count", description="Number of meetings linked to the account."),
        "latest_start_time": DateTimeDatabaseField(
            name="latest_start_time", nullable=True, description="Start time of the latest meeting."
        ),
        "recent": StringJSONDatabaseField(name="recent", description="Newest 10 meeting summaries."),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return _account_meetings_select()

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_meetings"

    def to_printed_hogql(self) -> str:
        return "account_meetings"


class _AccountSlackSummariesTable(LazyTable):
    description: str = "Slack summaries for each account. `recent` contains the newest 10 summaries."
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(name="account_id", description="Account the Slack summaries belong to."),
        "count": IntegerDatabaseField(name="count", description="Number of Slack summaries for the account."),
        "latest_generated_at": DateTimeDatabaseField(
            name="latest_generated_at", nullable=True, description="When the latest Slack summary was generated."
        ),
        "recent": StringJSONDatabaseField(name="recent", description="Newest 10 Slack summaries."),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return _account_slack_summaries_select()

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_slack_summaries"

    def to_printed_hogql(self) -> str:
        return "account_slack_summaries"


class _AccountFeatureRequestsTable(LazyTable):
    description: str = "Active feature requests linked to each account. `recent` contains the newest 10 requests."
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(name="account_id", description="Account the feature requests are linked to."),
        "count": IntegerDatabaseField(
            name="count", description="Number of active feature requests linked to the account."
        ),
        "last_updated_at": DateTimeDatabaseField(
            name="last_updated_at", nullable=True, description="When the latest linked feature request was updated."
        ),
        "recent": StringJSONDatabaseField(name="recent", description="Newest 10 active feature requests."),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        return _account_feature_requests_select()

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_feature_requests"

    def to_printed_hogql(self) -> str:
        return "account_feature_requests"


class _AccountSupportTicketsTable(LazyTable):
    description: str = "Support tickets linked to each account. `recent` contains the newest 10 tickets."
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(name="account_id", description="Account the support tickets belong to."),
        "count": IntegerDatabaseField(name="count", description="Number of support tickets linked to the account."),
        "last_message_at": DateTimeDatabaseField(
            name="last_message_at", nullable=True, description="When the latest support ticket message was sent."
        ),
        "recent": StringJSONDatabaseField(name="recent", description="Newest 10 support tickets."),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        _require_ticket_access(context, "system.support_tickets")
        return _account_support_tickets_select()

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_support_tickets"

    def to_printed_hogql(self) -> str:
        return "account_support_tickets"


class _AccountEmailThreadsTable(LazyTable):
    description: str = "Email threads linked to each account. `recent` contains the newest 10 threads."
    fields: dict[str, FieldOrTable] = {
        "account_id": UUIDDatabaseField(name="account_id", description="Account the email threads are linked to."),
        "count": IntegerDatabaseField(name="count", description="Number of email threads linked to the account."),
        "last_message_at": DateTimeDatabaseField(
            name="last_message_at", nullable=True, description="When the latest email message was sent."
        ),
        "recent": StringJSONDatabaseField(name="recent", description="Newest 10 email thread summaries."),
    }

    def lazy_select(
        self, table_to_add: LazyTableToAdd, context: HogQLContext, node: ast.SelectQuery
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        _require_ticket_access(context, "system._account_email_threads")
        return _account_email_threads_select()

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return "account_email_threads"

    def to_printed_hogql(self) -> str:
        return "account_email_threads"


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


def account_custom_properties_history_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.custom_properties_history`")
    return _join_on_account_id(_account_custom_properties_history_select(join_to_add.fields_accessed), join_to_add)


def account_relationships_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.relationships`")
    return _join_on_account_id(_account_relationships_select(join_to_add.fields_accessed), join_to_add)


def account_meetings_join(join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.meetings`")
    return _join_on_account_id(_account_meetings_select(), join_to_add)


def account_slack_summaries_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.slack_summaries`")
    return _join_on_account_id(_account_slack_summaries_select(), join_to_add)


def account_feature_requests_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.feature_requests`")
    return _join_on_account_id(_account_feature_requests_select(), join_to_add)


def account_support_tickets_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.support_tickets`")
    _require_ticket_access(context, "system.support_tickets")
    return _join_on_account_id(_account_support_tickets_select(), join_to_add)


def account_email_threads_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from `accounts.email_threads`")
    _require_ticket_access(context, "system._account_email_threads")
    return _join_on_account_id(_account_email_threads_select(), join_to_add)


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

account_custom_properties_history_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountCustomPropertiesHistoryTable(),
    resolver=ACCOUNT_CUSTOM_PROPERTIES_HISTORY,
)


account_relationships_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountRelationshipsTable(),
    resolver=ACCOUNT_RELATIONSHIPS,
)

account_meetings_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountMeetingsTable(),
    resolver=ACCOUNT_MEETINGS,
)

account_slack_summaries_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountSlackSummariesTable(),
    resolver=ACCOUNT_SLACK_SUMMARIES,
)

account_feature_requests_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountFeatureRequestsTable(),
    resolver=ACCOUNT_FEATURE_REQUESTS,
)

account_support_tickets_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountSupportTicketsTable(),
    resolver=ACCOUNT_SUPPORT_TICKETS,
)

account_email_threads_lazy_join: LazyJoin = LazyJoin(
    from_field=["id"],
    join_table=_AccountEmailThreadsTable(),
    resolver=ACCOUNT_EMAIL_THREADS,
)


account_relationship_definitions: PostgresTable = PostgresTable(
    name="account_relationship_definitions",
    postgres_table_name="customer_analytics_accountrelationshipdefinition",
    # Sub-resource of accounts; gated at the account resource level (see customer_analytics backend CLAUDE.md).
    access_scope="account",
    # Team-level definitions shared by every account, so a per-account grant never keys these rows.
    resource_level_access_only=True,
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
    access_control_creator_id_field="created_by_id",
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
        "churned_at": DateTimeDatabaseField(
            name="churned_at", nullable=True, description="When the account churned; NULL if it has not churned."
        ),
        "ignored_at": DateTimeDatabaseField(
            name="ignored_at", nullable=True, description="When Track Rules ignored the account; NULL if tracked."
        ),
        "tags": account_tags_lazy_join,
        "notebooks": account_notebooks_lazy_join,
        "custom_properties": account_custom_properties_lazy_join,
        "custom_properties_history": account_custom_properties_history_lazy_join,
        "relationships": account_relationships_lazy_join,
        "meetings": account_meetings_lazy_join,
        "slack_summaries": account_slack_summaries_lazy_join,
        "feature_requests": account_feature_requests_lazy_join,
        "support_tickets": account_support_tickets_lazy_join,
        "email_threads": account_email_threads_lazy_join,
    },
)


feature_request_product_areas: PostgresTable = PostgresTable(
    name="feature_request_product_areas",
    postgres_table_name="customer_analytics_featurerequestproductarea",
    access_scope="customer_analytics",
    description="Product areas used to categorize Customer analytics feature requests, one row per team-defined area.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Product area UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "name": StringDatabaseField(name="name", description="Team-maintained product area name."),
        "display_order": IntegerDatabaseField(
            name="display_order", description="Position in product area selectors. Lower values appear first."
        ),
        "_is_active": BooleanDatabaseField(name="is_active", hidden=True),
        "is_active": ExpressionField(
            name="is_active",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_active"])]),
            description="1 if editors can select this area for new requests, 0 otherwise.",
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="PostHog user who created the product area."
        ),
        "updated_by_id": IntegerDatabaseField(
            name="updated_by_id", nullable=True, description="PostHog user who last updated the product area."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the product area was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the product area was last updated."),
    },
)


feature_request_account_links: PostgresTable = PostgresTable(
    name="feature_request_account_links",
    postgres_table_name="customer_analytics_featurerequestaccountlink",
    access_scope="account",
    access_control_id_field="account_id",
    predicates=[parse_expr("unlinked_at IS NULL")],
    description="Active links between Customer analytics feature requests and affected accounts, one row per request and account pair.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Feature request account link UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "feature_request_id": UUIDDatabaseField(
            name="feature_request_id",
            description="Feature request this link belongs to. Join to `system.feature_requests.id`.",
        ),
        "account_id": UUIDDatabaseField(
            name="account_id", description="Affected account. Join to `system.accounts.id`."
        ),
        "unlinked_at": DateTimeDatabaseField(name="unlinked_at", nullable=True, hidden=True),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the account was first linked."),
        "updated_at": DateTimeDatabaseField(
            name="updated_at", nullable=True, description="When the account link was last changed."
        ),
    },
)


feature_requests: PostgresTable = PostgresTable(
    name="feature_requests",
    postgres_table_name="customer_analytics_featurerequest",
    access_scope="customer_analytics",
    predicates=[parse_expr("id IN (SELECT feature_request_id FROM system.feature_request_account_links)")],
    description="Customer analytics feature requests linked to at least one account the caller can access, one row per request.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Feature request UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "title": StringDatabaseField(name="title", description="Customer-facing request title."),
        "description": StringDatabaseField(name="description", description="Customer-facing description in Markdown."),
        "status": StringDatabaseField(
            name="status",
            description="Current lifecycle status: 'requested', 'planned', 'completed', 'wont_fix', or 'duplicate'.",
        ),
        "priority": StringDatabaseField(
            name="priority", nullable=True, description="Manual priority: 'high', 'medium', 'low', or NULL."
        ),
        "archived_at": DateTimeDatabaseField(
            name="archived_at", nullable=True, description="When the request was archived. NULL while active."
        ),
        "archived_by_id": IntegerDatabaseField(
            name="archived_by_id", nullable=True, description="PostHog user who archived the request."
        ),
        "version": IntegerDatabaseField(
            name="version", description="Version required for optimistic concurrency on mutations."
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="PostHog user who created the request."
        ),
        "updated_by_id": IntegerDatabaseField(
            name="updated_by_id", nullable=True, description="PostHog user who last updated the request."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the request was created."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the request was last updated."),
    },
)


feature_request_evidence: PostgresTable = PostgresTable(
    name="feature_request_evidence",
    postgres_table_name="customer_analytics_featurerequestevidence",
    access_scope="customer_analytics",
    predicates=[parse_expr("account_link_id IN (SELECT id FROM system.feature_request_account_links)")],
    description="Evidence recorded for active feature request account links, one row per evidence item.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Evidence UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "account_link_id": UUIDDatabaseField(
            name="account_link_id",
            description="Request and account pair this evidence supports. Join to `system.feature_request_account_links.id`.",
        ),
        "summary": StringDatabaseField(name="summary", description="Internal summary of the request evidence."),
        "customer_quote": StringDatabaseField(
            name="customer_quote", description="Customer quote kept with this evidence item."
        ),
        "source": StringDatabaseField(name="source", description="Free-form name of the evidence source."),
        "source_url": StringDatabaseField(
            name="source_url", description="HTTP or HTTPS link to the source, or an empty string."
        ),
        "requested_on": DateDatabaseField(
            name="requested_on", nullable=True, description="Date the account made the request, or NULL when unknown."
        ),
        "_image_ids": StringArrayDatabaseField(name="image_ids", hidden=True),
        "image_ids": ExpressionField(
            name="image_ids",
            expr=parse_expr("arrayMap(image_id -> toString(image_id), _image_ids)"),
            description="Uploaded image UUIDs attached to this evidence item, in display order.",
        ),
        "created_by_id": IntegerDatabaseField(
            name="created_by_id", nullable=True, description="PostHog user who added the evidence."
        ),
        "updated_by_id": IntegerDatabaseField(
            name="updated_by_id", nullable=True, description="PostHog user who last updated the evidence."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the evidence was added."),
        "updated_at": DateTimeDatabaseField(name="updated_at", description="When the evidence was last updated."),
    },
)


feature_request_product_area_links: PostgresTable = PostgresTable(
    name="feature_request_product_area_links",
    postgres_table_name="customer_analytics_featurerequestproductarealink",
    access_scope="customer_analytics",
    predicates=[parse_expr("feature_request_id IN (SELECT id FROM system.feature_requests)")],
    description="Links between visible feature requests and product areas, one row per request and area pair.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Feature request product area link UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "feature_request_id": UUIDDatabaseField(
            name="feature_request_id", description="Feature request. Join to `system.feature_requests.id`."
        ),
        "product_area_id": UUIDDatabaseField(
            name="product_area_id", description="Product area. Join to `system.feature_request_product_areas.id`."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the product area was linked."),
    },
)


feature_request_history: PostgresTable = PostgresTable(
    name="feature_request_history",
    postgres_table_name="customer_analytics_featurerequesthistory",
    access_scope="customer_analytics",
    predicates=[parse_expr("feature_request_id IN (SELECT id FROM system.feature_requests)")],
    description="Change history for visible Customer analytics feature requests, one row per successful save.",
    fields={
        "id": UUIDDatabaseField(name="id", description="Feature request history entry UUID."),
        "team_id": IntegerDatabaseField(name="team_id"),
        "feature_request_id": UUIDDatabaseField(
            name="feature_request_id", description="Feature request that changed. Join to `system.feature_requests.id`."
        ),
        "_changes": StringJSONDatabaseField(name="changes", hidden=True),
        "changed_fields": ExpressionField(
            name="changed_fields",
            expr=parse_expr("arrayMap(change -> JSONExtractString(change, 'field'), JSONExtractArrayRaw(_changes))"),
            description="Names of the fields changed in this save. Before and after values are not exposed.",
        ),
        "_is_initial": BooleanDatabaseField(name="is_initial", hidden=True),
        "is_initial": ExpressionField(
            name="is_initial",
            expr=ast.Call(name="toInt", args=[ast.Field(chain=["_is_initial"])]),
            description="1 if this entry records the request's initial values, 0 otherwise.",
        ),
        "source": StringDatabaseField(name="source", description="System that recorded the change."),
        "actor_id": IntegerDatabaseField(
            name="actor_id", nullable=True, description="PostHog user who changed the request."
        ),
        "changed_at": DateTimeDatabaseField(name="changed_at", description="When the request changed."),
    },
)


custom_property_definitions: PostgresTable = PostgresTable(
    name="custom_property_definitions",
    postgres_table_name="customer_analytics_custompropertydefinition",
    # Sub-resource of accounts; gated at the account resource level (see customer_analytics backend CLAUDE.md).
    access_scope="account",
    # Team-level definitions shared by every account, so a per-account grant never keys these rows.
    resource_level_access_only=True,
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
