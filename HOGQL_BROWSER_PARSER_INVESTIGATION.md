# HogQL Browser Parser Investigation

**Date**: 2025-10-30
**Question**: What would it take to make the SQL parser WASM so that it can run in browser, specifically handling remote database lookups?

## Executive Summary

Making HogQL work in the browser requires **two separate concerns**:
1. **Syntax Parsing** (feasible, no DB needed)
2. **Semantic Resolution** (requires database schema - needs API calls)

**Recommendation**: Implement a **hybrid architecture** with client-side parsing and server-side resolution.

---

## Current Architecture Analysis

### 1. Parser Layer (NO DATABASE CALLS)

**Location**:
- Grammar: `/posthog/hogql/grammar/HogQLParser.g4`, `HogQLLexer.g4`
- Python: `/posthog/hogql/parser.py`
- C++: `/common/hogql_parser/parser.cpp`

**Function**: Pure syntax parsing
- Input: SQL string
- Output: Abstract Syntax Tree (AST)
- **Dependencies**: ANTLR4 runtime ONLY (no database access)

```python
# Example: This works WITHOUT any database context
from posthog.hogql.parser import parse_expr
ast = parse_expr("SELECT timestamp, event FROM events WHERE team_id = 123")
# Returns AST with nodes like SelectQuery, Field, Constant
```

### 2. Resolver Layer (REQUIRES DATABASE METADATA)

**Location**: `/posthog/hogql/resolver.py`

**Function**: Semantic analysis and type resolution
- Resolves table references → actual table schemas
- Resolves field names → field types
- Resolves views → view definitions (loaded from Django ORM)
- Resolves data warehouse tables → external table schemas
- Validates cohorts, actions, properties

**Dependencies**:
- `HogQLContext` with `Database` object
- Django ORM queries to PostgreSQL for:
  - `DataWarehouseTable` - User-created external tables
  - `DataWarehouseSavedQuery` - User-created views
  - `GroupTypeMapping` - Group type configurations
  - Revenue analytics views
  - Session table version settings

```python
# Example: This REQUIRES database context
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.resolver import resolve_types

context = HogQLContext(
    team_id=123,
    database=create_hogql_database(team_id=123)  # ← Loads metadata from PostgreSQL
)
resolved_ast = resolve_types(ast, context, dialect="hogql")
# Now AST nodes have .type attributes with full type information
```

### 3. Database Schema Object

**Location**: `/posthog/hogql/database/database.py`

The `Database` class contains:

#### Static Tables (defined in code)
- `events`, `persons`, `groups`, `sessions`, etc.
- Web analytics pre-aggregated tables
- System tables (query_log, numbers, logs)
- Session replay events

#### Dynamic Tables (loaded from PostgreSQL)
```python
# From database.py:296-309
def _add_warehouse_tables(self, node: TableNode):
    # Adds DataWarehouseTable objects from Django ORM

def _add_views(self, node: TableNode):
    # Adds DataWarehouseSavedQuery objects (user views)
```

**Key Database Queries**:
```python
# Line 365-380: Loads external data warehouse tables
DataWarehouseTable.objects.select_related("credential", "external_data_source")
    .filter(Q(deleted=False) | Q(deleted__isnull=True), team_id=context.team_id)
    .all()

# Line 457-464: Loads saved queries (views)
DataWarehouseSavedQuery.objects.select_related("table")
    .filter(deleted__isnull=True, team_id=context.team_id)
    .all()
```

---

## Current Browser Integration

**Autocomplete** (`/frontend/src/lib/monaco/hogQLAutocompleteProvider.ts`)

Already uses **server-side API calls**:
```typescript
const query: HogQLAutocomplete = {
    kind: NodeKind.HogQLAutocomplete,
    language: type,
    query: model.getValue(),
    filters: logic.props.metadataFilters,
    globals: logic.props.globals,
    startPosition: startOffset,
    endPosition: endOffset,
}
const response = await performQuery<HogQLAutocomplete>(query)
// Server returns suggestions with full context
```

**Backend endpoint** (`/posthog/hogql/autocomplete.py`):
- Parses query
- Creates Database with full team schema
- Resolves types
- Returns context-aware suggestions

---

## Approach Options for Browser Parsing

### Option 1: Pure Client-Side Parsing (LIMITED) ⚠️

**What works**:
- ✅ Syntax validation
- ✅ Basic error highlighting
- ✅ Token identification for syntax highlighting

**What DOESN'T work**:
- ❌ Type checking
- ❌ Table name validation
- ❌ Field name validation
- ❌ View resolution
- ❌ Autocomplete suggestions

