# MetaHog - Direct Database Connection BI Layer

## Hackathon Research Notes

### Vision

Build an interactive BI visualization tool/layer for PostHog that allows direct SQL querying against external databases (starting with Postgres).

### Phases

1. **Phase 1: MetaHog** - Layer for making DB connections + Direct connection SQL query interface
2. **Phase 2: Hog + Looker** - Custom schema addons, HogQL -> Postgres parser+printer, BI UI with query builder
3. **Phase 3: Polish** - Improved UI (filtering, graphs), more database support
4. **Phase 4: Profit** - Rebuild insights on top of this

---

## Phase 1 Research

### Goal

- Store database connections (reuse existing patterns from data warehouse sources)
- Execute SQL directly against connected databases (not batch import)
- Schema discovery for connected databases
- Use existing SQL editor UI

### Proof Points

1. Local PostHog's Postgres (persons tables, etc.)
2. Demo Postgres via Docker with sample data

---

## Existing Codebase Analysis

### 1. Data Warehouse Source Models

**Location**: `products/data_warehouse/backend/models/`

Key models we can leverage:

| Model | File | Purpose |
|-------|------|---------|
| `ExternalDataSource` | `external_data_source.py` | Stores connection details (host, port, db, user, password, schema) |
| `Credential` | `credential.py` | Encrypted credential storage using Fernet |
| `SSHTunnel` | `ssh_tunnel.py` | SSH tunnel configuration for secure connections |

**Connection Storage Pattern**:

```python
# ExternalDataSource.job_inputs stores:
{
    "host": "localhost",
    "port": 5432,
    "database": "mydb",
    "user": "postgres",
    "password": "encrypted...",
    "schema": "public"
}
```

### 2. Postgres Connection Code

**Location**: `posthog/temporal/data_imports/sources/postgres/postgres.py`

Key functions to reuse/adapt:

```python
def get_schemas(host, database, user, password, schema, port):
    """Discovers tables and columns from Postgres database"""
    # Uses psycopg to connect and query information_schema
    # Returns: dict[table_name, list[tuple[column_name, data_type]]]

def validate_credentials(config, team_id):
    """Tests connection before saving"""
    # Returns: (is_valid, error_message)
```

### 3. Current Query Execution Flow

```text
User Query → HogQLQueryEditor.tsx
           ↓
    API: /api/projects/:id/query/
           ↓
    HogQL Parser → AST → ClickHouse SQL
           ↓
    ClickHouse Database
```

**Key insight**: Currently ALL queries go through HogQL → ClickHouse. External data is batch-imported to ClickHouse first.

### 4. SQL Editor Components

**Location**: `frontend/src/scenes/data-warehouse/editor/`

- `QueryWindow.tsx` - Main editor with Monaco
- `multitabEditorLogic.tsx` - State management, query execution
- `OutputPane.tsx` - Results display

### 5. Connection Form Components

**Location**: `frontend/src/scenes/data-warehouse/new/`

- `SourceForm.tsx` - Dynamic form for connection details
- `parseConnectionString.ts` - Parses postgres:// connection strings
- Already supports SSH tunnel configuration

---

## Implementation Plan

### Option A: Minimal - Add Direct Query Mode to Existing Sources

Extend `ExternalDataSource` to support a "direct query" mode alongside batch import.

**Pros**: Reuses existing models, UI, credential storage
**Cons**: Might conflate two different use cases

### Option B: New Model - DirectDatabaseConnection

Create a dedicated model for direct connections, separate from batch import sources.

**Pros**: Clean separation, purpose-built
**Cons**: More code, some duplication

### Recommended: Option A with Feature Flag

1. Add `supports_direct_query` field to `ExternalDataSource`
2. Create new API endpoint for direct query execution
3. Extend SQL editor to select target database
4. Route queries to appropriate backend

---

## Technical Requirements

### Backend

1. **New API Endpoint**: `/api/projects/:id/direct_query/`
   - Accept: `{ source_id, query }`
   - Execute SQL directly against source database
   - Return results in same format as HogQL queries

2. **Connection Pool Manager**
   - Reuse connections efficiently
   - Handle timeouts and connection limits
   - Support SSH tunnels

3. **Query Execution Service**

   ```python
   class DirectQueryExecutor:
       def execute(self, source: ExternalDataSource, query: str) -> QueryResult:
           # Get connection from pool
           # Execute query with timeout
           # Return results with column types
   ```

### Frontend

1. **Database Selector** in SQL editor
   - Dropdown to choose: "PostHog (HogQL)" vs connected databases
   - Show schema browser for selected database

2. **Schema Browser**
   - List tables from connected database
   - Show columns and types
   - Click to insert into query

### Security Considerations

- Query timeouts (prevent long-running queries)
- Row limits (prevent memory issues)
- Read-only connections where possible
- Audit logging for queries
- Rate limiting

