# MetaHog - Implementation Spec

> Technical specification for direct database query feature

## Overview

Add the ability to execute SQL queries directly against connected external databases (Postgres) from the PostHog SQL editor.

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| Query Only Model Field | ✅ Done | `products/data_warehouse/backend/models/external_data_source.py` |
| Migration | ✅ Done | `products/data_warehouse/backend/migrations/0012_externaldatasource_query_only.py` |
| Backend Create API | ✅ Done | `products/data_warehouse/backend/api/external_data_source.py` |
| DirectQueryExecutor | ✅ Done | `products/data_warehouse/backend/services/direct_query_executor.py` |
| Direct Query API | ✅ Done | `products/data_warehouse/backend/api/direct_query.py` |
| Frontend Toggle | ✅ Done | `frontend/src/scenes/data-warehouse/external/forms/SourceForm.tsx` |
| Source Wizard Logic | ✅ Done | `frontend/src/scenes/data-warehouse/new/sourceWizardLogic.tsx` |
| Frontend DB Selector | ✅ Done | `frontend/src/scenes/data-warehouse/editor/DatabaseSelector.tsx` |
| Frontend Query Logic | ✅ Done | `frontend/src/scenes/data-warehouse/editor/directQueryLogic.ts` |
| Query Execution Routing | ✅ Done | `frontend/src/scenes/data-warehouse/editor/QueryWindow.tsx` |
| URL Param Support | ✅ Done | `frontend/src/scenes/urls.ts`, `multitabEditorLogic.tsx` |
| Schema Browser Integration | ✅ Done | `frontend/src/scenes/data-warehouse/editor/sidebar/QueryDatabase.tsx` |
| Output Pane Integration | ✅ Done | `frontend/src/scenes/data-warehouse/editor/OutputPane.tsx` |

---

## Part 1: Query Only Source Creation

### 1.1 Model Migration

**File**: `posthog/migrations/XXXX_add_query_only_to_external_data_source.py`

```python
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('posthog', 'XXXX_previous_migration'),
    ]

    operations = [
        migrations.AddField(
            model_name='externaldatasource',
            name='query_only',
            field=models.BooleanField(default=False),
        ),
    ]
```

**File**: `products/data_warehouse/backend/models/external_data_source.py` (add field)

```python
class ExternalDataSource(...):
    # ... existing fields ...

    # When True, this source is for direct SQL queries only - no data sync
    query_only = models.BooleanField(default=False)
```

### 1.2 Backend API Changes

**File**: `products/data_warehouse/backend/api/external_data_source.py`

Modify the `create` method to handle `query_only` sources:

```python
def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
    prefix = request.data.get("prefix", None)
    source_type = request.data["source_type"]
    query_only = request.data.get("query_only", False)  # NEW

    # ... existing validation ...

    # Validate credentials (same as before)
    source_type_model = ExternalDataSourceType(source_type)
    source = SourceRegistry.get_source(source_type_model)
    is_valid, errors = source.validate_config(payload)
    if not is_valid:
        return Response(
            status=status.HTTP_400_BAD_REQUEST,
            data={"message": f"Invalid source config: {', '.join(errors)}"},
        )
    source_config: Config = source.parse_config(payload)

    # NEW: For query_only, just validate credentials and create source
    if query_only:
        # Validate credentials work
        credentials_valid, credentials_error = source.validate_credentials(source_config, self.team_id)
        if not credentials_valid:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": credentials_error or "Invalid credentials"},
            )

        # Create source without any schemas
        new_source_model = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            team=self.team,
            status="Completed",  # No sync needed
            source_type=source_type_model,
            job_inputs=source_config.to_dict(),
            prefix=prefix,
            query_only=True,  # Mark as query only
            created_by=request.user if isinstance(request.user, User) else None,
        )

        return Response(status=status.HTTP_201_CREATED, data={"id": new_source_model.pk})

    # ... existing flow for batch import sources ...
```

