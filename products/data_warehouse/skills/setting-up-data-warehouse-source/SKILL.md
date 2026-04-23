---
name: setting-up-data-warehouse-source
description: 'Guide for setting up a new data warehouse source connection in PostHog. Use when the user wants to connect an external database (Postgres, MySQL, Stripe, Hubspot, etc.), import data into PostHog, or asks how to set up a data warehouse source. Covers the full flow: discovering available source types, validating credentials, previewing tables, choosing sync configuration, and creating the source.'
---

# Setting up a data warehouse source

This skill walks through connecting an external data source to PostHog's data warehouse. The flow has three phases: discover what's available, validate and preview, then create with the right sync configuration.

## When to use this skill

- The user wants to connect an external database or SaaS tool to PostHog
- The user asks "how do I import data from X?" or "can I connect my Postgres/Stripe/etc?"
- The user wants to sync external data into PostHog for querying with HogQL

## Workflow

### 1. Discover available source types

Call `posthog:external-data-sources-wizard` to get the full list of supported sources and their required credential fields. Present a summary to the user — don't dump the raw output.

If the user already knows their source type, skip to step 2. If they're exploring, highlight the most common sources (Postgres, MySQL, Stripe, Hubspot, Salesforce, Snowflake, BigQuery) and ask what they're looking to connect.

### 2. Collect credentials

Each source type requires different credentials. The wizard response includes `fields` for each source type describing what's needed (host, port, API key, OAuth, etc.).

For database sources (Postgres, MySQL, etc.), you'll typically need: host, port, database, user, password, and schema.

For SaaS sources (Stripe, Hubspot, etc.), you'll typically need an API key or OAuth connection.

Ask the user for the required credentials. Be explicit about what's needed — don't ask for fields that aren't required for their source type.

### 3. Validate credentials and discover tables

Call `posthog:external-data-sources-db-schema` with the source type and credentials. This validates the connection and returns available tables with metadata:

- **Table name** and row count
- **Available sync methods**: incremental, full_refresh, append, CDC
- **Incremental fields**: columns that can track sync progress (e.g. `updated_at`, `id`)
- **Detected primary keys**: for deduplication
- **Column definitions**: field names, types, and nullability

Present this to the user in a readable format. For each table, show the name, row count, and available sync methods. Let the user choose which tables to sync and how.

### 4. Help choose sync configuration

For each table the user wants to sync, they need to decide:

- **sync_type**: How data is synced
  - `full_refresh` — re-imports all rows every sync. Simplest but slowest for large tables.
  - `incremental` — only syncs new/changed rows based on an incremental field. Best for large tables with a reliable timestamp or auto-incrementing ID.
  - `append` — adds new rows only, never updates existing ones. Good for event/log tables.
  - `cdc` (Postgres only) — change data capture via logical replication. Real-time but requires Postgres configuration.

- **incremental_field**: Required for incremental/append syncs. Choose a column that reliably increases (e.g. `updated_at`, `created_at`, `id`).

- **primary_key_columns**: For deduplication. Usually auto-detected but can be overridden.

Recommend incremental sync with `updated_at` when available — it's the best balance of speed and data freshness. Fall back to `full_refresh` for small tables or when no good incremental field exists.

### 5. Create the source

Call `posthog:external-data-sources-create` with:

- `source_type`: The source type name
- `payload`: Credentials dict plus a `schemas` array where each entry has:
  - `name`: table name from db-schema response
  - `should_sync`: `true` for tables to sync
  - `sync_type`: chosen sync method
  - `incremental_field` and `incremental_field_type`: if using incremental/append
  - `primary_key_columns`: if overriding auto-detected PKs
- `prefix`: Optional table name prefix in HogQL (useful to avoid name collisions)
- `description`: Optional human-readable description

After creation, the first sync starts automatically via Temporal. Tell the user they can check sync status with `posthog:external-data-schemas-list`.

### 6. Verify setup

After creation, call `posthog:external-data-sources-retrieve` with the new source ID to confirm it was created correctly. Show the user:

- Source type and prefix
- Number of schemas created
- Sync status of each schema

## Important notes

- **Credentials are stored securely.** Reassure users that credentials are encrypted at rest and never exposed in the UI after creation.
- **Prefix prevents collisions.** If the user has multiple sources of the same type (e.g. two Postgres databases), suggest using a prefix to namespace the tables in HogQL.
- **CDC requires Postgres setup.** If the user wants CDC, they need to enable logical replication on their Postgres instance. The `posthog:external-data-sources-wizard` response includes docs links for this.
- **Don't sync everything.** For large databases, recommend starting with the tables the user actually needs. More tables means more sync load and storage.

## Related tools

- `posthog:external-data-sources-wizard`: Get available source types and required fields
- `posthog:external-data-sources-db-schema`: Validate credentials and preview tables
- `posthog:external-data-sources-create`: Create the source connection
- `posthog:external-data-sources-retrieve`: Get source details after creation
- `posthog:external-data-schemas-list`: Check sync status of all table schemas