---

## Files to Modify/Create

### Backend

| File | Action | Purpose |
|------|--------|---------|
| `products/data_warehouse/backend/models/external_data_source.py` | Modify | Add `supports_direct_query` field |
| `posthog/api/direct_query.py` | Create | New API endpoint |
| `posthog/warehouse/direct_query/executor.py` | Create | Query execution logic |
| `posthog/warehouse/direct_query/connection_pool.py` | Create | Connection management |

### Frontend

| File | Action | Purpose |
|------|--------|---------|
| `frontend/src/scenes/data-warehouse/editor/QueryWindow.tsx` | Modify | Add database selector |
| `frontend/src/scenes/data-warehouse/editor/directQueryLogic.ts` | Create | Logic for direct queries |
| `frontend/src/scenes/data-warehouse/editor/SchemaExplorer.tsx` | Create | Schema browser component |

---

## Demo Setup

### Option 1: Use PostHog's Postgres

PostHog's local dev already has Postgres with tables like:

- `posthog_person`
- `posthog_persondistinctid`
- `posthog_team`
- `posthog_organization`

Connection: `postgresql://posthog:posthog@localhost:5432/posthog`

### Option 2: Docker Demo Database

```yaml
# docker-compose.demo.yml
services:
  demo-postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: demo
      POSTGRES_USER: demo
      POSTGRES_PASSWORD: demo
    ports:
      - "5433:5432"
    volumes:
      - ./demo-data.sql:/docker-entrypoint-initdb.d/init.sql
```

Sample data could include:

- Sales/orders data
- User analytics
- Product catalog

---

## Detailed Implementation Plan for Phase 1

### Step 1: Backend - Direct Query Executor

Create a new service that can execute SQL directly against connected databases.

**File: `posthog/warehouse/direct_query/executor.py`**

```python
from typing import Any
import psycopg
from products.data_warehouse.backend.models import ExternalDataSource

class DirectQueryExecutor:
    def __init__(self, source: ExternalDataSource):
        self.source = source
        self.job_inputs = source.job_inputs

    def execute(self, query: str, timeout_ms: int = 30000) -> dict:
        """Execute SQL query and return results with column info."""
        connection = psycopg.connect(
            host=self.job_inputs["host"],
            port=self.job_inputs["port"],
            dbname=self.job_inputs["database"],
            user=self.job_inputs["user"],
            password=self.job_inputs["password"],
            sslmode="prefer",
            connect_timeout=15,
        )

        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SET statement_timeout = {timeout_ms}")
                cursor.execute(query)

                columns = [
                    {"name": desc.name, "type": desc.type_code}
                    for desc in cursor.description or []
                ]
                rows = cursor.fetchall()

                return {
                    "columns": columns,
                    "results": [list(row) for row in rows],
                    "row_count": len(rows),
                }
        finally:
            connection.close()
```

### Step 2: Backend - New API Endpoint

**File: `posthog/api/direct_query.py`**

```python
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from posthog.api.routing import TeamAndOrgViewSetMixin
from products.data_warehouse.backend.models import ExternalDataSource
from posthog.warehouse.direct_query.executor import DirectQueryExecutor

class DirectQueryViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):

    @action(methods=["POST"], detail=False)
    def execute(self, request: Request):
        source_id = request.data.get("source_id")
        query = request.data.get("query")

        source = ExternalDataSource.objects.get(
            id=source_id,
            team_id=self.team_id
        )

        executor = DirectQueryExecutor(source)
        result = executor.execute(query)

        return Response(status=status.HTTP_200_OK, data=result)

    @action(methods=["GET"], detail=False)
    def sources(self, request: Request):
        """List sources that support direct queries (currently just Postgres)."""
        sources = ExternalDataSource.objects.filter(
            team_id=self.team_id,
            source_type__in=["Postgres"],  # Expandable
            deleted=False,
        )
        return Response([
            {"id": s.id, "name": s.prefix or s.source_type, "type": s.source_type}
            for s in sources
        ])
```

### Step 3: Frontend - Database Selector in SQL Editor

**Modify: `frontend/src/scenes/data-warehouse/editor/QueryPane.tsx`**

Add a dropdown to select the target database:

- "PostHog (HogQL)" - default, current behavior
- List of connected Postgres sources

### Step 4: Frontend - New Logic for Direct Queries

**File: `frontend/src/scenes/data-warehouse/editor/directQueryLogic.ts`**

