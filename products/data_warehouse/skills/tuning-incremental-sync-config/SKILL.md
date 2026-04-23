---
name: tuning-incremental-sync-config
description: >
  Change the sync configuration of an existing data warehouse schema — switch sync_type, pick a different
  incremental_field, set primary_key_columns, choose cdc_table_mode, or change sync_frequency. Use when the user
  asks "switch my orders table from full refresh to incremental", "this table is syncing too slowly / too
  frequently", "I need to pick a different incremental column", "set up CDC for this Postgres table", or when
  diagnosis of a failing sync pointed to an incremental-field or PK misconfiguration.
---

# Tuning incremental sync config

A sync's configuration lives on the `ExternalDataSchema` and can be changed any time via
`external-data-schemas-partial-update`. Most changes are non-destructive (take effect on the next sync), but a few
(switching sync_type, changing primary keys) require careful handling to avoid corrupting the synced data.

## When to use this skill

- The user wants to change how an already-connected table is synced
- A diagnosis flagged the incremental field or primary key as wrong
- The table is syncing too often / not often enough
- Switching an incremental table to CDC (or vice versa)
- The source table was changed on the other side (new columns, dropped columns) and the sync config needs to catch up

If the user is setting up a brand-new source, use `setting-up-a-data-warehouse-source` instead — configuration is
chosen at creation time there.

## Available tools

| Tool                                                   | Purpose                                                                   |
| ------------------------------------------------------ | ------------------------------------------------------------------------- |
| `external-data-schemas-retrieve`                       | Current sync_type, incremental_field, PKs, sync_frequency                 |
| `external-data-schemas-incremental-fields-create`      | Refresh candidate incremental fields from the live source                 |
| `external-data-schemas-partial-update`                 | Apply the config change                                                   |
| `external-data-schemas-reload`                         | Trigger a sync with the new config                                        |
| `external-data-schemas-resync`                         | Wipe and re-import from scratch when the change invalidates existing data |
| `external-data-schemas-delete-data`                    | Drop the synced table while keeping the schema entry                      |
| `external-data-sources-check-cdc-prerequisites-create` | Pre-flight Postgres CDC (only when switching to/from CDC)                 |
| `external-data-sources-webhook-info-retrieve`          | Current webhook state (when switching to/from sync_type=webhook)          |
| `external-data-sources-create-webhook-create`          | Register a webhook after switching a schema to sync_type=webhook          |
| `external-data-sources-update-webhook-inputs-create`   | Rotate a webhook signing secret                                           |
| `external-data-sources-delete-webhook-create`          | Unregister webhook when switching schemas off sync_type=webhook           |

## The fields you can tune

From the partial-update endpoint:

| Field                    | Values                                                                                           | Notes                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `sync_type`              | `full_refresh`, `incremental`, `append`, `cdc`, `webhook`                                        | Source must support the target type — check via incremental-fields |
| `incremental_field`      | Column name from the source                                                                      | Must appear in `incremental_fields` list for the schema            |
| `incremental_field_type` | `datetime`, `date`, `timestamp`, `integer`, `numeric`, `objectid`                                | Must match the column's real type                                  |
| `primary_key_columns`    | Array of column names                                                                            | Required for CDC. Used for upsert dedup on incremental             |
| `cdc_table_mode`         | `consolidated`, `cdc_only`, `both`                                                               | Only meaningful when sync_type=cdc                                 |
| `sync_frequency`         | `1min`, `5min`, `15min`, `30min`, `1hour`, `6hour`, `12hour`, `24hour`, `7day`, `30day`, `never` | Applies to all non-CDC types                                       |
| `sync_time_of_day`       | `HH:MM:SS`                                                                                       | When sync_frequency is daily/weekly-scale                          |
| `should_sync`            | `true` / `false`                                                                                 | Pause the schema without deleting it                               |

## Workflow

### Step 1 — Read the current config

Always start with `external-data-schemas-retrieve({id})`. Understanding the current state prevents mistakes like
"fixing" an incremental_field that's actually correct.

Note:

- Current `sync_type`, `incremental_field`, `incremental_field_type`, `primary_key_columns`
- Current `status` (don't tune a schema that's currently `Running` — wait or cancel first)
- `last_synced_at` (so you can tell if the next sync worked)
- `latest_error` if present (the error often tells you exactly what to change)

### Step 2 — If changing sync_type or incremental_field, refresh candidates

Call `external-data-schemas-incremental-fields-create({id})`. Even though the operation name says "create", it
re-reads the source and returns the current candidate fields — use it to confirm the field you want to set actually
exists on the source and which sync types are now available for this table.

The response:

```text
{
  "incremental_fields": [{"field": "updated_at", "type": "datetime", ...}, ...],
  "incremental_available": true,
  "append_available": true,
  "cdc_available": true,
  "full_refresh_available": true,
  "detected_primary_keys": ["id"],
  "available_columns": [...]
}
```

If your target `incremental_field` isn't in the list, tell the user — they need to either pick a different field or
change the source table to add one.

### Step 3 — Apply the change

Call `external-data-schemas-partial-update({id}, {...changed fields})`.

**Only send the fields that are actually changing.** Partial update means unspecified fields stay as they are.

Examples:

```json
// Switch from full_refresh to incremental
{
  "sync_type": "incremental",
  "incremental_field": "updated_at",
  "incremental_field_type": "datetime"
}

// Change sync frequency to hourly
{"sync_frequency": "1hour"}

// Fix wrong PK on a CDC table
{"primary_key_columns": ["tenant_id", "order_id"]}

// Pause a schema
{"should_sync": false}
```

### Step 4 — Decide whether existing data is still valid

This is the step that's easy to get wrong. Some config changes invalidate the synced data; others don't.

**Changes that DON'T invalidate existing data:**

- `sync_frequency`, `sync_time_of_day` — scheduling only
- `should_sync` — on/off
- `cdc_table_mode` in most cases — next sync will start writing to the new shape, but historical consolidated rows
  stay valid
- Switching between `incremental` and `full_refresh` with the same `incremental_field` — next sync just re-runs
  fresh
- Switching to or from `sync_type: "webhook"` — the synced data stays valid; only the ingestion path changes.
  Remember to register or unregister the webhook (see sections below) alongside the sync_type change.

**Changes that MAY invalidate existing data and need a resync:**

- Changing `incremental_field` to a different column — the high-water mark is from the old column and won't match.
  Without a resync you'll miss rows that were updated between the two fields' histories.
- Changing `primary_key_columns` — existing rows may be deduplicated incorrectly against new PK definitions.
- Switching from `full_refresh` to `append` — the existing rows don't have the version-history shape that append
  expects.
- Switching from `append` to `full_refresh` — opposite problem; you'll end up with duplicate historical versions.
- Switching to/from `cdc` — the table shape changes fundamentally.

When the change invalidates data, the clean flow is:

1. `external-data-schemas-partial-update` with the new config
2. Warn the user this is destructive
3. `external-data-schemas-resync` to wipe and re-import under the new config

Or equivalently, `external-data-schemas-delete-data` → `external-data-schemas-reload`. `delete-data` + `reload` is
cleaner when the table is large and the user wants to start from zero.

### Step 5 — Trigger and confirm

For non-destructive changes, call `external-data-schemas-reload({id})` to pick up the new config immediately rather
than waiting for the schedule.

Wait a moment, then `external-data-schemas-retrieve({id})` to confirm `status = Running` then `Completed`. Report
`last_synced_at` and any new `latest_error`.

## Specific common changes

### Switching full_refresh → incremental

1. `incremental-fields-create` to confirm the desired field exists and `incremental_available: true`.
2. `partial-update`: `{sync_type: "incremental", incremental_field, incremental_field_type}`.
3. No data wipe needed — next sync just switches strategy. If the source is growing fast, the next incremental sync
   is the cheap one.

### Switching incremental → cdc (Postgres only)

1. Run `external-data-sources-check-cdc-prerequisites-create` on the parent source. Only proceed if `valid: true`.
2. `incremental-fields-create` to confirm `cdc_available: true` and see `detected_primary_keys`.
3. `partial-update`: `{sync_type: "cdc", primary_key_columns: [...], cdc_table_mode: "consolidated"}`.
4. **Resync required** — CDC tables have a different shape. Trigger `external-data-schemas-resync` after the update.
   Warn the user this wipes existing data.

