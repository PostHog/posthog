# MetaHog - Phase 1 Plan

> Direct database connection and SQL querying for PostHog

## Goal

Enable users to connect to external databases (starting with Postgres) and run SQL queries directly against them from the PostHog SQL editor, without requiring batch import to ClickHouse.

## Success Criteria

- [x] Can add a Postgres connection via UI (reuse existing data warehouse source flow)
- [x] Can select a connected database as query target in SQL editor
- [x] Can execute SQL queries directly against the connected database
- [x] Can see schema (tables/columns) for connected databases
- [x] Results display in same format as HogQL queries

## Proof Points

1. **PostHog's local Postgres** - Query `posthog_person`, `posthog_team`, etc.
2. **Demo Pagila database** - External Postgres on port 5433 with DVD rental data

---

## High-Level Approach

### Option A: Extend ExternalDataSource (Recommended)

Add a "direct query" capability to existing data warehouse sources.

**Pros:**

- Reuses existing connection storage, encryption, SSH tunnel support
- Familiar UI flow for users
- Less new code

**Cons:**

- Conflates batch import and direct query use cases

### Option B: New DirectConnection Model

Create a separate model specifically for direct query connections.

**Pros:**

- Clean separation of concerns
- Purpose-built for direct queries

**Cons:**

- Duplicates connection management code
- New UI flow needed

### Decision: Option A

We'll extend the existing infrastructure. A source can support both batch import AND direct query, or just one.

---

## "Query Only" Source Flow

### Current Flow (Batch Import)

```text
Step 1: Select Postgres
Step 2: Enter connection details → Validate credentials
Step 3: Select tables to sync, configure sync type
Step 4: Import starts, schedules created
```

### New Flow (Query Only)

```text
Step 1: Select Postgres
Step 2: Enter connection details + [x] Query only → Validate credentials
Done! (skip table selection, no sync)
```

### Implementation

**Model Change:**

```python
# ExternalDataSource
query_only = models.BooleanField(default=False)
```

**Frontend Changes:**

1. Add toggle in SourceForm: "Query only (skip data sync)"
2. When `query_only` is checked:
   - Still validate credentials (verify connection works)
   - Skip `getDatabaseSchemas` call
   - Skip Step 3 (table selection)
   - Create source immediately with no schemas

**Backend Changes:**

1. Add `query_only` field to ExternalDataSource model
2. Modify create endpoint:
   - If `query_only=True`, don't require `schemas` payload
   - Don't create ExternalDataSchema records
   - Don't trigger Temporal workflows
3. Add to serializer for API responses

### User Flow Example

```text
User: "Add new data source" → Select "Postgres"

┌─────────────────────────────────────────────────┐
│ Link your data source                           │
├─────────────────────────────────────────────────┤
│ Connection string: [________________________]   │
│                                                 │
│ Host:     [localhost        ]                   │
│ Port:     [5433             ]                   │
│ Database: [pagila           ]                   │
│ User:     [postgres         ]                   │
│ Password: [••••••••         ]                   │
│ Schema:   [public           ]                   │
│                                                 │
│ ☑ Query only (skip data sync)                  │
│   Connect for direct SQL queries without        │
│   importing data to PostHog.                    │
│                                                 │
│ Table prefix: [dvd_rental    ]                  │
│                                                 │
│              [Cancel]  [Connect]                │
└─────────────────────────────────────────────────┘

→ Validates credentials
→ Creates source with query_only=True
→ Done! Source appears in SQL editor dropdown
```

---

## Phases

### Phase 1a: Query Only Source Creation ✅

- [x] Add `query_only` field to ExternalDataSource model
- [x] Create migration (`0012_externaldatasource_query_only.py`)
- [x] Modify backend create endpoint to handle query_only
- [x] Add "Query only" toggle to SourceForm
- [x] Modify sourceWizardLogic to skip schema selection for query_only

### Phase 1b: Direct Query Backend ✅

- [x] Create DirectQueryExecutor service (`products/data_warehouse/backend/services/direct_query_executor.py`)
- [x] Add `/direct_query/execute` API endpoint
- [x] Add `/direct_query/sources` API endpoint (list query-capable sources)
- [x] Add `/direct_query/schema/:id` API endpoint (schema discovery)

### Phase 1c: Frontend SQL Editor Integration ✅

**Approach: Database Selector + Direct Tables in Schema Browser**

We implemented a hybrid approach:

1. Database selector dropdown in SQL editor toolbar to switch between HogQL and external databases
2. Direct-query tables appear in the existing schema browser with visual differentiation (lightning bolt icon)
3. When an external database is selected, queries are routed to DirectQueryExecutor

**Key Components Implemented:**

1. **`directQueryLogic.ts`** - Kea logic for managing direct query state
   - Loads available query-only sources from API
   - Manages selected database state
   - Executes queries via DirectQueryExecutor API
   - Handles prefix stripping (e.g., `postgres.actor` → `actor`)

2. **`DatabaseSelector.tsx`** - Dropdown component in SQL editor toolbar
   - Shows "PostHog (HogQL)" as default option
   - Lists all query-only sources (e.g., "Postgres")
   - Syncs with URL params for shareable links

3. **Schema Browser Integration**
   - Direct-query tables appear under their source type (e.g., "postgres")
   - Tables shown with `is_direct_query=true` flag
   - Lightning bolt icon indicates direct query tables
   - Context menu has "Query (Direct)" option