**Implementation**:
```typescript
// 1. Generate TypeScript parser from ANTLR grammar
// npm install -g antlr4ng-cli
// antlr4ng -Dlanguage=TypeScript HogQLParser.g4 HogQLLexer.g4

// 2. Use in browser
import { HogQLLexer } from './generated/HogQLLexer';
import { HogQLParser } from './generated/HogQLParser';

function parseSyntaxOnly(query: string) {
    const inputStream = CharStreams.fromString(query);
    const lexer = new HogQLLexer(inputStream);
    const tokenStream = new CommonTokenStream(lexer);
    const parser = new HogQLParser(tokenStream);

    // Returns parse tree (syntax only, no types)
    return parser.select();
}
```

**Limitations**: No schema context = can't validate:
- `SELECT user_name FROM events` ← "user_name" doesn't exist in events table
- `SELECT * FROM my_warehouse_table` ← Can't know if this view exists
- `SELECT cohort(123)` ← Can't validate cohort ID

---

### Option 2: Hybrid Architecture (RECOMMENDED) ✅

**Client-Side**: Syntax parsing + basic validation
**Server-Side**: Schema resolution + type checking

#### Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Browser (Client)                  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. TypeScript Parser (ANTLR4ng)                   │
│     • Syntax parsing                               │
│     • Basic error detection                        │
│     • Immediate feedback (<10ms)                   │
│                                                     │
│  2. Schema Cache (IndexedDB/Memory)                │
│     • Table names list                             │
│     • Basic field names (for simple autocomplete)  │
│     • Refreshed periodically via API               │
│                                                     │
│  3. Debounced API Calls                           │
│     • Full type resolution                         │
│     • Advanced autocomplete                        │
│     • View/table existence checks                  │
│                                                     │
└─────────────────────────────────────────────────────┘
                         ↕ API
┌─────────────────────────────────────────────────────┐
│                Server (Python/Django)               │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. Existing HogQL Parser (C++/Python)             │
│  2. Database Schema (from PostgreSQL)              │
│  3. Type Resolver                                  │
│  4. Validation + Error Messages                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

#### Implementation Plan

**Phase 1: Client-Side Parser**
```bash
# Generate TypeScript parser
cd posthog/hogql/grammar
antlr4ng -Dlanguage=TypeScript -visitor -o ../../../frontend/src/lib/hogql-parser \
  HogQLLexer.g4 HogQLParser.g4
```

**Phase 2: Schema Metadata API**
```python
# New API endpoint: /api/projects/:id/hogql/schema
class HogQLSchemaView(APIView):
    def get(self, request):
        team = request.user.team
        database = create_hogql_database(team.pk)

        return {
            "tables": {
                "events": {
                    "fields": ["uuid", "event", "timestamp", "properties", ...],
                    "type": "posthog"
                },
                "persons": {...},
                # Include warehouse tables
                "my_snowflake_table": {
                    "fields": ["id", "name", "created_at"],
                    "type": "warehouse"
                },
                # Include views
                "my_saved_query": {
                    "fields": [...],
                    "type": "view"
                }
            },
            "functions": ["count", "sum", "avg", ...],
            "cohorts": [{"id": 1, "name": "Active Users"}, ...],
            "version": "abc123"  # Cache invalidation
        }
```

**Phase 3: Client-Side Cache**
```typescript
// frontend/src/lib/hogql/schemaCache.ts
class HogQLSchemaCache {
    private schema: DatabaseSchema | null = null;
    private lastFetch: number = 0;
    private TTL = 5 * 60 * 1000; // 5 minutes

    async getSchema(): Promise<DatabaseSchema> {
        if (this.schema && Date.now() - this.lastFetch < this.TTL) {
            return this.schema;
        }

        // Fetch from API
        const response = await api.hogql.getSchema();
        this.schema = response;
        this.lastFetch = Date.now();

        // Store in IndexedDB for offline support
        await this.saveToIndexedDB(response);

        return response;
    }

    // Fast lookups for autocomplete
    getTableNames(): string[] {
        return this.schema ? Object.keys(this.schema.tables) : [];
    }

    getFieldsForTable(tableName: string): string[] {
        return this.schema?.tables[tableName]?.fields || [];
    }
}
```

