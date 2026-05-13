---
name: configuring-tenant-query
description: >
  Guide the user through enabling the tenant query service on a direct Postgres data warehouse connection — the path
  that lets a PostHog customer expose tenant-isolated HogQL to their own end-customers. Use when the user wants to
  "set up tenant_query", "expose HogQL per customer", "build a multi-tenant query API on top of Postgres", or
  configure the predicate-rewriting layer on an existing direct Postgres source. Walks through discovering or
  creating the direct-Postgres source, picking the tenant column, configuring tenant_query, and verifying with a
  scoped query.
---

# Configuring tenant query on a direct Postgres source

Use this skill when the user wants to turn an existing Postgres database into a tenant-scoped query endpoint —
the layer that takes `SELECT ... FROM orders` and rewrites it to
`SELECT ... FROM orders WHERE customer_id = <tenant>` server-side, so a downstream LLM or REST proxy never controls
the tenant value.

The tenant_query service only works on **direct-Postgres** sources (`access_method=direct`) — sources where PostHog
queries the customer's Postgres live, rather than mirroring it into the warehouse. Sources synced with normal
bulk/CDC sync are not eligible.

## When to use this skill

- "I want to give my customers a way to query their own data via HogQL."
- "Set up tenant_query on the supabase source."
- "Enable predicate rewriting for the orders table per customer."
- "How do I make the data warehouse multi-tenant for my customers?"

## Available tools

| Tool                             | Purpose                                                                              |
| -------------------------------- | ------------------------------------------------------------------------------------ |
| `external-data-sources-list`     | Find existing direct-Postgres sources before creating a new one                      |
| `external-data-sources-wizard`   | Look up the field names Postgres expects (host, port, dbname, user, password)        |
| `external-data-sources-create`   | Create a new direct-Postgres source (pass `access_method: "direct"` in the payload)  |
| `external-data-sources-retrieve` | Inspect a source's discovered schemas and confirm the tenant column exists per table |
| `tenant-query-config-set`        | Enable / disable tenant_query and set the tenant column                              |
| `tenant-query-run`               | Run a HogQL SELECT as a specific tenant to verify the setup end-to-end               |