Add `query_only` to serializer:

```python
class ExternalDataSourceSerializers(serializers.ModelSerializer):
    class Meta:
        model = ExternalDataSource
        fields = [
            # ... existing fields ...
            "query_only",  # ADD
        ]
```

### 1.3 Frontend Changes for Query Only Toggle

**File**: `frontend/src/scenes/data-warehouse/external/forms/SourceForm.tsx`

Add query_only toggle after the other fields:

```tsx
// In SourceFormComponent, after the prefix field:

{sourceConfig.name === 'Postgres' && (  // Only show for supported types
    <LemonField
        name="query_only"
        label="Query only"
    >
        {({ value, onChange }) => (
            <>
                <LemonSwitch
                    checked={value || false}
                    onChange={onChange}
                    label="Skip data sync"
                />
                <p className="text-muted text-sm mt-1">
                    Connect for direct SQL queries without importing data to PostHog.
                    Use this for ad-hoc analysis of external databases.
                </p>
            </>
        )}
    </LemonField>
)}
```

**File**: `frontend/src/scenes/data-warehouse/new/sourceWizardLogic.tsx`

Modify the flow to skip schema selection for query_only:

```typescript
// In submitSourceConnectionDetailsSuccess listener:
submitSourceConnectionDetailsSuccess: () => {
    // NEW: Check if query_only mode
    if (values.sourceConnectionDetails.query_only) {
        // Skip schema fetching, go directly to create
        actions.createQueryOnlySource()
    } else {
        // Existing flow
        actions.getDatabaseSchemas()
    }
},

// NEW action:
createQueryOnlySource: async () => {
    if (values.selectedConnector === null) {
        return
    }

    try {
        actions.setIsLoading(true)
        const { id } = await api.externalDataSources.create({
            ...values.source,
            source_type: values.selectedConnector.name,
            query_only: true,
        })

        lemonToast.success('Query connection created')
        actions.setSourceId(id)
        actions.loadSources(null)
        actions.closeWizard()
    } catch (e: any) {
        lemonToast.error(e.data?.message ?? e.message)
    } finally {
        actions.setIsLoading(false)
    }
},
```

---

## Part 2: Direct Query Execution

## Backend Implementation

### 1. DirectQueryExecutor Service

**File**: `posthog/warehouse/direct_query/executor.py`

```python
from dataclasses import dataclass
from typing import Any
import psycopg

from products.data_warehouse.backend.models import ExternalDataSource


@dataclass
class DirectQueryResult:
    columns: list[dict[str, Any]]  # [{"name": "id", "type": "integer"}, ...]
    results: list[list[Any]]       # [[1, "foo"], [2, "bar"], ...]
    row_count: int
    truncated: bool                # True if results were limited


class DirectQueryExecutor:
    DEFAULT_TIMEOUT_MS = 30_000
    DEFAULT_ROW_LIMIT = 1000

    def __init__(self, source: ExternalDataSource):
        self.source = source
        self.job_inputs = source.job_inputs

    def execute(
        self,
        query: str,
        timeout_ms: int | None = None,
        row_limit: int | None = None,
    ) -> DirectQueryResult:
        """Execute SQL query against the connected database."""
        timeout_ms = timeout_ms or self.DEFAULT_TIMEOUT_MS
        row_limit = row_limit or self.DEFAULT_ROW_LIMIT

        # TODO: Add SSH tunnel support
        connection = psycopg.connect(
            host=self.job_inputs["host"],
            port=self.job_inputs.get("port", 5432),
            dbname=self.job_inputs["database"],
            user=self.job_inputs["user"],
            password=self.job_inputs["password"],
            sslmode=self.job_inputs.get("sslmode", "prefer"),
            connect_timeout=15,
        )

        try:
            with connection.cursor() as cursor:
                # Set statement timeout
                cursor.execute(f"SET statement_timeout = {timeout_ms}")

                # Execute the query
                cursor.execute(query)

                # Get column info
                columns = []
                if cursor.description:
                    columns = [
                        {"name": desc.name, "type": self._pg_type_to_string(desc.type_code)}
                        for desc in cursor.description
                    ]

                # Fetch results with limit
                rows = cursor.fetchmany(row_limit + 1)
                truncated = len(rows) > row_limit
                if truncated:
                    rows = rows[:row_limit]

                return DirectQueryResult(
                    columns=columns,
                    results=[list(row) for row in rows],
                    row_count=len(rows),
                    truncated=truncated,
                )
        finally:
            connection.close()

    def _pg_type_to_string(self, type_code: int) -> str:
        """Convert Postgres type OID to readable string."""
        # Common type OIDs - expand as needed
        type_map = {
            16: "boolean",
            20: "bigint",
            21: "smallint",
            23: "integer",
            25: "text",
            700: "real",
            701: "double",
            1043: "varchar",
            1082: "date",
            1114: "timestamp",
            1184: "timestamptz",
            1700: "numeric",
        }
        return type_map.get(type_code, "unknown")

    def get_schema(self) -> dict[str, list[dict[str, str]]]:
        """Get schema information (tables and columns)."""
        # Reuse existing get_schemas from postgres source
        from posthog.temporal.data_imports.sources.postgres.postgres import get_schemas

        return get_schemas(
            host=self.job_inputs["host"],
            database=self.job_inputs["database"],
            user=self.job_inputs["user"],
            password=self.job_inputs["password"],
            schema=self.job_inputs.get("schema", "public"),
            port=self.job_inputs.get("port", 5432),
        )
```