**Phase 4: Client-Side Validation Layer**
```typescript
// frontend/src/lib/hogql/validator.ts
class HogQLValidator {
    constructor(private parser: HogQLParser, private schema: HogQLSchemaCache) {}

    async validate(query: string): Promise<ValidationResult> {
        // Fast: Syntax-only validation (no API call)
        const syntaxErrors = this.validateSyntax(query);
        if (syntaxErrors.length > 0) {
            return { errors: syntaxErrors, warnings: [] };
        }

        // Medium: Basic schema validation (from cache, no API call)
        const schema = await this.schema.getSchema();
        const schemaErrors = this.validateAgainstSchema(query, schema);

        // Slow: Full server-side validation (debounced API call)
        // Only for complex cases (views, type checking, etc.)
        if (this.needsFullValidation(query)) {
            const serverResult = await api.hogql.validate(query);
            return serverResult;
        }

        return { errors: schemaErrors, warnings: [] };
    }

    private validateSyntax(query: string): SyntaxError[] {
        // Use ANTLR TypeScript parser
        try {
            const ast = this.parser.parse(query);
            return [];
        } catch (e) {
            return [{ message: e.message, line: e.line, column: e.column }];
        }
    }

    private validateAgainstSchema(query: string, schema: DatabaseSchema): Error[] {
        const errors: Error[] = [];
        const ast = this.parser.parse(query);

        // Walk AST and check table/field names
        ast.walk((node) => {
            if (node.type === 'TableReference') {
                if (!schema.tables[node.name]) {
                    errors.push({
                        message: `Table '${node.name}' does not exist`,
                        line: node.line,
                        column: node.column
                    });
                }
            }
        });

        return errors;
    }
}
```

**Phase 5: Improved Monaco Integration**
```typescript
// frontend/src/lib/monaco/hogQLLanguageProvider.ts
export function registerHogQLLanguage() {
    const schemaCache = new HogQLSchemaCache();
    const validator = new HogQLValidator(parser, schemaCache);

    // Immediate syntax highlighting
    monaco.languages.register({ id: 'hogql' });

    // Fast autocomplete from cache
    monaco.languages.registerCompletionItemProvider('hogql', {
        triggerCharacters: [' ', '.', ','],
        provideCompletionItems: async (model, position) => {
            const schema = await schemaCache.getSchema();
            const word = model.getWordUntilPosition(position);

            // Provide table names
            const tables = schemaCache.getTableNames().map(name => ({
                label: name,
                kind: monaco.languages.CompletionItemKind.Class,
                insertText: name
            }));

            // For more advanced autocomplete, debounce server call
            // ...

            return { suggestions: tables };
        }
    });

    // Validation markers
    monaco.languages.registerDocumentFormattingEditProvider('hogql', {
        provideDocumentFormattingEdits: async (model) => {
            const result = await validator.validate(model.getValue());
            // Update Monaco markers with errors/warnings
            return [];
        }
    });
}
```

---

### Option 3: Full Schema Serialization (NOT RECOMMENDED) ❌

**Idea**: Send entire Database schema to browser

**Problems**:
1. **Size**: Database schema can be large (1-10 MB JSON)
   - All table definitions
   - All field types
   - All warehouse tables
   - All saved queries
   - All cohorts/actions

2. **Security**: Exposes internal schema details

3. **Staleness**: Client cache gets out of sync
   - User creates new view → other users don't see it
   - Warehouse table schema changes → cached schema wrong

4. **Complexity**: Need to implement resolver in TypeScript
   - Port 2000+ lines of Python resolver logic
   - Maintain parity with server-side implementation

---

## Recommended Implementation Strategy

### Immediate Wins (Week 1-2)

1. **Generate TypeScript parser from ANTLR grammar**
   - Enables syntax highlighting
   - Enables immediate error feedback
   - No API changes needed

2. **Create lightweight schema metadata API**
   - Returns just table/field names (not full types)
   - Cached aggressively (5-10 min TTL)
   - ~50-200 KB payload

3. **Implement client-side schema cache**
   - IndexedDB storage for offline support
   - Automatic background refresh
   - Invalidation on schema changes

### Medium-term Improvements (Week 3-6)

4. **Smart validation hybrid**
   - Syntax validation: client-side (instant)
   - Basic schema checks: client-side with cache (fast)
   - Full type resolution: server-side (debounced)

5. **Enhanced autocomplete**
   - Basic suggestions from cache (no latency)
   - Advanced suggestions from server (debounced 300ms)
   - Function signatures, type hints

6. **Real-time schema updates**
   - WebSocket/SSE for schema change notifications
   - Invalidate cache when warehouse tables added
   - Notify users of new views

### Long-term Optimizations (Month 2+)

