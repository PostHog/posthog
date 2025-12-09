# MetaHog - Direct Query Architecture

> Technical architecture for direct SQL querying against external databases

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                           PostHog Frontend                               │
│  ┌─────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐  │
│  │ Database        │  │ Monaco SQL Editor   │  │ Schema Browser      │  │
│  │ Selector        │  │                     │  │ (tables with ⚡)    │  │
│  └────────┬────────┘  └──────────┬──────────┘  └──────────┬──────────┘  │
│           │                      │                        │              │
│           └──────────────────────┼────────────────────────┘              │
│                                  ▼                                       │
│                    ┌──────────────────────────┐                          │
│                    │   directQueryLogic.ts    │                          │
│                    │   (Kea state manager)    │                          │
│                    └────────────┬─────────────┘                          │
└─────────────────────────────────┼────────────────────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │  POST /api/query/        │
                    │  { kind: "DirectQuery" } │
                    └────────────┬─────────────┘
                                 │
┌────────────────────────────────┼────────────────────────────────────────┐
│                     PostHog Backend                                      │
│                                ▼                                         │
│              ┌──────────────────────────────┐                            │
│              │   process_query_model()      │                            │
│              │   posthog/api/services/      │                            │
│              │   query.py                   │                            │
│              └────────────┬─────────────────┘                            │
│                           │                                              │
│          ┌────────────────┴────────────────┐                             │
│          ▼                                 ▼                             │
│  ┌───────────────┐              ┌─────────────────────┐                  │
│  │ HogQL Query   │              │ DirectQuery Handler │                  │
│  │ (ClickHouse)  │              │                     │                  │
│  └───────┬───────┘              └──────────┬──────────┘                  │
│          │                                 │                             │
│          │                                 ▼                             │
│          │                      ┌─────────────────────┐                  │
│          │                      │ DirectQueryExecutor │                  │
│          │                      │ products/data_      │                  │
│          │                      │ warehouse/backend/  │                  │
│          │                      │ services/           │                  │
│          │                      └──────────┬──────────┘                  │
│          │                                 │                             │
└──────────┼─────────────────────────────────┼─────────────────────────────┘
           │                                 │
           ▼                                 ▼
    ┌──────────────┐              ┌─────────────────────┐
    │  ClickHouse  │              │  External Postgres  │
    │  (PostHog)   │              │  (query_only=True)  │
    └──────────────┘              └─────────────────────┘
```

## Component Details

### Frontend Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `DatabaseSelector` | `frontend/src/scenes/data-warehouse/editor/DatabaseSelector.tsx` | Dropdown to select HogQL or external database |
| `directQueryLogic` | `frontend/src/scenes/data-warehouse/editor/directQueryLogic.ts` | Kea logic for direct query state management |
| `QueryWindow` | `frontend/src/scenes/data-warehouse/editor/QueryWindow.tsx` | Monaco editor with database selector integration |
| `OutputPane` | `frontend/src/scenes/data-warehouse/editor/OutputPane.tsx` | Results display for both HogQL and direct queries |

### Backend Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `process_query_model()` | `posthog/api/services/query.py` | Routes queries by `kind` to appropriate handler |
| `DirectQueryExecutor` | `products/data_warehouse/backend/services/direct_query_executor.py` | Executes SQL against external databases |
| `DirectQueryViewSet` | `products/data_warehouse/backend/api/direct_query.py` | REST endpoints for sources and schema |
| `ExternalDataSource` | `products/data_warehouse/backend/models/external_data_source.py` | Stores connection details with `query_only` flag |

### Schema Types

| Type | Language | File |
|------|----------|------|
| `DirectQuery` | TypeScript | `frontend/src/queries/schema/schema-general.ts` |
| `DirectQueryResponse` | TypeScript | `frontend/src/queries/schema/schema-general.ts` |
| `DirectQuery` | Python | `posthog/schema.py` (generated) |
| `DirectQueryResponse` | Python | `posthog/schema.py` (generated) |

## Data Flow

### 1. Query Execution Flow

```text
User writes SQL → DatabaseSelector shows "Postgres" selected
                         ↓
              directQueryLogic.runQuery()
                         ↓
              Strip table prefix (postgres.film → film)
                         ↓
              api.query({
                kind: NodeKind.DirectQuery,
                source_id: "uuid...",
                query: "SELECT * FROM film"
              })
                         ↓
              POST /api/projects/@current/query/
                         ↓
              process_query_model() routes to DirectQuery handler
                         ↓
              DirectQueryExecutor.execute()
                         ↓
              psycopg connects to external Postgres
                         ↓
              Results returned as DirectQueryResponse
                         ↓
              OutputPane displays results
```

### 2. Schema Discovery Flow

```text
Source created with query_only=True
              ↓
GET /api/environments/@current/direct_query/schema/{source_id}
              ↓
DirectQueryExecutor.get_schema()
              ↓
Query information_schema.columns
              ↓
Map PostgreSQL types → HogQL types
              ↓
Create virtual DataWarehouseTable entries (is_direct_query=True)
              ↓
