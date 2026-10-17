# Data sources and queries

Run every query in project 2 (US) with the PostHog MCP `execute-sql` tool, unless a section says otherwise.
Replace `<org_id>`, `<account_id>`, `<channel_id>`, and `<domain>` with the values from step 2 of the skill.

## Resolve the organization

`org_universe` holds one row per organization with billing, ownership, enrichment, usage, and link columns.

```sql
SELECT organization_id, organization_name, region, company_domain, billing_plan,
       round(usage_mrr) AS usage_mrr, ca_account_id, sfdc_account_id, sfdc_slack_channel,
       ca_csm_email, ca_account_executive_email
FROM org_universe
WHERE organization_name ILIKE '%<name>%' OR company_domain ILIKE '%<name>%'
ORDER BY usage_mrr DESC
LIMIT 10
```

Then call `accounts-list` with `search` set to the name or domain.
The account `properties` hold `slack_channel_id`, `email_domains`, `sfdc_id`, `zendesk_id`, and `stripe_customer_id`.
The account `notebooks` list holds short ids of account plans and call notes.
`accounts-retrieve` returns the same fields for one account id.

## Company and commercials

```sql
SELECT organization_name, region, billing_plan,
       round(usage_mrr) AS usage_mrr, round(forecasted_usage_mrr) AS forecast_usage_mrr, round(durable_arr) AS durable_arr,
       contract_credit_amount, contract_starts_at, contract_ends_at,
       round(credits_remaining) AS credits_remaining, round(credit_runway_days) AS credit_runway_days,
       ca_csm_email, ca_account_executive_email, ca_tam_email, health_score_v2,
       products_used_30d, engaged_users_30d, member_count,
       sfdc_industry, sfdc_funding_stage, headcount, eng_headcount, sfdc_customer_archetype, last_conversation_at
FROM org_universe
WHERE organization_id = '<org_id>'
```

Spend by product. The JSON columns are nullable, so `ARRAY JOIN` needs `assumeNotNull`:

```sql
SELECT kv.1 AS product, round(kv.2) AS last_invoice_usd,
       round(JSONExtractFloat(assumeNotNull(forecasted_mrr_per_product), kv.1)) AS forecast_usd
FROM org_universe
ARRAY JOIN JSONExtractKeysAndValues(assumeNotNull(invoiced_mrr_m1_per_product), 'Float64') AS kv
WHERE organization_id = '<org_id>'
ORDER BY last_invoice_usd DESC
```

`account_health_scores_v4` (key `org_id`) holds per-product engagement columns `e_<product>` and pipeline counts.
`vitally_accounts` (key `external_id` = org id) holds `next_renewal_date`, `nps_score`, and `traits`.

## Shared Slack channel

Messages live in `slack.<channel id in lowercase>`. The channel list is `slack.$channels`, the user list is `slack.$users`.

```sql
SELECT toDateTime(toFloat(ts)) AS at, m.user AS user_id, u.real_name AS who, thread_ts IS NULL AS top_level,
       ts, substring(toValidUTF8(text), 1, 400) AS text
FROM slack.<channel_id_lowercase> m
LEFT JOIN slack.$users u ON u.id = m.user
WHERE toDateTime(toFloat(ts)) > now() - INTERVAL 60 DAY AND text IS NOT NULL
ORDER BY at DESC
LIMIT 100
```

- Read a whole thread with `WHERE ts = '<ts>' OR thread_ts = '<ts>'`.
- Permalink: `https://posthog.slack.com/archives/<CHANNEL_ID>/p<ts without the dot>`.
- Wrap `text` in `toValidUTF8`, or invalid bytes break the tool.
- Some channels have no table. Check with `system.information_schema.tables`.

## Internal Slack channels

There is no union view. Search a set of channels with `UNION ALL`, and match the brand, the org name, the org id prefix, and the shared channel id:

```sql
SELECT ch, toDateTime(toFloat(ts)) AS at, substring(toValidUTF8(text), 1, 400) AS text,
       concat('https://posthog.slack.com/archives/', ch, '/p', replaceAll(ts, '.', '')) AS link
FROM (
    SELECT 'C01MGUHFH6G' AS ch, ts, text FROM slack.c01mguhfh6g          -- #sales
    UNION ALL SELECT 'C08M011SBCM', ts, text FROM slack.c08m011sbcm      -- #team-customer-success
    UNION ALL SELECT 'C093XHYMGBE', ts, text FROM slack.c093xhymgbe      -- #team-product-led-sales
    UNION ALL SELECT 'C05MUMZLC13', ts, text FROM slack.c05mumzlc13      -- #support-managed-customers
    UNION ALL SELECT 'C096YTKDB7C', ts, text FROM slack.c096ytkdb7c      -- #support-top20
    UNION ALL SELECT 'C053HJDRZSA', ts, text FROM slack.c053hjdrzsa      -- #support-high-priority
    UNION ALL SELECT 'C09HKF565MZ', ts, text FROM slack.c09hkf565mz      -- #customer-churn
    UNION ALL SELECT 'C0959GXHJ92', ts, text FROM slack.c0959gxhj92      -- #feature-request-feed
    UNION ALL SELECT 'C08E93V7LE7', ts, text FROM slack.c08e93v7le7      -- #support-billing
    -- add the focus area channels from focus-areas.md here
)
WHERE toDateTime(toFloat(ts)) > now() - INTERVAL 60 DAY
  AND match(lower(toValidUTF8(text)), '(^|[^a-z])(<brand>|<org name>)([^a-z]|$)|<org id prefix>|<channel id lowercase>')
ORDER BY at DESC
LIMIT 40
```