### 2. API Endpoint

**File**: `posthog/api/direct_query.py`

```python
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from products.data_warehouse.backend.models import ExternalDataSource
from posthog.warehouse.direct_query.executor import DirectQueryExecutor


# Source types that support direct queries
DIRECT_QUERY_SOURCE_TYPES = ["Postgres"]


class DirectQueryViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    API for executing direct SQL queries against connected databases.
    """

    @action(methods=["POST"], detail=False)
    def execute(self, request: Request) -> Response:
        """Execute a SQL query against a connected database."""
        source_id = request.data.get("source_id")
        query = request.data.get("query")

        if not source_id or not query:
            return Response(
                {"error": "source_id and query are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            source = ExternalDataSource.objects.get(
                id=source_id,
                team_id=self.team_id,
                deleted=False,
            )
        except ExternalDataSource.DoesNotExist:
            return Response(
                {"error": "Source not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if source.source_type not in DIRECT_QUERY_SOURCE_TYPES:
            return Response(
                {"error": f"Source type {source.source_type} does not support direct queries"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            executor = DirectQueryExecutor(source)
            result = executor.execute(query)

            return Response({
                "columns": result.columns,
                "results": result.results,
                "row_count": result.row_count,
                "truncated": result.truncated,
            })
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(methods=["GET"], detail=False)
    def sources(self, request: Request) -> Response:
        """List sources that support direct queries."""
        sources = ExternalDataSource.objects.filter(
            team_id=self.team_id,
            source_type__in=DIRECT_QUERY_SOURCE_TYPES,
            deleted=False,
        )

        return Response([
            {
                "id": str(source.id),
                "name": source.prefix or source.source_type,
                "type": source.source_type,
            }
            for source in sources
        ])

    @action(methods=["GET"], detail=False, url_path="schema/(?P<source_id>[^/.]+)")
    def schema(self, request: Request, source_id: str) -> Response:
        """Get schema (tables and columns) for a source."""
        try:
            source = ExternalDataSource.objects.get(
                id=source_id,
                team_id=self.team_id,
                deleted=False,
            )
        except ExternalDataSource.DoesNotExist:
            return Response(
                {"error": "Source not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            executor = DirectQueryExecutor(source)
            schema = executor.get_schema()

            return Response({"schema": schema})
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
```

### 3. Register API Routes

