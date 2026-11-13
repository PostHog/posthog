import json
from typing import TYPE_CHECKING, Any

import structlog

from posthog.hogql import ast
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    IntegerDatabaseField,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    StringJSONDatabaseField,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.database.schema.information_schema import (
    _INTEGER,
    _NULLABLE_DATETIME,
    _NULLABLE_INTEGER,
    _NULLABLE_STRING,
    _STRING,
    _constant_rows_select,
)

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

logger = structlog.get_logger(__name__)

# Rows are inlined in the query text, so the cap keeps the query small. The newest rows win.
MAX_INTEGRATION_ROWS = 500

_COLUMNS: list[tuple[str, str]] = [
    ("id", _INTEGER),
    ("team_id", _INTEGER),
    ("kind", _STRING),
    ("integration_id", _NULLABLE_STRING),
    ("config", _STRING),
    ("errors", _STRING),
    ("created_at", _NULLABLE_DATETIME),
    ("created_by_id", _NULLABLE_INTEGER),
]


def load_integration_rows(context: "HogQLContext") -> list[list[Any]]:
    """The rows of the current team, from the integrations SDK, once per query.

    Only non-secret columns leave the SDK: `sensitive_config` and tokens are never read here.
    """
    if context.system_integrations_rows is not None:
        return context.system_integrations_rows

    rows: list[list[Any]] = []
    if context.team_id is not None:
        # Deferred: the SDK imports the Integration model, which imports the HogQL package.
        from posthog.integrations import IntegrationManager  # noqa: PLC0415

        records = IntegrationManager.any.with_source_rows().list(context.team_id, newest_first=True)
        if len(records) > MAX_INTEGRATION_ROWS:
            logger.warning(
                "system.integrations: row cap reached",
                team_id=context.team_id,
                total=len(records),
                cap=MAX_INTEGRATION_ROWS,
            )
        rows = [
            [
                record.id,
                record.team_id,
                record.kind,
                record.integration_id,
                json.dumps(dict(record.config), default=str),
                record.errors,
                record.created_at.isoformat(),
                record.created_by_id,
            ]
            for record in records[:MAX_INTEGRATION_ROWS]
        ]

    context.system_integrations_rows = rows
    return rows


def _json_read(chain: list[str | int]) -> ast.Expr:
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


class IntegrationsTable(PostgresTable, LazyTable):
    """`system.integrations`.

    The rows live in the integrations SDK, not in a Postgres table. It extends `PostgresTable` only
    to keep the table in the system-table access control (`access_scope`). The lazy resolution
    replaces it with constant rows, so no Postgres function call is ever printed for it.
    """

    # The rows have no Postgres table: the SDK owns the storage.
    postgres_table_name: str = ""
    # Object-level grants never key integration rows, so the table needs resource-level access.
    resource_level_access_only: bool = True

    def lazy_select(self, table_to_add: LazyTableToAdd, context: "HogQLContext", node: Any) -> ast.SelectQuery:
        rows = _constant_rows_select(_COLUMNS, load_integration_rows(context))
        # A nested read such as `config.team.name` arrives as its own flat column of the subquery.
        nested = {alias: chain for alias, chain in table_to_add.fields_accessed.items() if len(chain) > 1}
        if not nested:
            return rows
        return ast.SelectQuery(
            select=[
                *(ast.Alias(alias=name, expr=ast.Field(chain=[name])) for name, _ in _COLUMNS),
                *(ast.Alias(alias=alias, expr=_json_read(chain)) for alias, chain in nested.items()),
            ],
            select_from=ast.JoinExpr(table=rows),
        )

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        return "integrations"

    def to_printed_hogql(self) -> str:
        return "integrations"


integrations = IntegrationsTable(
    name="integrations",
    access_scope="integration",
    description="Third-party integrations connected to the project (Slack, GitHub, etc.); one row per integration.",
    fields={
        "id": IntegerDatabaseField(name="id", description="Integration id."),
        "team_id": IntegerDatabaseField(name="team_id", hidden=True),
        "kind": StringDatabaseField(name="kind", description="Integration type, e.g. 'slack', 'github', 'salesforce'."),
        "integration_id": StringDatabaseField(
            name="integration_id", description="Identifier of the account/workspace in the external system."
        ),
        "config": StringJSONDatabaseField(name="config", description="JSON non-sensitive integration config."),
        "errors": StringDatabaseField(
            name="errors", description="Most recent error encountered using the integration."
        ),
        "created_at": DateTimeDatabaseField(name="created_at", description="When the integration was connected."),
        "created_by_id": IntegerDatabaseField(name="created_by_id", description="User who connected the integration."),
    },
)