Tables appear in schema browser with ⚡ icon
```

## Key Design Decisions

### 1. Unified Query API

All queries go through `/api/query/` with a `kind` discriminator:

```python
# posthog/api/services/query.py
def process_query_model(team, query_json, ...):
    kind = query_json.get("kind")

    if kind == "DirectQuery":
        return _process_direct_query(team, query_json)
    elif kind == "HogQLQuery":
        return _process_hogql_query(team, query_json)
    # ... other query types
```

**Why?** Follows existing PostHog patterns for `HogQLQuery`, `TrendsQuery`, etc. Makes DirectQuery a first-class query type.

### 2. Query-Only Sources

Extended `ExternalDataSource` with `query_only=True` flag instead of creating a new model:

```python
# ExternalDataSource model
query_only = models.BooleanField(default=False)
```

**Why?** Reuses existing connection storage, encryption, SSH tunnel support.

### 3. Virtual Tables with `is_direct_query` Flag

```python
# DataWarehouseTable model (in-memory, not persisted)
is_direct_query: bool = False
```

**Why?** Allows direct query tables to appear in schema browser with visual differentiation.

### 4. Table Prefix Stripping

Frontend auto-strips source type prefix before sending to backend:

```typescript
// postgres.film → film
const tablePrefix = `${source.source_type.toLowerCase()}.`
if (query.toLowerCase().includes(tablePrefix)) {
    query = query.replace(new RegExp(tablePrefix, 'gi'), '')
}
```

**Why?** HogQL uses prefixed table names (`postgres.film`), but external databases expect unprefixed (`film`).

## Database Support

| Database | Status | Connection Method |
|----------|--------|-------------------|
| PostgreSQL | ✅ Supported | psycopg (direct) |
| MySQL | 🔮 Future | - |
| ClickHouse | 🔮 Future | - |
| BigQuery | 🔮 Future | - |

## Security Considerations

| Concern | Current State | Future Improvement |
|---------|---------------|-------------------|
| Query timeout | ⚠️ Not implemented | Add `statement_timeout` |
| Row limits | ✅ Default 1000 | Configurable per source |
| Read-only | ⚠️ Not enforced | Force read-only connections |
| SQL injection | ✅ Parameterized queries | - |
| Credential encryption | ✅ Fernet encryption | - |
| SSH tunnels | ✅ Supported | - |

## API Endpoints

### Unified Query API

```text
POST /api/projects/@current/query/
Body: {
    "kind": "DirectQuery",
    "source_id": "uuid",
    "query": "SELECT * FROM film LIMIT 10"
}
Response: {
    "columns": ["film_id", "title", "description"],
    "results": [[1, "ACADEMY DINOSAUR", "..."], ...],
    "types": ["INTEGER", "STRING", "STRING"]
}
```

### Source Management

```text
GET  /api/environments/@current/direct_query/sources
     Returns: List of query-capable sources

GET  /api/environments/@current/direct_query/schema/{source_id}
     Returns: Tables and columns for schema browser
```

## Type Mapping

PostgreSQL types are mapped to HogQL types for schema display:

| PostgreSQL | HogQL |
|------------|-------|
| integer, bigint, smallint | INTEGER |
| numeric, decimal, real, double | FLOAT |
| varchar, char, text | STRING |
| boolean | BOOLEAN |
| date | DATE |
| timestamp, timestamptz | DATETIME |
| json, jsonb | JSON |
| uuid | UUID |
| array types | ARRAY |

## File Structure

```text
posthog/
├── api/
│   └── services/
│       └── query.py                    # DirectQuery handler in process_query_model()
├── schema.py                           # Generated Python types
│
products/data_warehouse/backend/
├── api/
│   └── direct_query.py                 # REST endpoints
├── models/
│   └── external_data_source.py         # query_only field
├── services/
│   └── direct_query_executor.py        # SQL execution
└── migrations/
    └── 0012_externaldatasource_query_only.py

frontend/src/
├── queries/schema/
│   └── schema-general.ts               # DirectQuery types
└── scenes/data-warehouse/editor/
    ├── DatabaseSelector.tsx            # Database dropdown
    ├── directQueryLogic.ts             # Kea logic
    ├── QueryWindow.tsx                 # Monaco integration
    └── OutputPane.tsx                  # Results display
```

## Testing

### Manual Testing

1. Start Pagila demo database:

   ```bash
   cd ~/Documents/GitHub/pagila && docker compose up -d
   ```

2. Add Postgres source with "Query only" checkbox in Data Warehouse UI

3. Select database from dropdown in SQL editor

4. Run query: `SELECT * FROM postgres.film LIMIT 10`

### Automated Tests (TODO)

- [ ] `DirectQueryExecutor` unit tests
- [ ] API endpoint integration tests
- [ ] Frontend logic tests for `directQueryLogic`
- [ ] Schema discovery tests

## Related Documentation

- [PLAN.md](./PLAN.md) - Implementation plan and phases
- [RESEARCH.md](./RESEARCH.md) - Codebase exploration notes
- [IMPLEMENTATION.md](./IMPLEMENTATION.md) - Detailed implementation status