### Fixing a stale incremental field after schema drift

Source dropped the `updated_at` column. Sync has been failing with "column does not exist".

1. `incremental-fields-create` to see what fields remain.
2. Pick a replacement (or switch to `full_refresh` if none are suitable).
3. `partial-update` with the new field + type (or new sync_type).
4. `reload` to retry.

### Changing primary keys on a CDC table

1. `partial-update`: `{primary_key_columns: [...]}`.
2. **Resync required** — existing CDC tombstones and upsert keys won't match the new PK definition, leading to row
   duplication or missed updates.
3. `resync`, warn the user.

### Changing sync_frequency

1. `partial-update`: `{sync_frequency: "1hour"}`.
2. No reload needed — the next scheduled sync picks up the new cadence. Or reload manually if the user wants to
   confirm nothing broke.

### Switching a schema to `sync_type: "webhook"`

Only works for sources that implement `WebhookSource` (today: Stripe) and tables where `supports_webhooks: true`
from `incremental-fields-create`.

1. `incremental-fields-create` to confirm `supports_webhooks: true` for the table.
2. `partial-update`: `{sync_type: "webhook"}`.
3. If the source doesn't already have a webhook registered (check with `webhook-info-retrieve`), call
   `external-data-sources-create-webhook-create({source_id})` to register it.
4. No resync required — the schema's existing bulk-synced data stays, and the webhook becomes the primary ingestion
   path once the next reconciliation finishes.
5. Keep `sync_frequency` set (e.g. `24hour`) — it acts as a safety-net reconciliation in case any webhook delivery
   is missed.

### Switching off `sync_type: "webhook"`

1. `partial-update`: `{sync_type: "incremental"}` (or whatever bulk type is appropriate) with the required
   `incremental_field` + `incremental_field_type`.
2. If **no other schemas** on the source are still using `sync_type: "webhook"`, call
   `external-data-sources-delete-webhook-create({source_id})` to unregister. Leaving an orphaned webhook
   registered on the source side just means events will be received and dropped — not harmful, but messy.
3. If other schemas on the source are still on webhook, leave the webhook registered — it's shared across all
   webhook-type schemas on the source.

### Rotating a webhook signing secret

The source's signing secret (e.g. Stripe's `whsec_...`) was rotated, and payloads are now failing signature
verification.

1. Grab the new secret from the source's dashboard.
2. `external-data-sources-update-webhook-inputs-create({source_id}, {inputs: {signing_secret: "whsec_..."}})`.
3. No reload needed — the next inbound webhook payload will verify against the new secret.

### Pausing a schema

1. `partial-update`: `{should_sync: false}`. Schema stops syncing but stays configured.
2. To resume later: `partial-update`: `{should_sync: true}`, then `reload` for an immediate run.

## Important notes

- **Read before you write.** Always retrieve the current config first. `partial-update` doesn't complain if you set a
  field to the value it already had, but you might be about to change something you didn't realize was already set.
- **Not every sync_type is available on every schema.** The `incremental-fields-create` response tells you what's
  available _right now_, which can be different from what was available at creation (e.g. CDC may have been
  enabled for the team since).
- **Wipe when the shape changes.** Switching sync strategy often changes the physical table. If you don't resync,
  you'll be mixing row shapes and queries will return garbage.
- **CDC needs prerequisites.** Never switch to `sync_type: "cdc"` without running `check-cdc-prerequisites-create`
  first. The sync will just fail immediately.
- **Don't touch a Running schema.** If the schema is currently running, either wait for it to finish or
  `external-data-schemas-cancel` before applying the change. Updating config mid-sync can leave the incremental
  high-water mark inconsistent.
- **Sync frequency is cheap to change.** Encourage experimentation there. Sync_type and incremental_field are
  expensive to change — encourage care.
- **Webhooks are registered at the source level, not the schema level.** Multiple webhook-type schemas on the same
  source share one webhook registration. Only delete the webhook when the _last_ webhook-type schema on that
  source is being switched away, otherwise other schemas stop receiving pushes.