```typescript
import { kea, actions, reducers, loaders } from 'kea'
import api from 'lib/api'

export const directQueryLogic = kea({
    actions: {
        setSelectedSource: (sourceId: string | null) => ({ sourceId }),
        runDirectQuery: (query: string) => ({ query }),
    },
    loaders: {
        sources: {
            loadSources: async () => {
                return await api.get('api/projects/@current/direct_query/sources')
            },
        },
        queryResults: {
            runDirectQuery: async ({ query }) => {
                return await api.post('api/projects/@current/direct_query/execute', {
                    source_id: values.selectedSource,
                    query,
                })
            },
        },
    },
    reducers: {
        selectedSource: [
            null as string | null,
            {
                setSelectedSource: (_, { sourceId }) => sourceId,
            },
        ],
    },
})
```

---

## Concrete Next Steps

### Immediate (Today)

1. **[x] Create research branch** - `feat/hackathon-bi-research`
2. **[x] Document existing patterns** - This file
3. **[x] Set up demo Postgres** - Pagila database on port 5433
4. **[x] Create DirectQueryExecutor** - `products/data_warehouse/backend/services/direct_query_executor.py`

### Short-term (Hackathon)

5. **[x] Create API endpoint** - `/api/environments/:team_id/direct_query/execute`
6. **[x] Add schema endpoint** - `/api/environments/:team_id/direct_query/schema/:id`
7. **[x] Frontend database selector** - `DatabaseSelector.tsx` dropdown in SQL editor toolbar
8. **[x] Wire up execution** - Connect frontend to new API via `directQueryLogic.ts`
9. **[x] Test with Pagila Postgres** - Successfully queried film data
10. **[x] Tables appear in schema browser** - Direct query tables shown with lightning bolt icon
11. **[x] Query routing** - Queries routed to external DB based on selected database

### Demo Day

12. **[x] Polish UI** - Show source name, schema browser with direct query indicators
13. **[x] Error handling** - Nice error messages in output pane
14. **[x] Prefix stripping** - Auto-strip `postgres.` prefix from table names for external queries

---

## Demo Setup - DVD Rental (Pagila) Database

We're using the Pagila sample database - a PostgreSQL port of the MySQL Sakila database.
It simulates a DVD rental store with 15 tables including films, actors, customers, rentals, payments.

**Start the demo database:**

```bash
cd ~/Documents/GitHub/pagila
docker compose up -d
```

**Connection details:**

| Setting | Value |
|---------|-------|
| Host | localhost |
| Port | 5433 |
| Database | postgres |
| User | postgres |
| Password | 123456 |
| Schema | public |
| Connection string | `postgresql://postgres:123456@localhost:5433/postgres` |

**Key tables:**

- `film` - 1000 films with title, description, release year, rental rate
- `actor` - 200 actors
- `customer` - 599 customers with names, emails, addresses
- `rental` - 16,044 rental transactions
- `payment` - 14,596 payments
- `inventory`, `store`, `staff`, `category`, `language`, etc.

**Example queries for testing:**

```sql
-- Top 10 most rented films
SELECT f.title, COUNT(*) as rental_count
FROM rental r
JOIN inventory i ON r.inventory_id = i.inventory_id
JOIN film f ON i.film_id = f.film_id
GROUP BY f.title
ORDER BY rental_count DESC
LIMIT 10;

-- Revenue by month
SELECT DATE_TRUNC('month', payment_date) as month, SUM(amount) as revenue
FROM payment
GROUP BY month
ORDER BY month;

-- Customer spending
SELECT c.first_name, c.last_name, SUM(p.amount) as total_spent
FROM customer c
JOIN payment p ON c.customer_id = p.customer_id
GROUP BY c.customer_id, c.first_name, c.last_name
ORDER BY total_spent DESC
LIMIT 10;
```

---

## Key Files Reference

| Purpose | File |
|---------|------|
| ExternalDataSource model | `products/data_warehouse/backend/models/external_data_source.py` |
| Postgres connection code | `posthog/temporal/data_imports/sources/postgres/postgres.py` |
| Source registry | `posthog/temporal/data_imports/sources/__init__.py` |
| External data API | `products/data_warehouse/backend/api/external_data_source.py` |
| SQL editor logic | `frontend/src/scenes/data-warehouse/editor/multitabEditorLogic.tsx` |
| Query pane component | `frontend/src/scenes/data-warehouse/editor/QueryPane.tsx` |
| Connection string parser | `frontend/src/scenes/data-warehouse/external/forms/parseConnectionString.ts` |

---

## Open Questions

1. Should direct queries be limited to certain roles/permissions?
2. How to handle query results that are very large? (pagination?)
3. Should we support parameterized queries?
4. How to visualize results beyond tables (charts)?
5. Should connections be team-scoped or org-scoped?
6. Connection pooling for better performance?

---

## References

- Existing Postgres source: `posthog/temporal/data_imports/sources/postgres/`
- Data warehouse models: `products/data_warehouse/backend/models/`
- SQL editor: `frontend/src/scenes/data-warehouse/editor/`
- Query API: `posthog/api/query.py`