4. **Query Execution Flow**
   - User selects external database from dropdown
   - User writes SQL (e.g., `SELECT * FROM postgres.actor`)
   - Frontend strips prefix (`postgres.`) before sending to API
   - API executes query directly against external Postgres
   - Results displayed in same format as HogQL queries

**Files Created/Modified:**

| File | Status | Purpose |
|------|--------|---------|
| `frontend/src/scenes/data-warehouse/editor/directQueryLogic.ts` | ✅ Created | Direct query state management |
| `frontend/src/scenes/data-warehouse/editor/DatabaseSelector.tsx` | ✅ Created | Database selector dropdown |
| `frontend/src/scenes/data-warehouse/editor/QueryWindow.tsx` | ✅ Modified | Integrated DatabaseSelector and RunButton logic |
| `frontend/src/scenes/data-warehouse/editor/multitabEditorLogic.tsx` | ✅ Modified | URL param handling, query routing |
| `frontend/src/scenes/data-warehouse/editor/OutputPane.tsx` | ✅ Modified | Display direct query results |
| `frontend/src/scenes/data-warehouse/editor/sidebar/QueryDatabase.tsx` | ✅ Modified | Direct query context menu |
| `frontend/src/scenes/urls.ts` | ✅ Modified | Added direct_query_source URL params |

### Phase 1d: Polish & Testing ✅

- [x] Error handling and timeouts - Errors displayed in output pane
- [x] Query result limits - Default 1000 rows, configurable via API
- [x] Test with demo Pagila database - Working end-to-end
- [x] Prefix stripping - Auto-strips source_type prefix from table names
- [x] Loading states - Proper loading indicators in dropdown and results

### Phase 1e: Unified Query API Integration ✅

Integrated DirectQuery into PostHog's unified `/query/` API pattern:

- [x] Add `DirectQuery` kind to `NodeKind` enum in TypeScript schema
- [x] Add `DirectQuery` and `DirectQueryResponse` interfaces
- [x] Generate Python schema via `pnpm schema:build`
- [x] Add DirectQuery handler in `process_query_model()` (`posthog/api/services/query.py`)
- [x] Update frontend to use `api.query({ kind: NodeKind.DirectQuery, ... })`
- [x] Add `is_direct_query` field to `DataWarehouseTable` model
- [x] Add PostgreSQL to HogQL type mapping for schema discovery
- [x] Source validation - fall back to HogQL if source ID not found

**Why unified API?** Follows the same pattern as `HogQLQuery`, `TrendsQuery`, etc. Makes DirectQuery a first-class query type in PostHog's architecture.

---

## Architecture

### Original (Database Selector) - Abandoned

```text
┌─────────────────────────────────────────────────────────────┐
│                      SQL Editor UI                          │
│  ┌─────────────────┐  ┌──────────────────────────────────┐ │
│  │ Database Select │  │ Monaco Editor                    │ │
│  │ - PostHog (HogQL)│  │ SELECT * FROM film LIMIT 10;    │ │
│  │ - Pagila (PG)   │  │                                  │ │
│  └─────────────────┘  └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### New (Direct Tables in Schema Browser)

```text
┌─────────────────────────────────────────────────────────────┐
│                      SQL Editor UI                          │
│  ┌─────────────────┐  ┌──────────────────────────────────┐ │
│  │ Schema Browser  │  │ Monaco Editor                    │ │
│  │                 │  │                                  │ │
│  │ PostHog Tables  │  │ SELECT * FROM pagila_film        │ │
│  │  └ events       │  │ LIMIT 10;                        │ │
│  │  └ persons      │  │                                  │ │
│  │                 │  │                                  │ │
│  │ Direct Tables ⚡│  │                                  │ │
│  │  └ pagila_film  │  │                                  │ │
│  │  └ pagila_actor │  │                                  │ │
│  │  └ pagila_rental│  │                                  │ │
│  └─────────────────┘  └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Query Execution                          │
│                                                             │
│  Parse query → Detect table references                      │
│                                                             │
│  if all tables are PostHog/ClickHouse:                      │
│    → HogQL → ClickHouse                                     │
│                                                             │
│  if any table is "direct":                                  │
│    → Translate to source SQL                                │
│    → DirectQueryExecutor → External DB                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
      ┌──────────────┐               ┌──────────────┐
      │  ClickHouse  │               │   External   │
      │  (PostHog)   │               │   Postgres   │
      └──────────────┘               └──────────────┘
```

---

## Open Questions

1. **Permissions**: Should direct query be limited to certain roles?
2. **Query limits**: Max rows? Timeout?
3. **Read-only**: Force read-only connections?
4. **Multiple databases**: Support MySQL, etc. later?
5. **Connection pooling**: Needed for performance?

## Decisions Made

| Question | Decision | Rationale |
|----------|----------|-----------|
| Start with which DB? | Postgres | Already have connection code |
| New model or extend? | Extend ExternalDataSource | Less duplication |
| Where to add UI? | Existing SQL editor | Familiar UX |

---

## Timeline

This is a hackathon - aiming for working demo, not production-ready.

- **Day 1**: Research (done), Backend executor + API
- **Day 2**: Frontend integration, testing
- **Demo**: Query external Postgres from PostHog SQL editor

---

## Related Docs

- [RESEARCH.md](./RESEARCH.md) - Codebase exploration and findings
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) - Detailed implementation specs