For reading the current configuration, query the `system.tenant_query_configs` table via the SQL tool — see
[models-data-warehouse.md](../../../posthog_ai/skills/querying-posthog-data/references/models-data-warehouse.md#tenant-query-configs-systemtenant_query_configs).

## The setup flow

```text
┌────────────────────────┐
│ 1. discover / create   │  Find an existing direct-Postgres source, or create one.
└──────────┬─────────────┘
           ▼
┌────────────────────────┐
│ 2. verify tenant col   │  Confirm the tenant column exists on every table you'll expose.
└──────────┬─────────────┘
           ▼
┌────────────────────────┐
│ 3. configure           │  Enable tenant_query and pick the tenant column.
└──────────┬─────────────┘
           ▼
┌────────────────────────┐
│ 4. verify              │  Run a scoped query and confirm rows are tenant-isolated.
└────────────────────────┘
```

## Workflow

### Step 1 — Find or create a direct-Postgres source

Call `external-data-sources-list`. Filter results client-side for `source_type == "Postgres"` and
`access_method == "direct"`. If a matching source already exists, capture its `id` (this becomes the
`connection_id` everywhere else).

If it already has tenant_query configured and you just want to inspect the current state, query the system table
instead of running through the setup again:

```sql
SELECT c.enabled, c.tenant_column_name, c.tenant_column_type,
       c.default_timeout_ms, c.max_timeout_ms, c.max_result_limit
FROM system.tenant_query_configs AS c
INNER JOIN system.data_warehouse_sources AS s ON c.external_data_source_id = s.id
WHERE s.source_type = 'Postgres'
```

If a config row exists with `enabled = true`, the source is already set up — skip to Step 4 to verify.
If `enabled = false` or no row exists, continue to Step 2.

If no direct source exists, you need to create one. The standard
[setting-up-a-data-warehouse-source](../setting-up-a-data-warehouse-source/SKILL.md) flow assumes bulk sync, so adapt
it:

- Call `external-data-sources-wizard` and grab the `Postgres` entry's required fields.
- Collect credentials from the user. For Supabase specifically, use the **Session Pooler**
  (`aws-1-<region>.pooler.supabase.com:5432`) and a user shaped like `postgres.<project-ref>` — the direct host
  (`db.<ref>.supabase.co`) is IPv6-only on the free tier and PostHog's data warehouse needs IPv4.
- Call `external-data-sources-create` with `access_method: "direct"` in the payload. Direct sources still need a
  `prefix` — pick a meaningful name like `supabase`, `customers_db`, etc. The prefix becomes part of the table names
  the user will type in tenant queries (or, depending on schema setup, just the source identifier).

Direct sources don't actually sync data — PostHog stores connection metadata and a schema snapshot, and queries the
customer's Postgres live on each request.

### Step 2 — Verify the tenant column exists on every table you plan to expose

Call `external-data-sources-retrieve({id})`. Walk the `schemas` array and confirm every table the customer will
query has a column matching the tenant column you intend to use (e.g. `customer_id`, `account_id`, `tenant_id`).

Tables missing the column will be silently disabled by `tenant-query-config-set` and listed in the response's
`disabled_tables` — that's by design (a query that bypasses the predicate must not be allowed) but it surprises
users. Inspect the schema first and tell the user up front which tables won't be queryable.

If a critical table is missing the column, the user has two options:

1. Add the column to the source database and re-sync the schema
   (`external-data-sources-refresh-schemas` then call this step again).
2. Materialize a view in their Postgres that joins the column in, then expose the view instead.

Don't try to work around it on the PostHog side — the whole point of tenant_query is that the predicate is enforced
on every enabled table.

### Step 3 — Configure tenant_query

Call `tenant-query-config-set` with:

```json
{
  "connection_id": "<source id from Step 1>",
  "enabled": true,
  "tenant_column_name": "customer_id"
}
```

Optional limits:

- `default_timeout_ms` — applied when an end-user query doesn't specify `timeout_ms`. Default is 30000 (30s).
- `max_timeout_ms` — cap on end-user-supplied `timeout_ms`. Default is 120000 (2m).
- `max_result_limit` — max rows returnable per query. Default is 100000.

Tighten these for production-customer exposure; defaults are fine for a demo.

The response confirms:

- `tenant_column_type` — `integer`, `string`, or `uuid`, auto-detected from Postgres column metadata. This determines
  how `tenant_value` is coerced and how the predicate is rendered. The user doesn't pick this — it follows the
  Postgres column type.
- `enabled_tables` — tables that have the column and are now tenant-scoped.
- `disabled_tables` — tables that lacked the column and were excluded. **Read this list out loud to the user** —
  silent table drops are a footgun.

Configuring tenant_query requires project-admin access. If the API returns "Project admin access is required",
direct the user to a team member with admin rights.

### Step 4 — Verify with a tenant-scoped query

Call `tenant-query-run` with:

```json
{
  "connection_id": "<source id>",
  "tenant_value": "<a real tenant id from the customer's data>",
  "query": "SELECT count(*) FROM <one_of_the_enabled_tables>"
}
```

The response includes a `hogql` field showing the rewritten query — verify the predicate
(e.g. `equals(customer_id, ...)`) is present. The `results` array is the actual Postgres roundtrip.

Re-run with a different `tenant_value` and confirm the count or first few row IDs differ — that's how you prove the
predicate is actually filtering rather than getting silently dropped.

If you get a HogQL error about the table being unknown, the table was disabled in Step 3 because it lacked the
tenant column. Go back and either pick a different table or fix the column.

## Important notes

- **tenant_query is only for `access_method=direct` Postgres sources.** It doesn't apply to bulk-synced or CDC
  sources — those store data in PostHog's warehouse, not the customer's Postgres, so the predicate-rewriting model
  doesn't fit.
- **The agent / LLM never sets `tenant_value` for an end customer.** This skill's `tenant-query-run` call is
  operator-trusted — you're using it to verify setup, not to serve end-customer traffic. End-customer traffic must
  flow through the host application's REST or MCP layer that resolves the tenant from a server-trusted session
  (cookie, Bearer, etc.). The skill's verification calls should use a known test tenant, not a real customer's id.
- **`disabled_tables` is a security feature, not a bug.** If `tenant-query-config-set` returns a non-empty
  `disabled_tables`, it's because those tables lacked the column and exposing them would have leaked across tenants.
  Always surface that list to the user.
- **Auto-detected column type follows Postgres.** If the column is `uuid`, you must pass UUID-shaped strings as
  `tenant_value`; integer columns require integers. The service rejects type-mismatched values with a clean
  validation error.
- **Re-running `tenant-query-config-set` is idempotent.** Same payload twice is a no-op. Use it to widen the
  enabled-table set after adding the tenant column to more tables in the source database (re-run
  `external-data-sources-refresh-schemas` first to update the schema snapshot).
- **Disabling is also via this same tool.** `tenant-query-config-set` with `enabled: false` turns the service off
  for that connection. The configuration row is kept so re-enabling is a one-call operation.
