# Ticket queries

All queries run through the PostHog MCP `execute-sql` tool in the internal project (US, project 2).
Always confirm table columns via `system.information_schema.columns` before querying a `system.*` table.

## Open web analytics tickets from the conversations product

```sql
SELECT ticket_number, id, status, priority, channel_source,
       substring(last_message_text, 1, 400) AS last_msg, created_at, message_count
FROM system.support_tickets
WHERE status IN ('new', 'open', 'pending')
  AND created_at >= now() - INTERVAL 21 DAY
  AND (last_message_text ILIKE '%web analytics%'
       OR last_message_text ILIKE '%bounce%'
       OR last_message_text ILIKE '%utm%'
       OR last_message_text ILIKE '%pageview%'
       OR email_subject ILIKE '%web analytics%')
ORDER BY created_at DESC
```

Caveats: `last_message_text` is only the latest message and may be truncated; `message_count > 1` means there is history you have not seen.
The keyword filter misses tickets phrased differently — also read the `#support-web-analytics` Slack channel for the Zendesk-mirrored stream.

## Full comment history via the Zendesk warehouse mirror

`system.support_tickets` has no messages table. The Zendesk mirror does, inside a JSON array column:

```sql
SELECT created_at, body FROM (
    SELECT created_at,
           JSONExtractString(
               arrayJoin(JSONExtractArrayRaw(assumeNotNull(toString(child_events)))),
               'body') AS body
    FROM zendesk.ticket_events
    WHERE ticket_id = {zendesk_ticket_id}
) WHERE body != ''
ORDER BY created_at ASC
```

Notes: `assumeNotNull` is required (arrayJoin cannot sit inside Nullable); apply `LIMIT` after the subquery or arrayJoin eats it; MCP display truncates long cells, so extract fields instead of dumping raw JSON.

## Resolve a requester to an org/team (US and EU)

```sql
SELECT 'us' AS region, u.email, u.current_team_id
FROM postgres.posthog_user u WHERE u.email = '{email}'
UNION ALL
SELECT 'eu', u.email, u.current_team_id
FROM eu_postgres_posthog_user u WHERE u.email = '{email}'
```

Also useful: `postgres.posthog_organizationdomain` (verified domains only — often empty for smaller orgs), `postgres.posthog_organization` by name, `all_posthog_team`.

EU customer data is not queryable from the US MCP project.
For per-team event data on either region, use the `query-clickhouse-via-metabase` skill.

## Error tracking cross-reference

Frontend crashes reported by EU customers usually have US occurrences too (PostHog staff and US users hit the same code).
Search the internal project's error tracking with the MCP tools; `source` on the issue row names the sourcemapped file, and `verbosity: stack` on events gives resolved frame names, so you can go from a minified customer stack to `file:line` without a local repro.