**File**: `posthog/api/__init__.py` (add to existing)

```python
from posthog.api.direct_query import DirectQueryViewSet

# In router registration section:
router.register(r"direct_query", DirectQueryViewSet, basename="direct_query")
```

---

## Frontend Implementation

### 1. Direct Query Logic

**File**: `frontend/src/scenes/data-warehouse/editor/directQueryLogic.ts`

```typescript
import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { directQueryLogicType } from './directQueryLogicType'

export interface DirectQuerySource {
    id: string
    name: string
    type: string
}

export interface DirectQueryResult {
    columns: Array<{ name: string; type: string }>
    results: any[][]
    row_count: number
    truncated: boolean
}

export const directQueryLogic = kea<directQueryLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'directQueryLogic']),

    actions({
        setSelectedSource: (sourceId: string | null) => ({ sourceId }),
        executeQuery: (query: string) => ({ query }),
    }),

    reducers({
        selectedSourceId: [
            null as string | null,
            {
                setSelectedSource: (_, { sourceId }) => sourceId,
            },
        ],
    }),

    loaders(({ values }) => ({
        sources: [
            [] as DirectQuerySource[],
            {
                loadSources: async () => {
                    const response = await api.get('api/projects/@current/direct_query/sources/')
                    return response as DirectQuerySource[]
                },
            },
        ],
        queryResult: [
            null as DirectQueryResult | null,
            {
                executeQuery: async ({ query }) => {
                    if (!values.selectedSourceId) {
                        throw new Error('No source selected')
                    }
                    const response = await api.post('api/projects/@current/direct_query/execute/', {
                        source_id: values.selectedSourceId,
                        query,
                    })
                    return response as DirectQueryResult
                },
            },
        ],
    })),

    selectors({
        isDirectQueryMode: [
            (s) => [s.selectedSourceId],
            (selectedSourceId) => selectedSourceId !== null,
        ],
        selectedSource: [
            (s) => [s.sources, s.selectedSourceId],
            (sources, selectedSourceId) =>
                sources.find((s) => s.id === selectedSourceId) ?? null,
        ],
    }),

    listeners({
        loadSourcesSuccess: () => {
            // Could auto-select first source or do nothing
        },
    }),
])
```

### 2. Database Selector Component

**File**: `frontend/src/scenes/data-warehouse/editor/DatabaseSelector.tsx`

```tsx
import { useActions, useValues } from 'kea'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { directQueryLogic } from './directQueryLogic'

export function DatabaseSelector(): JSX.Element {
    const { sources, selectedSourceId, sourcesLoading } = useValues(directQueryLogic)
    const { setSelectedSource, loadSources } = useActions(directQueryLogic)

    // Load sources on mount
    useEffect(() => {
        loadSources()
    }, [])

    const options = [
        { value: null, label: 'PostHog (HogQL)' },
        ...sources.map((source) => ({
            value: source.id,
            label: `${source.name} (${source.type})`,
        })),
    ]

    return (
        <LemonSelect
            size="small"
            value={selectedSourceId}
            onChange={(value) => setSelectedSource(value)}
            options={options}
            loading={sourcesLoading}
            placeholder="Select database"
        />
    )
}
```

### 3. Integrate into Query Editor

**Modify**: `frontend/src/scenes/data-warehouse/editor/QueryWindow.tsx`

Add the DatabaseSelector to the editor toolbar and modify the run query logic to route to the appropriate API based on selection.

---

## API Reference

### POST /api/projects/:team_id/direct_query/execute/

Execute a SQL query against a connected database.

**Request:**

```json
{
    "source_id": "uuid-of-source",
    "query": "SELECT * FROM film LIMIT 10"
}
```

**Response:**

```json
{
    "columns": [
        {"name": "film_id", "type": "integer"},
        {"name": "title", "type": "varchar"},
        {"name": "release_year", "type": "integer"}
    ],
    "results": [
        [1, "Academy Dinosaur", 2006],
        [2, "Ace Goldfinger", 2006]
    ],
    "row_count": 2,
    "truncated": false
}
```

