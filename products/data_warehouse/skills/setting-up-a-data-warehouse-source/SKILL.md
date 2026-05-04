---
name: setting-up-a-data-warehouse-source
description: >
  Guide the user through connecting a new data warehouse source — Postgres, MySQL, Stripe, Hubspot, MongoDB,
  Salesforce, BigQuery, Snowflake, and so on. Use when the user wants to "connect Stripe", "import data from
  Postgres", "add a new data source", "sync my warehouse tables", or wants to pick sync methods for each table. Walks
  through source-type discovery, credential validation, table discovery, per-table sync_type selection, and the
  final create call. Also covers picking a good prefix and what to do right after creation.
---

# Setting up a data warehouse source

Use this skill when the user wants to connect an external data source to PostHog's data warehouse for the first time.
The setup has a specific three-step flow (wizard → db-schema → create) — skipping steps leads to failed sources and
confused users.

## When to use this skill

- The user wants to connect a new source: "connect Stripe", "import my Postgres orders table", "sync Hubspot contacts"
- The user isn't sure what source types PostHog supports
- The user has credentials but doesn't know how to structure the `schemas` payload
- The user wants guidance on which sync method to pick per table

## Available tools

| Tool                                                   | Purpose                                                                          |
| ------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `external-data-sources-wizard`                         | Discover which source types exist and what fields each needs                     |
| `external-data-sources-db-schema`                      | Validate credentials and list tables with available sync methods per table       |
| `external-data-sources-create`                         | Create the source — requires a `schemas` array built from the db-schema response |
| `external-data-sources-check-cdc-prerequisites-create` | Postgres CDC pre-flight check (optional, only for Postgres CDC)                  |
| `external-data-sources-webhook-info-retrieve`          | Check if a source supports webhooks and whether one has been registered          |
| `external-data-sources-create-webhook-create`          | Register a webhook with the external service after source creation               |
| `external-data-sources-update-webhook-inputs-create`   | Supply the signing secret manually when auto-registration failed                 |
| `external-data-sources-list`                           | After creation, confirm the source is listed and see its initial status          |
| `external-data-schemas-list`                           | See per-table sync status once the source is created                             |

## The three-step flow

Every source setup follows the same shape. Don't try to shortcut to `external-data-sources-create` — you need the
db-schema response to build a valid `schemas` payload.

```text
         ┌────────────────────┐
         │ 1. wizard          │  What source types exist? What fields does each need?
         └────────┬───────────┘
                  ▼
         ┌────────────────────┐
         │ 2. db-schema       │  Validate creds. List tables + available sync methods per table.
         └────────┬───────────┘
                  ▼
         ┌────────────────────┐
         │ 3. create          │  Send source_type + credentials + schemas[] to actually create.
         └────────────────────┘
```

## Workflow

### Step 1 — Discover the source type

Call `external-data-sources-wizard` (no params). The response is a dict keyed by source type. Each entry describes:

- `name` — the canonical source_type string you'll pass to later calls (e.g. `"Postgres"`, `"Stripe"`, `"Hubspot"`).
- `label` / `caption` — human-readable.
- `fields` — the config fields needed (host, port, database, api_key, client_id/secret, ...). Each has `name`,
  `type` (input, password, switch, select, file-upload), and `required`.
- `featured`, `unreleasedSource` — use to gauge readiness. Skip sources marked `unreleasedSource: true` unless the
  user explicitly asked for a preview.

Match the user's request to a source. If they said "Postgres", look up `Postgres`. If they said something ambiguous
like "database", present the top relevant matches (Postgres, MySQL, MongoDB, BigQuery, Snowflake, Redshift) and let
them pick.

For OAuth-based sources (Hubspot, Salesforce, Google Ads), the wizard entry hints at an OAuth flow. These typically
need the user to authorize in the PostHog UI rather than pasting credentials — explain this and direct them to the
source setup page rather than trying to collect tokens in chat. OAuth is about _authentication_, not about how data
flows; OAuth sources still use polling bulk sync, not webhooks.

Gather the required credentials from the user. Never ask for more fields than the wizard entry says are required —
asking for an unnecessary `port` when the source doesn't need one confuses users.

### Step 2 — Validate credentials and discover tables

Call `external-data-sources-db-schema` with `source_type` plus all credential fields. This does two things at once:

1. Validates the credentials against the live source. Returns 400 with a `message` if anything is wrong (bad host,
   wrong password, permission denied). Show the error verbatim — it's often actionable ("password authentication
   failed for user 'x'").
2. If valid, returns an array of table entries. Each entry:

