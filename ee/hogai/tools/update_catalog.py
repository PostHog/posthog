from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import AppendColumnNoteParams, AppendNodeNoteParams, RecordJoinParams
from products.catalog.backend.logic import UnknownTableError

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

UPDATE_CATALOG_TOOL_PROMPT = """
Append a user-attributed note to the team's catalog when the conversation has surfaced
something concrete about a table, column, or join. The catalog is the team's source of
truth for data semantics — every note you write here will be visible to future
PostHog AI conversations for this team via the read_data and execute_sql output.

Call this tool whenever you learn a fact about the team's data — either from what the
user says directly, or from what you can infer by combining their statements with the
insights, saved queries, and SQL you've already seen in this conversation. Concrete
examples:

  - The user clarifies a column's units, meaning, or what's filtered:
      "amount is in USD cents, not dollars"
      "this table excludes our staging traffic"
  - The user confirms the business meaning of a table you queried or an insight you saw:
      Looking at insight "MRR by Plan Tier" that queries stripe_charges.amount and the
      user says "yeah that's our revenue data" → both the table and the column are
      worth annotating.
  - The user describes a join — even casually — between two tables:
      "join customers with subscriptions on customer_id"
      "the orders table links to users via user_id"

Do NOT call for speculation or generic statements. Only record what the user has
actually told you or that you can ground in the conversation.

Three actions:
  - action="update_table" — append a note to a table's description.
  - action="update_column" — append a note to a column's description.
  - action="record_join" — record a declared join between two tables (with optional
    source / target column names).

All table names should be the same names you would use in `FROM <name>` in a SQL
query. The tool resolves the name through HogQL — if it's not a real table for this
team, the call will fail and you should reconsider.
""".strip()


class UpdateTableNoteArgs(BaseModel):
    """Append a note to a table-level description."""

    action: Literal["update_table"]
    table_name: str = Field(description="HogQL table name, e.g. 'events', 'stripe_charges', 'system.tables'.")
    note: str = Field(description="The factual note to record. One or two sentences.")


class UpdateColumnNoteArgs(BaseModel):
    """Append a note to a column-level description."""

    action: Literal["update_column"]
    table_name: str = Field(description="HogQL table name the column belongs to.")
    column_name: str = Field(description="Column name as it appears in the table's schema.")
    note: str = Field(description="The factual note to record. One or two sentences.")


class RecordJoinArgs(BaseModel):
    """Record a user-declared join between two tables.

    Leave source_column / target_column null for table-level lineage. The tool
    stores the edge with kind=declared_join and confidence=1.0 (auto-accepted).
    """

    action: Literal["record_join"]
    source_table: str = Field(description="HogQL name of the source (left) table.")
    target_table: str = Field(description="HogQL name of the target (right) table.")
    source_column: str | None = Field(default=None, description="Optional source-side join column.")
    target_column: str | None = Field(default=None, description="Optional target-side join column.")
    note: str = Field(description="What the user said about the join — units, FK semantics, caveats.")


class UpdateCatalogToolArgs(BaseModel):
    args: UpdateTableNoteArgs | UpdateColumnNoteArgs | RecordJoinArgs = Field(
        discriminator="action",
        description="Discriminated by 'action': update_table | update_column | record_join.",
    )


def _attribution_handle(user: User) -> str:
    """Short identifier embedded in the catalog note so the next reader can tell who said what.

    Prefers the email local-part (readable, stable per user); falls back to a UUID
    prefix when the user has no email (shouldn't normally happen).
    """
    if user.email:
        return user.email.split("@", 1)[0]
    return str(user.uuid)[:8]


def _build_attribution(user: User, when: date | None = None) -> str:
    when = when or date.today()
    return f"[@{_attribution_handle(user)} {when.isoformat()}]"


class UpdateCatalogTool(MaxTool):
    name: Literal["update_catalog"] = "update_catalog"
    description: str = UPDATE_CATALOG_TOOL_PROMPT
    args_schema: type[BaseModel] = UpdateCatalogToolArgs

    async def _arun_impl(
        self,
        args: UpdateTableNoteArgs | UpdateColumnNoteArgs | RecordJoinArgs,
    ) -> tuple[str, dict[str, Any]]:
        attribution = _build_attribution(self._user)
        try:
            if isinstance(args, UpdateTableNoteArgs):
                return await self._append_table_note(args, attribution)
            if isinstance(args, UpdateColumnNoteArgs):
                return await self._append_column_note(args, attribution)
            return await self._record_join(args, attribution)
        except UnknownTableError as e:
            raise MaxToolRetryableError(str(e))

    async def _append_table_note(self, args: UpdateTableNoteArgs, attribution: str) -> tuple[str, dict[str, Any]]:
        params = AppendNodeNoteParams(
            team_id=self._team.pk,
            table_name=args.table_name,
            note=args.note,
            attribution=attribution,
        )
        node = await database_sync_to_async(CatalogAPI.append_node_note)(self._team, params)
        return (
            f"Recorded note on `{args.table_name}`: {attribution} {args.note}",
            {"action": "update_table", "node_id": str(node.id), "table": args.table_name},
        )

    async def _append_column_note(self, args: UpdateColumnNoteArgs, attribution: str) -> tuple[str, dict[str, Any]]:
        params = AppendColumnNoteParams(
            team_id=self._team.pk,
            table_name=args.table_name,
            column_name=args.column_name,
            note=args.note,
            attribution=attribution,
        )
        column = await database_sync_to_async(CatalogAPI.append_column_note)(self._team, params)
        target = f"{args.table_name}.{args.column_name}"
        return (
            f"Recorded note on `{target}`: {attribution} {args.note}",
            {"action": "update_column", "column_id": str(column.id), "target": target},
        )

    async def _record_join(self, args: RecordJoinArgs, attribution: str) -> tuple[str, dict[str, Any]]:
        params = RecordJoinParams(
            team_id=self._team.pk,
            source_table=args.source_table,
            target_table=args.target_table,
            source_column=args.source_column,
            target_column=args.target_column,
            note=args.note,
            attribution=attribution,
        )
        edge = await database_sync_to_async(CatalogAPI.record_join)(self._team, params)
        source = f"{args.source_table}.{args.source_column}" if args.source_column else args.source_table
        target = f"{args.target_table}.{args.target_column}" if args.target_column else args.target_table
        return (
            f"Recorded join `{source}` ↔ `{target}`: {attribution} {args.note}",
            {"action": "record_join", "relationship_id": str(edge.id), "source": source, "target": target},
        )
