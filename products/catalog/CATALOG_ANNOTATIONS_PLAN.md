# Plan: Catalog annotations from AI conversations

## Product goal

Users share domain knowledge about their data while chatting with PostHog AI ("that amount column is in USD cents", "the stripe_charges table includes test data from staging"). Today this knowledge is lost when the conversation ends. We want the AI to notice when a user provides factual info about a table or column — or when it can infer meaning by combining user statements with insights, queries, and data visible in the conversation — and write it to the catalog as an **annotation**.

Annotations are append-only, attributed to the user who triggered them, and linked to the conversation for auditability. Multiple users can annotate the same table. We store `created_by` so that in the future we can weight annotations by user role (engineer vs sales rep), but we don't filter on it yet.

## How it works from the user's perspective

1. User opens PostHog AI and asks a question involving their data.
2. The AI does its normal work (builds insights, runs SQL, etc.).
3. If the AI learns something concrete about a table or column — from what the user says, from insight titles/descriptions visible in context, or from combining these signals — it silently calls the `annotate_catalog` tool.
4. The annotation is stored with: who said it, which conversation, and what table/column it's about.
5. Next time anyone (human or agent) queries `system.catalog_annotations`, those notes are there.

No approval dialog. No visible confirmation to the user. The agent synthesizes context from everything in the conversation (UI context injection gives it dashboard/insight titles and query results, plus the user's own words).

## Architecture context

### The catalog (current state on `semantic-layer` branch)

The catalog product lives in `products/catalog/`. Key pieces:

- **Models** (`products/catalog/backend/models.py`): `CatalogNode` (tables), `CatalogColumn` (columns), `CatalogRelationship` (edges), `CatalogMetric` (metrics), `CatalogTraversalRun` (audit).
- **Facade** (`products/catalog/backend/facade/api.py`): `CatalogAPI` is the only thing other products may import. Static methods delegate to `logic.py`.
- **Contracts** (`products/catalog/backend/facade/contracts.py`): Frozen dataclasses for DTOs and params. Input params use name-based lookup (not UUIDs) where appropriate.
- **Logic** (`products/catalog/backend/logic.py`): All DB operations. `upsert_node()`, `upsert_column()`, `propose_relationship()`, etc. All use `@transaction.atomic` and `update_or_create` for idempotency.
- **HogQL system tables** (`posthog/hogql/database/schema/system.py`): `system.tables`, `system.columns`, `system.relationships` exposed as `PostgresTable` instances registered in `SystemTables.children`. These UNION Postgres rows with synthesized rows from the in-process registry (`system_union.py`).
- **MCP tools** (`products/catalog/mcp/tools.yaml`): `catalog-nodes-create`, `catalog-columns-create`, `catalog-relationships-create` — used by the sandbox traversal agent, not the chat agent.

### The chat agent

- **Main loop** (`ee/hogai/core/agent_modes/executables.py`): `AgentExecutable.arun()` calls the LLM, `AgentToolsExecutable.arun()` executes tool calls. ROOT → ROOT_TOOLS → ROOT loop via LangGraph.
- **Tools** are `MaxTool` subclasses in `ee/hogai/tools/`. Each has `name` (Literal string), `description` (prompt), `args_schema` (Pydantic BaseModel), and `_arun_impl()`.
- **Tool registration**: `DEFAULT_TOOLS` in `ee/hogai/chat_agent/toolkit.py` lists tools available in ALL agent modes. Mode-specific tools go in `ee/hogai/core/agent_modes/presets/`. Some tools (like `ManageMemoriesTool`) are gated behind feature flags in `ChatAgentToolkit.tools`.
- **AssistantTool enum**: Defined in `frontend/src/queries/schema/schema-assistant-messages.ts` (TypeScript is source of truth), then regenerated into `posthog/schema.py` (Python). Every tool needs an entry in both.
- **Context injection** (`ee/hogai/context/context.py`): UI context (dashboards, insights, notebooks the user is viewing) is injected before the first message. The agent sees insight titles, descriptions, and query results in its context window.
- **Reference tool**: `ManageMemoriesTool` (`ee/hogai/tools/manage_memories.py`) is the closest pattern to follow — single-file MaxTool, calls DB via `database_sync_to_async`, returns `tuple[str, dict]`.

### Key pattern: how a MaxTool accesses team/user/conversation

```python
class SomeTool(MaxTool):
    async def _arun_impl(self, ...):
        self._team       # Team object
        self._user       # User object (who is chatting)
        # conversation_id from LangGraph config:
        # self._config.get("configurable", {}).get("thread_id")
```

## Implementation steps

### Step 1: Add `CatalogAnnotation` model

**File**: `products/catalog/backend/models.py`

Add at the bottom of the file, after `CatalogMetric`:

```python
class CatalogAnnotation(UUIDModel):
    """A user-provided note about a CatalogNode or CatalogColumn, contributed via AI chat."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    node = models.ForeignKey(CatalogNode, on_delete=models.CASCADE, related_name="annotations")
    column = models.ForeignKey(
        CatalogColumn, null=True, blank=True, on_delete=models.CASCADE, related_name="annotations"
    )
    content = models.TextField()
    created_by = models.ForeignKey(
        "posthog.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    conversation_id = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "node"]),
            models.Index(fields=["team", "column"]),
        ]
```

- `node` is always set (table-level annotation, or parent of the column).
- `column` is set only for column-level annotations.
- `created_by` tracks the user whose conversation triggered the annotation.
- `conversation_id` links to the chat thread for audit trail.
- Append-only — no `updated_at`, no update methods.

### Step 2: Create Django migration

**File**: `products/catalog/backend/migrations/0004_catalogannotation.py`

Generate with: `python manage.py makemigrations catalog`

This should depend on `("catalog", "0003_alter_catalognode_kind_and_more")` (check `max_migration.txt`). Purely additive (new table only), safe with zero downtime.

Update `products/catalog/backend/migrations/max_migration.txt` to the new migration number.

### Step 3: Add facade contracts

**File**: `products/catalog/backend/facade/contracts.py`

Add at the bottom:

```python
@dataclass(frozen=True)
class CatalogAnnotationDTO:
    id: UUID
    node_id: UUID
    column_id: UUID | None
    content: str
    created_by_id: int | None
    conversation_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class CreateAnnotationParams:
    team_id: int
    node_name: str          # LLM knows table names, not UUIDs
    column_name: str | None
    content: str
    created_by_id: int | None = None
    conversation_id: str | None = None
```

Name-based lookup (not UUID) because the LLM sees table/column names from `system.tables`/`system.columns`, not UUIDs.

### Step 4: Add logic layer function

**File**: `products/catalog/backend/logic.py`

Add imports for `CatalogAnnotation` and the new contracts. Add `to_annotation_dto()` and `create_annotation()`:

```python
def to_annotation_dto(annotation: CatalogAnnotation) -> contracts.CatalogAnnotationDTO:
    return contracts.CatalogAnnotationDTO(
        id=annotation.id,
        node_id=annotation.node_id,
        column_id=annotation.column_id,
        content=annotation.content,
        created_by_id=annotation.created_by_id,
        conversation_id=annotation.conversation_id,
        created_at=annotation.created_at,
    )


@transaction.atomic
def create_annotation(params: contracts.CreateAnnotationParams) -> contracts.CatalogAnnotationDTO:
    node, _ = CatalogNode.objects.get_or_create(
        team_id=params.team_id,
        name=params.node_name,
        defaults={"kind": CatalogNode.Kind.POSTHOG_TABLE},
    )
    column = None
    if params.column_name:
        column = CatalogColumn.objects.filter(node=node, name=params.column_name).first()
        if column is None:
            column = CatalogColumn.objects.create(
                node=node, name=params.column_name, team_id=params.team_id
            )
    annotation = CatalogAnnotation.objects.create(
        team_id=params.team_id,
        node=node,
        column=column,
        content=params.content,
        created_by_id=params.created_by_id,
        conversation_id=params.conversation_id,
    )
    return to_annotation_dto(annotation)
```

`get_or_create` on the node means annotations work even for tables not yet cataloged by the traversal workflow. The `defaults={"kind": CatalogNode.Kind.POSTHOG_TABLE}` is a reasonable fallback — the traversal will update the kind when it runs.

### Step 5: Expose on facade API

**File**: `products/catalog/backend/facade/api.py`

Add imports for `CreateAnnotationParams` and `CatalogAnnotationDTO`. Add to `CatalogAPI`:

```python
@staticmethod
def create_annotation(params: CreateAnnotationParams) -> CatalogAnnotationDTO:
    return logic.create_annotation(params)
```

### Step 6: Create the MaxTool

**File**: `ee/hogai/tools/annotate_catalog.py` (new file)

Follow the `ManageMemoriesTool` pattern in `ee/hogai/tools/manage_memories.py`:

```python
from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.sync import database_sync_to_async

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import CreateAnnotationParams

from ee.hogai.tool import MaxTool

ANNOTATE_CATALOG_TOOL_PROMPT = """
Save a note about a data table or column to the team's catalog.
Use when you learn something concrete about a table or column during this conversation —
either from what the user says directly, or from what you can infer by combining their
statements with the insights, queries, and data you've seen in this conversation.

For example, if the user is looking at an insight titled "MRR by Plan Tier" that queries
stripe_charges.amount, and they confirm "yeah that's our revenue data", you now know
enough to annotate both the table (revenue/billing data) and the column (monetary, used
for MRR calculation).

Only call when you have concrete, factual information grounded in the conversation.
Do NOT call for speculation or things the user hasn't confirmed.

Examples of when to annotate:
- User says: "The stripe_charges table includes test data from our staging environment"
- User says: "The amount column in orders is in USD cents, not dollars"
- User confirms the business meaning of a table you queried or an insight you see
- You notice an insight title/description reveals what a table is used for, and the
  user's question confirms it

The annotation is attributed to the user and linked to this conversation.
""".strip()


class AnnotateCatalogToolArgs(BaseModel):
    table_name: str = Field(description="Name of the table as it appears in system.tables")
    column_name: str | None = Field(
        default=None, description="Column name, if the annotation is about a specific column"
    )
    content: str = Field(
        description="The annotation text — what you learned about this table or column"
    )


class AnnotateCatalogTool(MaxTool):
    name: Literal["annotate_catalog"] = "annotate_catalog"
    description: str = ANNOTATE_CATALOG_TOOL_PROMPT
    args_schema: type[BaseModel] = AnnotateCatalogToolArgs

    async def _arun_impl(
        self,
        table_name: str,
        column_name: str | None = None,
        content: str = "",
    ) -> tuple[str, dict[str, Any]]:
        conversation_id = (self._config.get("configurable") or {}).get("thread_id")

        result = await database_sync_to_async(CatalogAPI.create_annotation)(
            CreateAnnotationParams(
                team_id=self._team.pk,
                node_name=table_name,
                column_name=column_name,
                content=content,
                created_by_id=self._user.pk if self._user else None,
                conversation_id=conversation_id,
            )
        )
        target = f"{table_name}.{column_name}" if column_name else table_name
        return f"Annotation saved for {target}.", {"annotation_id": str(result.id)}
```

Key details:

- `self._team` and `self._user` are inherited from `MaxTool` — set during `create_tool_class()`.
- `self._config` is the LangGraph `RunnableConfig` — `thread_id` is the conversation UUID.
- Returns `tuple[str, dict]` — message string + artifact dict (same pattern as `ManageMemoriesTool`).

### Step 7: Expose annotations via HogQL system table

**File**: `posthog/hogql/database/schema/system.py`

Add a `catalog_annotations` PostgresTable near the existing catalog system tables (around line 1279). Follow the exact same pattern used for `catalog_tables`, `catalog_columns`, and `catalog_relationships`:

```python
catalog_annotations = PostgresTable(
    name="catalog_annotations",
    postgres_table_name="catalog_catalogannotation",
    access_scope="catalog",
    fields={
        "id": StringDatabaseField(name="id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "node_id": StringDatabaseField(name="node_id"),
        "column_id": StringDatabaseField(name="column_id", nullable=True),
        "content": StringDatabaseField(name="content"),
        "created_by_id": IntegerDatabaseField(name="created_by_id", nullable=True),
        "conversation_id": StringDatabaseField(name="conversation_id", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at"),
    },
)
```

Register in `SystemTables.children` dict:

```python
"catalog_annotations": TableNode(name="catalog_annotations", table=catalog_annotations),
```

No UNION ALL needed (unlike `tables`/`columns`/`relationships` which synthesize rows). Annotations only come from Postgres.

### Step 8: Register the tool in the AssistantTool enum

**File**: `frontend/src/queries/schema/schema-assistant-messages.ts`

Add `'annotate_catalog'` to the `AssistantTool` union type. Place it near `'manage_memories'`.

**Then regenerate** `posthog/schema.py` so `AssistantTool.ANNOTATE_CATALOG` exists. The generation command is typically `pnpm run generate:schema` or similar (check `package.json` scripts).

### Step 9: Export from tools **init**

**File**: `ee/hogai/tools/__init__.py`

Add:

```python
from .annotate_catalog import AnnotateCatalogTool
```

### Step 10: Add to DEFAULT_TOOLS

**File**: `ee/hogai/chat_agent/toolkit.py`

Add `AnnotateCatalogTool` to `DEFAULT_TOOLS` so it's available in all agent modes:

```python
DEFAULT_TOOLS: list[type[MaxTool]] = [
    ReadTaxonomyTool,
    ReadDataTool,
    SearchTool,
    ListDataTool,
    TodoWriteTool,
    SwitchModeTool,
    CreateFormTool,
    CreateNotebookTool,
    AnnotateCatalogTool,  # <-- add here
]
```

Also add the import at the top of the file.

Gate behind the catalog feature flag in `ChatAgentToolkit.tools` (same `FEATURE_FLAGS.CATALOG` used in `products/catalog/manifest.tsx`). Check how `ManageMemoriesTool` is gated behind `has_memory_tool_feature_flag` for the pattern — you'll need a similar `has_catalog_feature_flag` check, or check the flag directly via `posthoganalytics`.

### Step 11: Update system table tests

**File**: `posthog/hogql/database/schema/test/test_system_tables.py`

The existing tests validate the system table registry. Add `"catalog_annotations"` to whatever list of expected table names exists.

**File**: `posthog/hogql/database/test/__snapshots__/test_database.ambr`

The snapshot will need updating after adding the new system table. Run the tests and accept the snapshot update.

## What we are NOT doing (explicitly deferred)

- **Context injection**: No automatic injection of catalog descriptions into the prompt. The agent can query `system.tables` and `system.catalog_annotations` via `execute-sql` when it needs context.
- **Approval flow**: Annotations are append-only notes, not destructive. No `is_dangerous_operation` needed.
- **Deduplication**: If the agent writes the same annotation twice, both are stored. Fine for V1.
- **Quality filtering by user role**: We store `created_by` for future weighting, but don't filter on it yet.
- **Annotation display in the catalog UI**: Annotations exist in the DB and are queryable via HogQL, but we don't add them to the frontend catalog scenes.
- **Batch inference from existing insights/dashboards**: Crawling existing artifacts for catalog signal is a separate future workstream.

## Verification

1. **Unit test**: Test `create_annotation()` in logic.py — verify it creates the annotation, handles missing nodes (get_or_create), handles column-level annotations, sets attribution correctly.
2. **Tool test**: Test `AnnotateCatalogTool._arun_impl` creates the right annotation with user attribution and conversation_id.
3. **HogQL test**: Verify `SELECT * FROM system.catalog_annotations WHERE team_id = X` returns annotations after creation.
4. **Manual test**: Start dev (`./bin/start`), open PostHog AI, say something like "the events table timestamp column is in UTC" — verify the agent calls `annotate_catalog` and the annotation appears in `SELECT * FROM system.catalog_annotations`.