```text
{
  "table": "orders",
  "should_sync": false,
  "rows": 1_250_000,
  "incremental_available": true,   # can do sync_type=incremental
  "append_available": true,        # can do sync_type=append
  "cdc_available": true,           # can do sync_type=cdc  (null = not enabled for team)
  "supports_webhooks": false,      # can do sync_type=webhook for real-time push
  "incremental_fields": [          # candidates: usually updated_at, created_at, id
    {"field": "updated_at", "type": "datetime", "label": "updated_at", ...},
    {"field": "created_at", "type": "datetime", ...},
    {"field": "id", "type": "integer", ...}
  ],
  "detected_primary_keys": ["id"],
  "available_columns": [{"field": "id", "type": "integer", "nullable": false}, ...],
  "description": "..."
}
```

Present this to the user. Don't dump the raw JSON — summarize: which tables were found, row counts, and the default
sync method recommendation per table (see [sync-type decision guide](./references/sync-types.md)).

### Step 3 — Confirm per-table sync configuration

For each table the user wants to sync, pick a sync_type. See the
[sync-type decision guide](./references/sync-types.md) for detailed rules, but the short version is:

- **Small / dimension tables (<50k rows, no natural ordering column):** `full_refresh` — simple and always correct.
- **Large tables with an `updated_at` / `modified_at`:** `incremental` — much cheaper per sync.
- **Append-only immutable tables (logs, events):** `append` if available — preserves history.
- **Postgres with CDC enabled and you need near-real-time:** `cdc` — requires primary keys and Postgres prerequisites.
- **Sources that support webhooks (currently Stripe):** for near-real-time ingestion set `sync_type: "webhook"` on
  the tables where `supports_webhooks: true`, then register the webhook as a post-create step (see step 6 below).
  Tables that don't support webhooks on the same source still need a bulk sync_type.

For each schema that will use `incremental`/`append`/`cdc`, you also need:

- `incremental_field` — which column to track for high-water-mark ordering. Pick from the `incremental_fields` list
  returned by db-schema. Prefer `updated_at` over `created_at` (updated_at catches late-arriving updates;
  created_at misses them). For integer-only tables, use the monotonically increasing primary key.
- `incremental_field_type` — must match the chosen field's type (`datetime`, `timestamp`, `date`, `integer`,
  `numeric`, `objectid`).
- `primary_key_columns` — required for CDC. Use `detected_primary_keys` from db-schema.

### Step 4 — Pick a good prefix

The source's `prefix` is prepended to table names in HogQL. Tables end up as `{prefix}_{table_name}`.

- Default to the source type lowercased if there's only one source of that type: `stripe`, `postgres`.
- If the user already has a Postgres source, pick something distinguishing: `postgres_prod`, `postgres_analytics`.
- Use lowercase, underscore-separated. The prefix becomes part of every HogQL query the user writes.

Confirm the prefix with the user before creating — changing it later is possible but renames every table.

### Step 5 — Create the source

Call `external-data-sources-create` with:

```json
{
  "source_type": "Postgres",
  "prefix": "postgres_prod",
  "payload": {
    "host": "...",
    "port": "5432",
    "dbname": "...",
    "user": "...",
    "password": "...",
    "schema": "public",
    "schemas": [
      {
        "name": "orders",
        "should_sync": true,
        "sync_type": "incremental",
        "incremental_field": "updated_at",
        "incremental_field_type": "datetime",
        "primary_key_columns": ["id"]
      },
      {
        "name": "users",
        "should_sync": true,
        "sync_type": "full_refresh"
      },
      {
        "name": "audit_log",
        "should_sync": false
      }
    ]
  }
}
```

Rules for the `schemas` array:

- Every table returned by db-schema should be included, even ones the user doesn't want (set `should_sync: false`).
  Tables the user didn't mention default to `should_sync: false`.
- `sync_type` is required only when `should_sync: true`.
- `incremental_field` / `incremental_field_type` must be present when `sync_type` is `incremental` or `append`.
- `primary_key_columns` must be present when `sync_type` is `cdc`.

On success you'll get back a source with a new `id`. The first sync is triggered automatically.

### Step 6 — Register a webhook (only when any schema is `sync_type: "webhook"`)

Webhook-type schemas don't start receiving data just by existing — the external service needs to know where to POST
events, and PostHog needs to know how to verify them. This is a second call after source creation, not part of the
`external-data-sources-create` payload. Do this **before** telling the user the setup is complete, otherwise they
hear "syncs are running" while the push channel is still unregistered.

