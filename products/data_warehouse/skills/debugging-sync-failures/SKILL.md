---
name: debugging-sync-failures
description: 'Diagnose and fix data warehouse sync failures in PostHog. Use when syncs are failing, tables are not updating, data appears stale, or the user reports errors with their data warehouse imports. Covers checking sync status, reading job logs, identifying common failure patterns, and suggesting fixes like resyncing, updating credentials, or changing sync configuration.'
---

# Debugging sync failures

This skill helps diagnose why a data warehouse sync is failing and guides toward a fix. The approach is: identify the failing schema, check job history, read logs, match the error pattern, and suggest the right remediation.

## When to use this skill

- The user says their data warehouse sync is failing or stuck
- The user reports stale or missing data from an imported source
- The user sees errors in the data warehouse UI
- The user asks "why is my Postgres/Stripe/etc sync not working?"

## Workflow

### 1. Identify the problem

Start by listing sources and their schemas to find which ones are unhealthy.

Call `posthog:external-data-sources-list` to see all sources. Look for sources with a `status` other than `Completed` or schemas with `latest_error` set.

Then call `posthog:external-data-schemas-list` for a full view of all table schemas. Key fields to check:

- **status**: `Running`, `Completed`, `Failed`, `Cancelled`
- **latest_error**: The most recent error message
- **last_synced_at**: When data was last successfully synced — if this is far in the past, syncs may be silently failing

If the user mentions a specific source or table, call `posthog:external-data-sources-retrieve` or `posthog:external-data-schemas-retrieve` to get details directly.

### 2. Check job history

Call `posthog:external-data-sources-jobs` with the source ID to see recent sync jobs. This returns:

- Job status (Running, Completed, Failed, Cancelled)
- Rows synced
- Created/finished timestamps
- Latest error per job

Look for patterns:

- **All recent jobs failing**: Likely a credential or connectivity issue
- **Intermittent failures**: Could be timeouts, rate limits, or transient network issues
- **Jobs completing with 0 rows**: The query may be returning empty results (incremental field issue)

### 3. Read sync logs

Call `posthog:external-data-sync-logs` with the schema ID to get detailed log entries. Use the `job_id` parameter (the `workflow_run_id` from the jobs response) to focus on a specific failed job.

Start with the default log level (LOG and above). If you need more detail, set `level: "DEBUG"`. Use the `search` parameter to filter for specific error messages.

### 4. Diagnose common failure patterns

**Credential failures:**

- Error mentions "authentication failed", "password", "access denied", "invalid API key"
- Fix: User needs to update credentials. They can use `posthog:external-data-sources-partial-update` to update `job_inputs` with new credentials, or delete and recreate the source.

**Connectivity issues:**

- Error mentions "connection refused", "timeout", "host not found", "SSL"
- Fix: Check if the database is accessible from PostHog's infrastructure. The user may need to allowlist PostHog's IP addresses or check firewall rules.

**Schema changes:**

- Error mentions "column not found", "relation does not exist", "table not found"
- Fix: The source schema has changed. Call `posthog:external-data-sources-refresh-schemas` to rediscover tables, then update sync configuration.

**Incremental field issues:**

- Syncs complete but return 0 rows, or data appears stale
- The incremental field value may have jumped or the column type changed
- Fix: Try a resync with `posthog:external-data-schemas-resync` to reset the incremental state, or change the incremental field via `posthog:external-data-schemas-partial-update`.

**Rate limiting (SaaS sources):**

- Error mentions "rate limit", "429", "too many requests"
- Fix: Reduce sync frequency via `posthog:external-data-schemas-partial-update` with a longer `sync_frequency` (e.g. `"24hour"` instead of `"1hour"`).

**Data type mismatches:**

- Error mentions "type mismatch", "cannot cast", "invalid value"
- Fix: This usually requires a resync. Call `posthog:external-data-schemas-resync` to re-import from scratch.

### 5. Apply the fix

Based on the diagnosis:

- **Update sync config**: `posthog:external-data-schemas-partial-update` — change sync_type, sync_frequency, incremental_field
- **Trigger a manual sync**: `posthog:external-data-schemas-reload` — retry with current config
- **Full resync**: `posthog:external-data-schemas-resync` — delete synced data and re-import from scratch (destructive)
- **Cancel stuck sync**: `posthog:external-data-schemas-cancel` — cancel a running sync that appears stuck
- **Refresh available schemas**: `posthog:external-data-sources-refresh-schemas` — rediscover tables after source schema changes
- **Delete and recreate**: As a last resort, `posthog:external-data-sources-destroy` and recreate with `posthog:external-data-sources-create`

Always confirm with the user before destructive actions (resync, delete).

### 6. Verify the fix

After applying a fix, wait for the next sync to complete and check:

- `posthog:external-data-schemas-retrieve` — verify status is `Completed` and `latest_error` is cleared
- `posthog:external-data-sync-logs` — check logs for the new sync job

## Important notes

- **Resync deletes existing data.** Always warn the user before calling resync — it drops all synced rows and re-imports from scratch.
- **Check logs before suggesting a resync.** A resync is the nuclear option. Most issues can be fixed by updating config or credentials.
- **Sync frequency affects load.** If a source is rate-limited, reducing sync frequency is better than retrying constantly.
- **CDC sources need special care.** CDC (change data capture) failures often involve replication slot issues on Postgres. These may require the user to check their database server directly.

## Related tools

- `posthog:external-data-sources-list`: List all sources with status
- `posthog:external-data-schemas-list`: List all table schemas with sync status
- `posthog:external-data-sources-retrieve`: Get source details
- `posthog:external-data-schemas-retrieve`: Get schema details
- `posthog:external-data-sources-jobs`: Get sync job history
- `posthog:external-data-sync-logs`: Get detailed sync logs
- `posthog:external-data-schemas-partial-update`: Update sync configuration
- `posthog:external-data-schemas-reload`: Trigger a manual sync
- `posthog:external-data-schemas-resync`: Full resync from scratch
- `posthog:external-data-schemas-cancel`: Cancel a running sync
- `posthog:external-data-sources-refresh-schemas`: Rediscover tables