### GET /api/projects/:team_id/direct_query/sources/

List sources that support direct queries.

**Response:**

```json
[
    {"id": "uuid-1", "name": "pagila", "type": "Postgres"},
    {"id": "uuid-2", "name": "analytics", "type": "Postgres"}
]
```

### GET /api/projects/:team_id/direct_query/schema/:source_id/

Get schema information for a source.

**Response:**

```json
{
    "schema": {
        "film": [
            {"column": "film_id", "type": "integer"},
            {"column": "title", "type": "character varying"}
        ],
        "actor": [
            {"column": "actor_id", "type": "integer"},
            {"column": "first_name", "type": "character varying"}
        ]
    }
}
```

---

## Testing

### Manual Testing

1. Start demo Postgres: `docker compose -f hack/docker-compose.demo-db.yml up -d`
2. Add Postgres source via Data Warehouse UI with connection to localhost:5433
3. Open SQL editor, select the new source from dropdown
4. Run query: `SELECT * FROM film LIMIT 10`
5. Verify results display correctly

### Unit Tests

**File**: `posthog/warehouse/direct_query/test_executor.py`

```python
import pytest
from unittest.mock import MagicMock, patch

from posthog.warehouse.direct_query.executor import DirectQueryExecutor, DirectQueryResult


class TestDirectQueryExecutor:
    def test_execute_simple_query(self):
        # TODO: Add tests with mocked psycopg connection
        pass

    def test_execute_with_timeout(self):
        pass

    def test_execute_with_row_limit(self):
        pass

    def test_get_schema(self):
        pass
```

---

## Security Considerations

- [ ] Queries execute with stored credentials (already encrypted)
- [ ] Statement timeout prevents long-running queries
- [ ] Row limit prevents memory issues
- [ ] Consider read-only mode (SET TRANSACTION READ ONLY)
- [ ] Audit logging for executed queries
- [ ] Rate limiting on API endpoint

---

## Future Enhancements

- [ ] Connection pooling for better performance
- [ ] Support MySQL, other databases
- [ ] Query history
- [ ] Saved queries
- [ ] Schema browser in sidebar
- [ ] Query explain/analyze
- [ ] Export results to CSV

---

## Actual API Endpoints (Implemented)

### POST /api/environments/:team_id/direct_query/execute

Execute a SQL query against a query-only data source.

**Request:**

```json
{
    "source_id": "019b03ef-7bb6-0000-ed53-df5c886fad51",
    "sql": "SELECT * FROM film LIMIT 10",
    "max_rows": 1000
}
```

**Response:**

```json
{
    "columns": ["film_id", "title", "release_year"],
    "rows": [
        {"film_id": 1, "title": "ACADEMY DINOSAUR", "release_year": 2012}
    ],
    "row_count": 10,
    "execution_time_ms": 8.51
}
```

### GET /api/environments/:team_id/direct_query/sources

List query-only data sources.

**Response:**

```json
{
    "sources": [
        {"id": "uuid", "source_type": "Postgres", "prefix": "", "created_at": "..."}
    ]
}
```

### GET /api/environments/:team_id/direct_query/schema/:source_id

Get schema for a query-only source.

**Response:**

```json
{
    "tables": {
        "film": [["film_id", "integer"], ["title", "character varying"]],
        "actor": [["actor_id", "integer"], ["first_name", "character varying"]]
    }
}
```

---

## Testing the Implementation

```bash
# 1. Start Pagila demo database
cd ~/Documents/GitHub/pagila && docker compose up -d

# 2. Create a query-only source via PostHog UI
#    - Go to Data Warehouse > Add source > Postgres
#    - Enter: localhost:5433, postgres, 123456, public
#    - Check "Query only (skip data sync)"

# 3. Test via API (with PostHog running)
curl -X POST "http://localhost:8000/api/environments/1/direct_query/execute" \
  -H "Content-Type: application/json" \
  -d '{"source_id": "YOUR_SOURCE_ID", "sql": "SELECT * FROM film LIMIT 5"}'

# 4. Or test directly via Python
python demo_query.py
```

