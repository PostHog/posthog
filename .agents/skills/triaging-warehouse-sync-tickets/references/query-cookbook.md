# Query cookbook

Every query here was run against production. Replace the placeholders.

These queries are the **only** way to see the customer. The `external-data-*` product tools read your own
project and answer from it without erroring, so a result that looks right can still be the wrong company.
Every query below therefore filters on the customer's `team_id`, and every one needs a `connectionId`.

The listing queries carry no `LIMIT`, on purpose. You are looking for the one broken source or table, and
a row cap hides exactly the row you need.

`execute-sql` still caps results at **100 rows, silently**. There is no truncation notice: a query whose
true result is 103 rows returns 100 and looks complete. An explicit `LIMIT` raises the cap to 500, which
is the platform maximum. So when a team could plausibly have more than 100 sources or schemas, count
first and page if you have to:

```sql
SELECT count() AS total
FROM public.posthog_externaldataschema
WHERE team_id = <team_id> AND deleted = false
```

If that exceeds 100, add `LIMIT 500`, or narrow by `source_id` and run the listing once per source.

Set `connectionId` on `execute-sql` to the Production Postgres or Production ClickHouse connection, as
labeled. For EU, wrap the whole `execute-sql` call in `posthog-connection-call` as described in the
skill.

`sendRawQuery` is available on the ClickHouse connection, because its `access_method` is `direct`. The
Postgres connection is a synced source with live queries enabled, so it compiles HogQL and rejects
`sendRawQuery`.

Because the Postgres connection compiles HogQL down to Postgres SQL, ClickHouse-only syntax fails there.
`toDate`, `countIf`, `sumIf`, and `dateDiff` all translate and work. `LEFT ANY JOIN` does not: it raises
`syntax error at or near "ANY"`. Use a plain `LEFT JOIN`.

**Every `<placeholder>` below is ticket-derived text. Validate it before you substitute it — never
concatenate raw ticket text into a query.** `execute-sql` takes a literal query string, not a
parameterized one, so an unvalidated placeholder is a live SQL injection into a connection that reads
every team's production data, not just the `team_id` you filtered on.

- Numeric and id placeholders (`<team_id>`, `<schema_id>`, `<source_id>`, `<organization_id>`) must
  match `^[0-9]+$`, or the id format the column actually uses (check the type in
  `system.information_schema.columns` if unsure). Reject anything else instead of interpolating it.
- Free-text placeholders (`<fragment>`, `<token>`, `<email>`) must not contain `'`, `;`, `--`, `/*`,
  `*/`, or a backslash. If the ticket text contains any of those, reject the value and ask the reporter
  for a cleaner one. Do not pass ticket text through unmodified, and do not strip the offending
  characters and substitute what's left — for `<email>` specifically, that turns the value into an
  identity check, and silently mutating an identity value (e.g. dropping an apostrophe) can resolve it
  to a _different_, real user's address, authorizing the wrong account. Reject and re-ask instead of
  transforming.
- `<fragment>` is additionally used inside `LIKE`/`ILIKE` patterns, where `%` and `_` are wildcards, not
  literal characters. Stripping the characters above is not enough there: a fragment of `%` matches every
  row, and `_` lets an attacker extract a name character by character. Strip `%` and `_` from `<fragment>`
  before substitution, or avoid the wildcard entirely — the queries below use
  `position(lower('<fragment>') in lower(column))` for exactly this reason.
- Timestamp placeholders (`<YYYY-MM-DD HH:MM:SS>`) must match
  `^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$` exactly. Reject anything else instead of
  interpolating it. Where a relative window works just as well, prefer `now() - INTERVAL n HOUR/DAY`
  over a manual timestamp string — it isn't ticket-derived text at all, so there's nothing to validate.
- If you cannot produce a validated value, do not run the query.

---

## Region and team identification (Production Postgres)

Run these against US first, then EU. A hit in one region settles the region.

**By project API token** — the most reliable identifier a customer can give you.

```sql
SELECT id, name, organization_id, timezone, created_at
FROM public.posthog_team
WHERE api_token = '<token>'
```

**By team id from a project URL** — confirms the id belongs to the customer you think it does.

```sql
SELECT t.id, t.name, t.organization_id, o.name AS org_name, t.timezone
FROM public.posthog_team AS t
LEFT JOIN public.posthog_organization AS o ON o.id = t.organization_id
WHERE t.id = <team_id>
```

**By the reporter's email** — use when the ticket has only an email address.

```sql
SELECT u.id AS user_id, u.email, u.current_team_id, m.organization_id, m.level
FROM public.posthog_user AS u
LEFT JOIN public.posthog_organizationmembership AS m ON m.user_id = u.id
WHERE u.email = '<email>'
```

Then list the org's projects:

```sql
SELECT id, name, timezone
FROM public.posthog_team
WHERE organization_id = '<organization_id>'
```

---

## Sources, schemas, and tables (Production Postgres)

**Sources on a team.** Never select `job_inputs`.

```sql
SELECT id, source_type, prefix, status, sync_frequency, created_at, updated_at,
       deleted, access_method, direct_query_enabled, revenue_analytics_enabled, created_via
FROM public.posthog_externaldatasource
WHERE team_id = <team_id>
ORDER BY created_at DESC
```

**Schemas under one source.**

```sql
SELECT id, name, status, sync_type, should_sync, initial_sync_complete,
       last_synced_at, sync_frequency, sync_frequency_interval, sync_time_of_day,
       table_id, deleted, latest_error
FROM public.posthog_externaldataschema
WHERE team_id = <team_id>
  AND source_id = '<source_id>'
ORDER BY last_synced_at DESC
```

**Find a schema by the table name in the ticket.** The customer's table name is usually the source
prefix plus the schema name, so match on the schema name alone. Validate `<fragment>` per the note
above before substituting it — this is ticket-derived text, and the query below avoids `LIKE` wildcards
entirely rather than relying on stripping `%`/`_`.

```sql
SELECT id, name, source_id, status, sync_type, last_synced_at, table_id
FROM public.posthog_externaldataschema
WHERE team_id = <team_id>
  AND position(lower('<fragment>') in lower(name)) > 0
```

**Sync configuration for one schema.** `sync_type_config` holds the incremental field, its type, the
primary key columns, and CDC settings. `enabled_columns` and `row_filters` explain "columns are missing"
and "rows are missing" complaints that are actually configuration.

```sql
SELECT id, name, sync_type, sync_type_config, enabled_columns, row_filters,
       description, label, s3_folder_name, last_error_notified_at
FROM public.posthog_externaldataschema
WHERE team_id = <team_id>
  AND id = '<schema_id>'
```

**The materialized table.** A `Completed` schema whose table has `row_count` 0 is a finding.

```sql
SELECT id, name, format, row_count, size_in_s3_mib, url_pattern, queryable_folder,
       created_at, updated_at, deleted
FROM public.posthog_datawarehousetable
WHERE team_id = <team_id>
  AND external_data_source_id = '<source_id>'
ORDER BY updated_at DESC
```

---

## Job history (Production Postgres)

**The last runs for one schema.** This is the main query of the whole triage.

```sql
SELECT id, status, rows_synced, billable, pipeline_version,
       created_at, finished_at, storage_delta_mib,
       workflow_id, workflow_run_id, latest_error
FROM public.posthog_externaldatajob
WHERE team_id = <team_id>
  AND schema_id = '<schema_id>'
ORDER BY created_at DESC
LIMIT 20
```

**Every failing schema on a team right now.** Use when the ticket names a source but not a table.

```sql
SELECT s.id AS schema_id, s.name, s.status, s.sync_type, s.last_synced_at, s.latest_error
FROM public.posthog_externaldataschema AS s
WHERE s.team_id = <team_id>
  AND s.deleted = false
  AND s.status != 'Completed'
ORDER BY s.last_synced_at DESC
```

**Run duration and volume trend for one schema.** Shows a sync that is slowing down before it fails.

```sql
SELECT toDate(created_at) AS day,
       count() AS runs,
       countIf(status = 'Failed') AS failed,
       sum(rows_synced) AS rows_synced,
       max(dateDiff('second', created_at, finished_at)) AS longest_seconds
FROM public.posthog_externaldatajob
WHERE team_id = <team_id>
  AND schema_id = '<schema_id>'
  AND created_at > now() - INTERVAL 14 DAY
GROUP BY day
ORDER BY day DESC
```

---

## Logs (Production ClickHouse)

**Warnings and errors for one run.** Start here.

```sql
SELECT timestamp, level, message
FROM log_entries
WHERE team_id = <team_id>
  AND log_source = 'external_data_jobs'
  AND instance_id = '<workflow_run_id>'
  AND timestamp > now() - INTERVAL 24 HOUR
  AND level IN ('warning', 'error')
ORDER BY timestamp ASC
LIMIT 200
```

**The full line stream for one run**, once you know roughly when it broke. Note the explicit `'UTC'`,
which is what makes a window derived from a Postgres timestamp line up. Validate each
`<YYYY-MM-DD HH:MM:SS>` per the note above before substituting it.

```sql
SELECT timestamp, level, message
FROM log_entries
WHERE team_id = <team_id>
  AND log_source = 'external_data_jobs'
  AND instance_id = '<workflow_run_id>'
  AND timestamp BETWEEN toDateTime('<YYYY-MM-DD HH:MM:SS>', 'UTC')
                    AND toDateTime('<YYYY-MM-DD HH:MM:SS>', 'UTC')
ORDER BY timestamp ASC
LIMIT 500
```