Some accounts also have a private `#customer-<name>-internal` channel.
Find it with `SELECT id, name FROM slack.$channels WHERE name ILIKE 'customer-%<name>%'`.

## Recorded calls (Gong)

Match calls on participant email domains. Titles and summary text give false matches, because other customers mention the brand.

```sql
SELECT e.id, e.title, e.started, round(e.duration / 60) AS mins, e.url
FROM gong_calls_extensive e
WHERE match(lower(toString(e.parties)), '@(<domain one>|<domain two>)')
ORDER BY e.started DESC
LIMIT 10
```

Read one summary point by point. The JSON keys are `brief`, `outline`, `highlights`, and `keyPoints`:

```sql
SELECT JSONExtractString(assumeNotNull(toString(content)), 'brief') AS brief FROM gong_calls_content WHERE id = '<call id>'

SELECT JSONExtractString(kp, 'text') AS point
FROM gong_calls_content
ARRAY JOIN JSONExtractArrayRaw(assumeNotNull(JSONExtractRaw(assumeNotNull(toString(content)), 'keyPoints'))) AS kp
WHERE id = '<call id>'
```

Full transcripts are in `gong_transcript_chunks`. Watchable link: `https://us-26000.app.gong.io/call?id=<id>`.
Gong writes no summary for calls under 30 seconds.

## Account notes and plans

- Account notebooks: the `notebooks` list on the account. Read titles and text with `system.notebooks` (`short_id`, `title`, `markdown`, `text_content`, `last_modified_at`), or read one with `notebooks-get`.
- Vitally notes: `vitally_notes` filtered on `organization_id = '<org_id>'`. Many duplicate the account notebooks.
- Calendar meetings: `accounts-meetings-list` rejects personal API keys. Read the mirror instead: `postgres_customer_analytics_meeting` (`account_id`, `title`, `start_time`) and `postgres_customer_analytics_meetingparticipant`.
- `business-knowledge-documents-search` returns product docs and internal guides, rarely customer facts. Use it for focus-area background, not for the customer.

## Support tickets and requests

```sql
SELECT ticket_number, created_at, status, priority, channel_source,
       substring(coalesce(email_subject, last_message_text), 1, 160) AS subject
FROM system.support_tickets
WHERE organization_id = '<org_id>' AND created_at > now() - INTERVAL 60 DAY
ORDER BY created_at DESC
```

Also check `system.feature_request_account_links` and `system.customer_tasks` on `account_id = '<account_id>'`.
Zendesk tables are paused and stale.

## Tools connected to PostHog

```sql
WITH teams AS (SELECT id FROM postgres_posthog_team WHERE organization_id = '<org_id>')
SELECT 'warehouse source' AS kind, source_type AS what, toString(count()) AS how_many, toString(min(created_at)) AS first_added
FROM postgres_posthog_externaldatasource WHERE deleted = 0 AND team_id IN (SELECT id FROM teams) GROUP BY source_type
UNION ALL
SELECT 'destination', coalesce(template_id, name), toString(countIf(enabled)), toString(min(created_at))
FROM postgres_posthog_hogfunction WHERE deleted = 0 AND type IN ('destination', 'internal_destination') AND team_id IN (SELECT id FROM teams) GROUP BY coalesce(template_id, name)
UNION ALL
SELECT 'batch export', d.type, toString(countIf(NOT b.paused)), toString(min(b.created_at))
FROM postgres_posthog_batchexport b JOIN postgres_posthog_batchexportdestination d ON d.id = b.destination_id
WHERE b.deleted = 0 AND b.team_id IN (SELECT id FROM teams) GROUP BY d.type
UNION ALL
SELECT 'integration', kind, toString(count()), toString(min(created_at))
FROM postgres_posthog_integration WHERE team_id IN (SELECT id FROM teams) GROUP BY kind
UNION ALL
SELECT 'saved view', if(is_materialized, 'materialized', 'plain'), toString(count()), toString(min(created_at))
FROM postgres_posthog_datawarehousesavedquery WHERE deleted = 0 AND team_id IN (SELECT id FROM teams) GROUP BY is_materialized
```

`postgres_posthog_*` mirrors prod US only.
For an EU org, use `eu_postgres_posthog_team`, `eu_postgres_posthog_batchexport`, and `eu_postgres_posthog_externaldatasource`, and say that destinations and integrations were not checked.
`org_universe.sfdc_tech_tags` and `sfdc_use_cases` add enrichment, but are often empty.

## Agent and MCP usage

```sql
SELECT tool, driver, count() AS calls, uniq(distinct_id) AS people, max(timestamp) AS last_call
FROM v_mcp_tool_calls
WHERE org = '<org_id>' AND timestamp > now() - INTERVAL 60 DAY
GROUP BY tool, driver
ORDER BY calls DESC
LIMIT 30
```

`driver` separates their own agents (`Customer · agent`), Slack-assisted use (`Customer · assisted`), and scouts on their project (`Self-driving`).
Scout rows have `is_customer_driven = 0`, so count only `is_customer_driven = 1` rows as customer adoption.

## Data catalog metrics (Postgres, needs a checkout)

The data catalog tables are not mirrored into project 2. Query prod US Postgres through Metabase:

```sh
echo "SELECT t.id AS team_id, t.name, m.name AS metric, m.status, m.created_source, m.created_at
FROM posthog_team t LEFT JOIN data_catalog_metric m ON m.team_id = t.id AND NOT m.deleted
WHERE t.organization_id = '<org_id>'" | hogli metabase:query --region us --database-id 34
```

Use `--region eu` for an EU org, and check the database id with `hogli metabase:databases --region <region>`.