---

## Frontend Implementation (Actual)

### directQueryLogic.ts

The central Kea logic for managing direct query state:

```typescript
// Key interfaces
export interface DirectQuerySource {
    id: string
    source_type: string
    prefix: string | null
    created_at: string
    status: string
}

export type SelectedDatabase = 'hogql' | string // 'hogql' or source UUID

// Key selectors
- selectedDatabase: Currently selected database ('hogql' or source UUID)
- sources: List of query-only sources from API
- isDirectQueryMode: True if an external source is selected
- selectedSource: The currently selected DirectQuerySource object
- selectedSourceName: Display name for the selected source

// Key actions
- setSelectedDatabase(database): Switch between HogQL and external sources
- executeDirectQuery(sourceId, sql, maxRows): Execute query against external DB
- loadSources(): Fetch available query-only sources from API
```

### Prefix Stripping Logic

When executing queries against external databases, table prefixes are automatically stripped:

```typescript
// In directQueryLogic.ts executeDirectQuery loader:
const prefixToStrip = source?.prefix || source?.source_type?.toLowerCase()
if (prefixToStrip) {
    const prefixPattern = new RegExp(`\\b${prefixToStrip}\\.`, 'gi')
    transformedSql = sql.replace(prefixPattern, '')
}

// Example:
// User writes: SELECT * FROM postgres.actor
// Sent to API: SELECT * FROM actor
```

This is necessary because:

1. HogQL names tables as `{source_type}.{table_name}` (e.g., `postgres.actor`)
2. The external database just has `actor` as the table name
3. The prefix needs to be stripped before sending to the external DB

### URL Parameter Support

Direct query sessions can be shared via URL:

```typescript
// urls.ts sqlEditor function supports:
- direct_query_source: UUID of the external source
- direct_query_prefix: Table prefix (for display)

// Example URL:
/sql?open_query=SELECT * FROM postgres.actor&direct_query_source=UUID
```

### Query Execution Flow

1. User selects "Postgres" from DatabaseSelector dropdown
2. User writes query: `SELECT * FROM postgres.actor`
3. User clicks Run
4. `RunButton` checks `isDirectQueryMode` from directQueryLogic
5. If true, calls `executeDirectQuery` action
6. `directQueryLogic` strips `postgres.` prefix
7. API call: `POST /api/environments/@current/direct_query/execute/`
8. Backend executes against external Postgres
9. Results displayed in OutputPane

### Key Files Summary

| File | Purpose |
|------|---------|
| `directQueryLogic.ts` | State management for direct queries |
| `DatabaseSelector.tsx` | Dropdown to select target database |
| `QueryWindow.tsx` | Contains RunButton with direct query routing |
| `OutputPane.tsx` | Displays results (handles both HogQL and direct query) |
| `multitabEditorLogic.tsx` | URL param handling, coordinates with directQueryLogic |
| `QueryDatabase.tsx` | Schema browser with "Query (Direct)" context menu |
| `urls.ts` | URL generation with direct_query params |

---

## Known Issues & Future Work

### Current Limitations

1. **Single database per query** - Cannot join HogQL tables with external tables
2. **No query history** - Direct queries not saved to query history
3. **No autocomplete** - Monaco doesn't have schema awareness for external DBs

### Future Enhancements

- [ ] Connection pooling for better performance
- [ ] Support MySQL, other databases
- [ ] Cross-database joins (HogQL + external)
- [ ] Query explain/analyze for external DBs
- [ ] Schema-aware autocomplete

---

## Related Docs

- [RESEARCH.md](./RESEARCH.md) - Codebase exploration and findings
- [PLAN.md](./PLAN.md) - High-level plan and decisions
