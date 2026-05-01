# Warehouse sources — implementation status & communication methods

This file is the authoritative inventory of every source registered in [`posthog/temporal/data_imports/sources/__init__.py`](__init__.py),
the wire protocol it uses to talk to its upstream, and whether its outbound traffic is currently routed
through the [tracked HTTP transport](common/http/) (so it shows up in our HTTP logs, metrics, and
sample-capture pipeline).

Keep this file in sync as sources are added, implemented, or migrated. The [implementing-warehouse-sources
skill](/.agents/skills/implementing-warehouse-sources/SKILL.md) instructs agents to update it as part of any
new source / vendor-SDK / migration PR.

## Status legend

| Status          | Meaning                                                                                                                   |
| --------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **Implemented** | Source has working sync logic and is exposed to users (possibly behind `featureFlag=` or `releaseStatus="alpha"/"beta"`). |
| **Scaffolded**  | Source class is registered with `unreleasedSource=True` and an empty/placeholder `source.py`. No sync logic yet.          |

## Comm-method legend

| Method                    | Meaning                                                                                                                                                          |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **HTTP**                  | REST/JSON over HTTPS via the `requests` library. Routed through `make_tracked_session()` (see [common/http/](common/http/)).                                     |
| **HTTP (vendor SDK)**     | The vendor ships its own SDK that wraps HTTP. Where the SDK exposes a session/transport hook, we inject `make_tracked_session()` so the calls are still tracked. |
| **gRPC**                  | The vendor SDK uses gRPC over HTTP/2 (binary, not REST). The tracked HTTP transport does not currently apply.                                                    |
| **DB protocol**           | Native database wire protocol via a driver (e.g. PostgreSQL, MySQL, Snowflake). Not HTTP.                                                                        |
| **Webhook (S3-buffered)** | Vendor pushes events to a webhook endpoint; payloads are buffered to S3 by the `WebhookSourceManager` and consumed by the pipeline.                              |

When a source uses more than one transport (e.g. BigQuery REST + Storage gRPC, or Stripe pull-API + webhooks),
the row lists both.

## Tracked-transport legend

| State         | Meaning                                                                                                                                 |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| ✅ Tracked    | Outbound calls go through `make_tracked_session()` (or the equivalent vendor-SDK injection).                                            |
| ⚠️ Vendor SDK | Vendor SDK has no session/transport hook we can use. Outbound HTTP bypasses our logging/metrics today. May need a `# nosemgrep` pragma. |
| ➖ N/A        | Source uses a non-HTTP protocol (DB driver, gRPC, etc.) — the HTTP transport doesn't apply.                                             |
| —             | Source is scaffolded; no transport in use yet.                                                                                          |

---

## Implemented sources

| Source        | Comm method                 | Primary library                                                 | Tracked transport           |
| ------------- | --------------------------- | --------------------------------------------------------------- | --------------------------- |
| attio         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| bigquery      | HTTP + gRPC                 | google-cloud-bigquery + bigquery-storage                        | ✅ (HTTP), ➖ (gRPC)        |
| bing_ads      | HTTP (vendor SDK, SOAP)     | bingads SDK                                                     | ⚠️                          |
| buildbetter   | HTTP                        | requests                                                        | ✅                          |
| chargebee     | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| clerk         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| clickhouse    | DB protocol (HTTP-based)    | clickhouse-connect / clickhouse-driver                          | ➖                          |
| convex        | HTTP                        | requests                                                        | ✅                          |
| customer_io   | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (App API) / ➖ (webhook) |
| doit          | HTTP                        | requests                                                        | ✅                          |
| github        | HTTP                        | requests                                                        | ✅                          |
| google_ads    | gRPC                        | google-ads (googleads.client)                                   | ➖                          |
| google_sheets | HTTP (vendor SDK)           | gspread                                                         | ✅                          |
| hubspot       | HTTP                        | requests                                                        | ✅                          |
| klaviyo       | HTTP                        | requests                                                        | ✅                          |
| linear        | HTTP                        | requests                                                        | ✅                          |
| linkedin_ads  | HTTP (vendor SDK, RESTli)   | linkedin-api (RestliClient)                                     | ⚠️                          |
| mailchimp     | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| meta_ads      | HTTP                        | requests                                                        | ✅                          |
| mongodb       | DB protocol                 | pymongo                                                         | ➖                          |
| mssql         | DB protocol                 | pyodbc / pymssql                                                | ➖                          |
| mysql         | DB protocol                 | pymysql                                                         | ➖                          |
| paddle        | HTTP                        | requests                                                        | ✅                          |
| pinterest_ads | HTTP                        | requests                                                        | ✅                          |
| plain         | HTTP                        | requests                                                        | ✅                          |
| postgres      | DB protocol                 | psycopg                                                         | ➖                          |
| reddit_ads    | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| redshift      | DB protocol                 | psycopg (Postgres-compatible)                                   | ➖                          |
| resend        | HTTP                        | requests                                                        | ✅                          |
| salesforce    | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| sentry        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| shopify       | HTTP                        | requests                                                        | ✅                          |
| slack         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| snapchat_ads  | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| snowflake     | DB protocol                 | snowflake-connector-python                                      | ➖                          |
| stripe        | HTTP (vendor SDK) + Webhook | stripe (StripeClient + RequestsClient) + `WebhookSourceManager` | ✅ (pull) / ➖ (webhook)    |
| supabase      | DB protocol                 | psycopg (delegates to PostgresSource)                           | ➖                          |
| tiktok_ads    | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| typeform      | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| vitally       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| zendesk       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |

### Notes on partially-tracked sources

- **bing_ads** uses Microsoft's `bingads` Python SDK, which builds its own HTTP transport via `suds-py3` for
  the SOAP API and a separate Reporting client. The SDK does not expose a session or HTTP-client injection
  hook today. Outbound traffic from this source bypasses the tracked transport.
- **linkedin_ads** uses `linkedin-api`'s `RestliClient`, which constructs its own internal `requests.Session`.
  We don't yet have a session-injection seam on it, so outbound calls bypass the tracked transport. (The file
  imports `requests` only for exception types — those references are expected and don't need a pragma.)
- **bigquery's** Storage Read API uses gRPC; only the metadata/management traffic via the BigQuery REST API
  is HTTP, and that HTTP path is tracked via `AuthorizedSession` + a mounted `TrackedHTTPAdapter`.

---

## Scaffolded sources

These are registered in `__init__.py` with `unreleasedSource=True` and a stub `source.py`. They have no
sync logic yet — picking up any of them means following the [implementing-warehouse-sources skill](/.agents/skills/implementing-warehouse-sources/SKILL.md).

active_campaign, adjust, aircall, airtable, amazon_ads, amplitude, apple_search_ads, appsflyer, asana,
ashby, auth0, azure_blob, bamboohr, bigcommerce, box, braintree, braze, brevo, calendly, campaign_monitor,
chartmogul, circleci, clickup, close, cockroachdb, confluence, convertkit, copper, datadog,
drip, dynamodb, elasticsearch, eventbrite, facebook_pages, firebase, freshdesk, freshsales, front,
fullstory, gitlab, gong, google_analytics, google_drive, gorgias, granola, greenhouse, helpscout,
instagram, intercom, iterable, jira, kafka, launchdarkly, lever, mailerlite, mailjet, marketo,
microsoft_teams, mixpanel, monday, netsuite, notion, okta, omnisend, onedrive, oracle, outreach,
pagerduty, pardot, paypal, pendo, pipedrive, plaid, polar, postmark, productboard, quickbooks, recharge,
recurly, revenuecat, ringcentral, salesloft, sendgrid, servicenow, sftp, sharepoint, shortcut, smartsheet,
square, surveymonkey, temporalio, trello, twilio, twitter_ads, webflow, woocommerce, workday, wrike, xero,
youtube_analytics, zoho_crm, zoom, zuora.

---

## When to update this file

Update SOURCES.md whenever you:

- **Add a new source** (move it from the scaffolded list into the implemented table once it actually syncs).
- **Implement an existing scaffolded source** (move it into the implemented table; record the comm method
  and tracked-transport state).
- **Migrate a vendor SDK** to use `make_tracked_session()` (flip the source from ⚠️ to ✅).
- **Switch a source's protocol** (e.g. swap a REST client for a gRPC SDK, or add webhook support
  alongside the pull API).

The semgrep rule [`data-imports-http-transport`](/.semgrep/rules/data-imports-http-transport.yaml) enforces
that direct `requests.<verb>` / `requests.Session()` / `httpx.*` calls inside `sources/` go through the
tracked transport. Vendor SDKs that genuinely cannot be intercepted should both:

1. Carry a `# nosemgrep: data-imports-http-transport-...` pragma at the call site, with a one-line reason.
2. Be listed here under "Notes on partially-tracked sources" with the `⚠️ Vendor SDK` row state.