**One table across many runs.** `log_source_id` is the schema id, so this spans every run of that table.

```sql
SELECT instance_id, min(timestamp) AS started, count() AS lines,
       countIf(level = 'error') AS errors,
       countIf(level = 'warning') AS warnings
FROM log_entries
WHERE team_id = <team_id>
  AND log_source = 'external_data_jobs'
  AND log_source_id = '<schema_id>'
  AND timestamp > now() - INTERVAL 3 DAY
GROUP BY instance_id
ORDER BY started DESC
LIMIT 50
```

**Search the message text.** The logger appends `[resource]` and `#batch_index` to warehouse import
messages, so never match with equality. Validate `<fragment>` per the note at the top of this file
before substituting it. This is ClickHouse, not Postgres, so the wildcard-free substring match is
`positionCaseInsensitive`, not the `position(... in ...)` form used above.

```sql
SELECT timestamp, level, instance_id, message
FROM log_entries
WHERE team_id = <team_id>
  AND log_source = 'external_data_jobs'
  AND log_source_id = '<schema_id>'
  AND timestamp > now() - INTERVAL 3 DAY
  AND positionCaseInsensitive(message, '<fragment>') > 0
ORDER BY timestamp DESC
LIMIT 100
```

**CDC fallback.** CDC lines default `log_source_id` to the source id. Try this when a CDC schema returns
nothing by schema id.

```sql
SELECT timestamp, level, log_source_id, message
FROM log_entries
WHERE team_id = <team_id>
  AND log_source = 'external_data_jobs'
  AND log_source_id = '<source_id>'
  AND timestamp > now() - INTERVAL 1 DAY
  AND level IN ('warning', 'error')
ORDER BY timestamp DESC
LIMIT 200
```

**Data modeling views.** Use when the complaint is about a saved view rather than a source table.

```sql
SELECT timestamp, level, instance_id, message
FROM log_entries
WHERE team_id = <team_id>
  AND log_source = 'data_modeling_run'
  AND log_source_id = '<saved_query_id>'
  AND timestamp > now() - INTERVAL 2 DAY
ORDER BY timestamp DESC
LIMIT 200
```

---

## Metrics (Production ClickHouse)

`app_metrics2.instance_id` is the **schema id** here, not the run id.

**Success and failure counts per day for one table.**

```sql
SELECT toDate(timestamp) AS day, metric_kind, metric_name, sum(count) AS total
FROM app_metrics2
WHERE team_id = <team_id>
  AND app_source = 'warehouse_source_sync'
  AND instance_id = '<schema_id>'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY day, metric_kind, metric_name
ORDER BY day DESC
```

**Every table under one source, ranked by failures.** Use to see whether the problem is one table or the
whole source.

```sql
SELECT instance_id AS schema_id,
       sumIf(count, metric_name = 'succeeded') AS succeeded,
       sumIf(count, metric_name = 'failed') AS failed,
       sumIf(count, metric_name = 'billing_limited') AS billing_limited,
       sumIf(count, metric_name = 'rows_synced') AS rows_synced
FROM app_metrics2
WHERE team_id = <team_id>
  AND app_source = 'warehouse_source_sync'
  AND app_source_id = '<source_id>'
  AND timestamp > now() - INTERVAL 14 DAY
GROUP BY schema_id
ORDER BY failed DESC
```

**Billing limits across a team.** A non-zero `billing_limited` count changes the recommendation from a
technical fix to a billing conversation.

```sql
SELECT toDate(timestamp) AS day, sum(count) AS billing_limited
FROM app_metrics2
WHERE team_id = <team_id>
  AND app_source = 'warehouse_source_sync'
  AND metric_name = 'billing_limited'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY day
ORDER BY day DESC
```

---

## Connection discovery

**List the direct-connect connections in the current project.**

```text
external-data-sources-connections-list
```

**List the tables a connection exposes**, with that connection's id set as `connectionId`:

```sql
SELECT table_name FROM system.information_schema.tables
```

**List a table's columns**, same `connectionId`:

```sql
SELECT column_name, data_type
FROM system.information_schema.columns
WHERE table_name = '<table>'
```

Confirmed contents at time of writing:

- Production ClickHouse: `log_entries`, `app_metrics2`, `events`, `person`, `ai_events`.
- Production Postgres: the `public.posthog_*` Django tables, including
  `posthog_externaldatasource`, `posthog_externaldataschema`, `posthog_externaldatajob`,
  `posthog_datawarehousetable`, `posthog_team`, `posthog_organization`, `posthog_user`,
  `posthog_organizationmembership`, `posthog_datamodelingjob`, `posthog_datawarehousesavedquery`.

Re-run the discovery queries rather than trusting that list. It drifts.
