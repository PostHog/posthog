# Multi-tenant query service TODO

## Goal

Build a live Postgres query service that lets PostHog customers expose tenant-isolated HogQL querying to their own customers.

The service must always execute through HogQL parsing, validation, and rewrite.
There is no raw SQL mode.

Example behavior:

```sql
select * from trips
```

with configured tenancy column `customer_id` and request `tenant_value = 42` becomes an enforced tenant-scoped query equivalent to:

```sql
select * from trips where customer_id = 42
```

The tenant predicate must be injected structurally through the HogQL AST, not appended as a string.

## Decisions so far

- Data source: live Postgres connections only.
- Query language: HogQL only.
- Raw SQL mode: not supported.
- Endpoint: separate endpoint from `/api/query`.
- Working endpoint name: `tenant_query`.
- Candidate path: `POST /api/projects/:project_id/tenant_query/`.
- Request method: `POST` only.
- Request body shape:

```json
{
  "connection_id": "abc",
  "tenant_value": "42",
  "query": "select * from trips",
  "timeout_ms": 30000
}
```

- Auth model: the PostHog customer proxies requests through their own backend.
  PostHog trusts the customer backend to provide the correct `tenant_value`.
- Config ownership: admin-only.
- Tenancy config: one tenancy column per connection, for example `customer_id`.
  Per-table granularity can come later.
- Tenant value key: generic `tenant_value`, not a request key named after the tenancy column.
- Tenant value type: inferred from the live Postgres schema.
  It may be an integer, string, or UUID.
- Enabled objects: table-level allowlist only in v1.
- Disabled tables: hidden and not queryable.
- Column-level controls: deferred.
  These should use the same system as normal direct queries later.
- Tenant column visibility: hidden from schema export and query results.
- Missing tenant column: reject the whole query if any referenced base table lacks the configured tenancy column.
- Dimension table exceptions: not supported in v1.
  Every referenced base table must have the tenancy column.
- Query shape: all `SELECT` queries supported if HogQL can parse and the rewriter can enforce tenant predicates.
- CTEs and subqueries: supported.
- Tenant predicate behavior: always inject the service-owned tenant predicate, even if the submitted query already filters the tenant column.
  Conflicting predicates should naturally return no rows.
- Default limit: if no explicit limit is provided, inject `LIMIT 100`.
- Max limit: configurable per connection, default `100000`.
- Timeout: configurable.
  Requests may provide `timeout_ms`, subject to a configured maximum.
- Postgres execution safety: run queries in a read-only transaction and set `statement_timeout`.
- Unsafe Postgres functions: defer detailed handling for now.
- Schema export: exposed through namespaced virtual system tables, metadata-only.
  Candidate tables:
  - `system.tables`
  - `system.fields`
- System table behavior: metadata-only and allowed without `tenant_value`.
  Only enabled tables and visible fields should be exposed.
- Response shape: match the existing PostHog query response style with columns, types, results, and timing.
- Logs: store original query, rewritten query, tenant value, timing, row count, errors, connection metadata, and referenced table metadata.
  No masking in v1.
- Observability: available through PostHog Logs and MCP tools only.
  No dedicated execution history UI in v1.
- MCP generator: deferred.
  For now, only build the query service.
- Billing: deferred.
- Rate limits: deferred, though the design should leave room for them.

## Implementation steps

1. Locate the existing live Postgres direct-query path and how it integrates with HogQL.
   Confirm where connection metadata, schema introspection, query execution, and result typing currently live.

2. Define the admin configuration model for the service.
   It should store:
   - connection reference
   - enabled flag
   - tenancy column name
   - inferred tenancy column type
   - enabled tables
   - default timeout
   - maximum timeout
   - maximum result limit, defaulting to `100000`

3. Add schema introspection for tenancy validation.
   The config flow should verify that every enabled table has the configured tenancy column and should infer the column type.

4. Add namespaced virtual system tables for metadata export.
   `system.tables` and `system.fields` should expose only enabled tables and should hide the tenancy column from fields.

5. Add the new query endpoint.
   Candidate:

```http
POST /api/projects/:project_id/tenant_query/
```

The endpoint should validate:

- admin/project access as appropriate for the caller
- service enabled for the connection
- `connection_id`
- `tenant_value`
- `query`
- optional `timeout_ms`

6. Parse submitted queries as HogQL.
   Reject anything that is not a `SELECT` query.

7. Resolve all referenced base tables.
   Reject the query if any referenced base table:
   - is not enabled
   - does not exist
   - lacks the configured tenancy column

8. Rewrite the HogQL AST.
   Inject the configured tenancy predicate for every referenced base table or alias.
   This must cover normal table references, joins, CTEs, and subqueries.

9. Enforce result limits.
   Inject `LIMIT 100` when the query has no explicit limit.
   Reject or clamp explicit limits above the configured maximum.
   The preferred behavior still needs to be chosen during implementation.

10. Compile the rewritten HogQL to Postgres SQL for the selected live connection.
    Ensure there is no path that executes submitted raw SQL directly.

11. Execute against live Postgres in a read-only transaction.
    Set `statement_timeout` from the request or connection default, capped by the configured maximum timeout.

12. Shape the response to match existing PostHog query responses.
    Include columns, types, results, and execution timing.
    Hide the tenant column from `select *` results and schema output.

13. Emit Logs records for every execution.
    Include:
    - connection ID
    - tenant value
    - original query
    - rewritten query
    - referenced tables
    - duration
    - row count
    - success or error
    - error details when present

14. Add MCP observability tools for the PostHog customer.
    Initial tools:
    - list recent tenant query executions
    - get tenant query execution detail
    - summarize errors by tenant, table, and query pattern
    - summarize usage by tenant, table, and time range

15. Add tests.
    Cover:
    - default limit injection
    - max limit enforcement
    - tenant predicate injection for simple selects
    - joins
    - aliases
    - CTEs
    - subqueries
    - queries with an existing tenant filter
    - disabled table rejection
    - missing tenancy column rejection
    - tenant column hidden from `select *`
    - tenant column hidden from `system.fields`
    - metadata-only system table queries without `tenant_value`
    - read-only execution
    - timeout handling
    - log emission on success and failure

## Open implementation choices

- Final endpoint name:
  - candidate: `tenant_query`
  - alternative: `multi_tenant_query`
  - alternative: `query_service`
- Whether max-limit violations should be rejected or clamped.
- Exact timeout defaults and max timeout.
- Exact Logs schema/event naming.
- Exact MCP tool names and output schemas.