Only needed when at least one schema on the source has `sync_type: "webhook"` and `should_sync: true`. Currently only
Stripe implements this flow; for everything else skip this step.

Before calling create-webhook, check `external-data-sources-webhook-info-retrieve({id})`. If it already returns
`exists: true`, do NOT call create-webhook again — each successful call registers a new external endpoint and would
result in duplicate deliveries.

1. Call `external-data-sources-create-webhook-create({id})`. PostHog:
   - creates the HogFunction that will receive webhook POSTs,
   - builds a schema_mapping from external event types to PostHog schema ids,
   - calls the source's API (e.g. Stripe) to register the webhook URL and subscribe to the relevant events,
   - on Stripe, auto-captures the `signing_secret` and stores it securely.

   Returns `{success, webhook_url, error}`. On success report the `webhook_url` to the user for their records — but
   they don't need to paste it anywhere; registration is already done.

2. If `success: false` with a permissions error like "API key doesn't have permission to create webhooks":
   - The HogFunction is still created, just disabled.
   - Ask the user to create the webhook manually in the source's dashboard using the returned `webhook_url`.
   - Have them copy the signing secret from the source's webhook settings.
   - Call `external-data-sources-update-webhook-inputs-create({id}, {inputs: {signing_secret: "whsec_..."}})` to
     store it. The HogFunction picks it up and verifies incoming payloads.

3. Verify with `external-data-sources-webhook-info-retrieve({id})`. A healthy webhook has `exists: true`,
   `external_status.status: "enabled"`, and no `error`.

Webhooks are supplementary to bulk sync. The first load of a webhook-enabled schema is still done via polling
(`initial_sync_complete` flips to true when done); after that, the webhook becomes the primary ingestion path. A
webhook schema will still have a `sync_frequency` that schedules a periodic bulk refresh as a safety net. This is
expected — not something to "fix".

### Step 7 — Confirm and explain what happens next

After creation (and, for webhook schemas, after Step 6):

- Call `external-data-schemas-list` to show the user the initial state.
- Explain: every enabled schema enters `Running`, then moves to `Completed` when the first sync finishes. First
  syncs can take anywhere from seconds to hours depending on row count — a multi-million-row table is fine, just
  slow.
- Tell them how to query: `SELECT * FROM {prefix}_{table_name} LIMIT 10` in HogQL.
- Offer to check back in a few minutes to confirm the initial syncs succeeded.

## CDC setup for Postgres (optional, when requested)

If the user wants near-real-time replication from Postgres:

1. Before calling db-schema, run `external-data-sources-check-cdc-prerequisites-create` with their Postgres creds.
   It returns `{valid, errors[]}` listing anything missing (wal_level, replication slot, publication, permissions).
2. If `valid: false`, present the errors and ask the user to fix on the Postgres side. Don't try to create a CDC
   source that will immediately fail.
3. Once prerequisites pass, proceed to db-schema and create. Set `sync_type: "cdc"` on the tables that need it, and
   include `primary_key_columns` for each (CDC requires them).

## Important notes

- **Always validate creds with db-schema before create.** The create endpoint will accept invalid creds and then fail
  asynchronously — the source appears in the list with status `Error` and no tables. Skipping the validation step
  just pushes the failure into the background.
- **Present the table list before creating.** Large databases may have hundreds of tables. Don't auto-select them all
  — row counts and relevance matter for billing. Let the user opt in explicitly.
- **Don't invent schemas.** Every entry in the `schemas` array must correspond to a real table from the db-schema
  response. You can't "also add an orders table" unless db-schema found one.
- **Prefix is load-bearing.** It's part of every HogQL query the user will ever write against these tables. Pick
  something short, descriptive, and not already taken.
- **OAuth sources are different.** Hubspot, Salesforce, Google Ads etc. need the user to authorize via the PostHog
  UI. Direct them there — don't try to collect OAuth tokens in chat.
- **Webhooks are a separate step after create.** Setting `sync_type: "webhook"` on a schema doesn't register the
  webhook — the `create-webhook` call does. Always follow create → create-webhook → webhook-info for webhook-type
  schemas, and never leave a webhook schema dangling without registration (it just won't receive events).
- **Webhook support is source-specific and sparse.** Currently only Stripe implements `WebhookSource`. Don't promise
  webhooks for Hubspot, Salesforce, or Postgres — they'll use polling sync.
- **Row counts drive billing.** Warehouse syncing is metered by rows synced. A chatty 500M-row events table synced
  hourly is very different from a 10k-row dimension table synced daily. Flag large tables and offer longer sync
  frequencies (`sync_frequency: "24hour"`) as the default.