7. **Partial type inference**
   - Some type checking possible client-side
   - Constant types, basic expressions
   - Reduces server validation load

8. **Query result caching**
   - Cache common table schemas
   - Deduplicate validation requests
   - Reduce API calls by 60-80%

---

## Performance Comparison

| Operation | Current (Server-Only) | Hybrid (Recommended) | Full Client-Side |
|-----------|----------------------|---------------------|------------------|
| **Syntax error detection** | 100-300ms | <10ms | <10ms |
| **Table name autocomplete** | 100-300ms | <50ms (cached) | Not possible |
| **Field validation** | 100-300ms | 50-100ms (cached) | Not possible |
| **Type checking** | 100-300ms | 100-300ms (debounced) | Not possible |
| **View resolution** | 100-300ms | 100-300ms (API call) | Not possible |
| **Cold start** | 100-300ms | 200-400ms (schema fetch) | <10ms |
| **Bundle size** | 0 KB | ~300 KB (parser + runtime) | ~300 KB |

---

## API Contract Design

### GET `/api/projects/:id/hogql/schema`

**Response**:
```json
{
    "version": "2024-10-30T12:34:56Z",
    "tables": {
        "events": {
            "type": "posthog",
            "fields": ["uuid", "event", "timestamp", "distinct_id", "properties", "person_id"]
        },
        "persons": {
            "type": "posthog",
            "fields": ["id", "created_at", "properties", "is_identified"]
        },
        "my_warehouse_table": {
            "type": "warehouse",
            "source": "snowflake",
            "fields": ["id", "name", "email", "created_at"]
        },
        "revenue_by_cohort": {
            "type": "view",
            "fields": ["cohort_id", "total_revenue", "user_count"]
        }
    },
    "functions": {
        "aggregate": ["count", "sum", "avg", "min", "max", "uniq"],
        "string": ["lower", "upper", "concat", "substring"],
        "posthog": ["cohort", "matchAction", "sparkline"]
    },
    "cohorts": [
        {"id": 1, "name": "Active Users"},
        {"id": 2, "name": "Churned Users"}
    ],
    "properties": {
        "event": ["$current_url", "$browser", "$os"],
        "person": ["email", "name", "plan"]
    }
}
```

**Caching headers**:
```
Cache-Control: private, max-age=300
ETag: "abc123"
```

### POST `/api/projects/:id/hogql/validate`

**Request**:
```json
{
    "query": "SELECT event, count() FROM events WHERE team_id = {team_id} GROUP BY event",
    "validate_types": true
}
```

**Response**:
```json
{
    "valid": false,
    "errors": [
        {
            "message": "Field 'team_id' should not be used in queries",
            "line": 1,
            "column": 43,
            "severity": "error"
        }
    ],
    "warnings": [
        {
            "message": "Consider using person properties for better performance",
            "line": 1,
            "column": 7,
            "severity": "warning"
        }
    ]
}
```

---

## Migration Path

### Phase 1: Parallel Implementation (No Breaking Changes)
- Add TypeScript parser alongside existing server validation
- New schema metadata endpoint (optional)
- Gradual rollout with feature flag

### Phase 2: Optimize Client Experience
- Use client parser for immediate feedback
- Keep server validation for accuracy
- Collect metrics on validation accuracy

### Phase 3: Progressive Enhancement
- Add more validation logic to client
- Reduce server validation load
- Maintain server as source of truth

### Phase 4: Long-term
- 90% of validation happens client-side
- Server handles only complex cases
- Significant reduction in API calls

---

## Security Considerations

1. **Schema exposure**: Only expose table/field names, not data
2. **Rate limiting**: Prevent schema API abuse
3. **Permissions**: Filter schema based on user access level
4. **Validation**: Always re-validate on server before query execution
5. **Sanitization**: Client validation is advisory only

---

## Conclusion

**The parser CAN run in the browser** (syntax parsing only), but **full semantic validation REQUIRES server-side database lookups**.

**Recommended approach**:
- ✅ Client-side TypeScript parser for instant syntax feedback
- ✅ Lightweight schema metadata API with aggressive caching
- ✅ Server-side validation for complex resolution (debounced)
- ✅ Hybrid architecture balances UX and accuracy

**Effort estimate**:
- TypeScript parser generation: 1-2 days
- Schema API + caching: 3-5 days
- Monaco integration: 3-5 days
- Testing & refinement: 5-7 days
- **Total**: 2-3 weeks for initial implementation

**Key insight**: The current autocomplete already follows this hybrid pattern - we're just formalizing and extending it to full validation.
