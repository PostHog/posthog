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
| **gRPC**                  | The vendor SDK uses gRPC over HTTP/2 (binary, not REST). Routed through the [tracked gRPC transport](common/grpc/) via client interceptors (see `common/grpc/`). |
| **DB protocol**           | Native database wire protocol via a driver (e.g. PostgreSQL, MySQL, Snowflake). Not HTTP.                                                                        |
| **Webhook (S3-buffered)** | Vendor pushes events to a webhook endpoint; payloads are buffered to S3 by the `WebhookSourceManager` and consumed by the pipeline.                              |

When a source uses more than one transport (e.g. BigQuery REST + Storage gRPC, or Stripe pull-API + webhooks),
the row lists both.

## Tracked-transport legend

| State         | Meaning                                                                                                                                 |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| ✅ Tracked    | Outbound calls go through `make_tracked_session()` (or the equivalent vendor-SDK injection).                                            |
| ⚠️ Vendor SDK | Vendor SDK has no session/transport hook we can use. Outbound HTTP bypasses our logging/metrics today. May need a `# nosemgrep` pragma. |
| ➖ N/A        | Source uses a native DB wire protocol (Postgres, MySQL, Snowflake, …) — neither the HTTP nor gRPC transport applies.                    |
| —             | Source is scaffolded; no transport in use yet.                                                                                          |

---

## Implemented sources

| Source           | Comm method                 | Primary library                                                 | Tracked transport           |
| ---------------- | --------------------------- | --------------------------------------------------------------- | --------------------------- |
| aircall          | HTTP                        | requests                                                        | ✅                          |
| amplitude        | HTTP                        | requests                                                        | ✅                          |
| asana            | HTTP                        | requests                                                        | ✅                          |
| ashby            | HTTP                        | requests                                                        | ✅                          |
| attio            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| bamboohr         | HTTP                        | requests                                                        | ✅                          |
| bigquery         | HTTP + gRPC                 | google-cloud-bigquery + bigquery-storage                        | ✅ (HTTP + gRPC)            |
| bing_ads         | HTTP (vendor SDK, SOAP)     | bingads SDK                                                     | ⚠️                          |
| braze            | HTTP                        | requests                                                        | ✅                          |
| brevo            | HTTP                        | requests                                                        | ✅                          |
| buildbetter      | HTTP                        | requests                                                        | ✅                          |
| calendly         | HTTP                        | requests                                                        | ✅                          |
| campaign_monitor | HTTP                        | requests                                                        | ✅                          |
| chargebee        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| confluence       | HTTP                        | requests                                                        | ✅                          |
| chartmogul       | HTTP                        | requests                                                        | ✅                          |
| clerk            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| clickhouse       | DB protocol (HTTP-based)    | clickhouse-connect / clickhouse-driver                          | ➖                          |
| clickup          | HTTP                        | requests                                                        | ✅                          |
| close            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| convertkit       | HTTP                        | requests                                                        | ✅                          |
| convex           | HTTP                        | requests                                                        | ✅                          |
| copper           | HTTP                        | requests                                                        | ✅                          |
| customer_io      | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (App API) / ➖ (webhook) |
| datadog          | HTTP                        | requests                                                        | ✅                          |
| doit             | HTTP                        | requests                                                        | ✅                          |
| drip             | HTTP                        | requests                                                        | ✅                          |
| freshdesk        | HTTP                        | requests                                                        | ✅                          |
| freshsales       | HTTP                        | requests                                                        | ✅                          |
| eventbrite       | HTTP                        | requests                                                        | ✅                          |
| front            | HTTP                        | requests                                                        | ✅                          |
| github           | HTTP                        | requests                                                        | ✅                          |
| gitlab           | HTTP                        | requests                                                        | ✅                          |
| gong             | HTTP                        | requests                                                        | ✅                          |
| google_ads       | gRPC                        | google-ads (googleads.client)                                   | ✅                          |
| google_sheets    | HTTP (vendor SDK)           | gspread                                                         | ✅                          |
| granola          | HTTP                        | requests                                                        | ✅                          |
| gorgias          | HTTP                        | requests                                                        | ✅                          |
| greenhouse       | HTTP                        | requests                                                        | ✅                          |
| hubspot          | HTTP                        | requests                                                        | ✅                          |
| intercom         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| iterable         | HTTP                        | requests                                                        | ✅                          |
| jira             | HTTP                        | requests                                                        | ✅                          |
| klaviyo          | HTTP                        | requests                                                        | ✅                          |
| launchdarkly     | HTTP                        | requests                                                        | ✅                          |
| linear           | HTTP                        | requests                                                        | ✅                          |
| lever            | HTTP                        | requests                                                        | ✅                          |
| linkedin_ads     | HTTP (vendor SDK, RESTli)   | linkedin-api (RestliClient)                                     | ⚠️                          |
| mailchimp        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| mailerlite       | HTTP                        | requests                                                        | ✅                          |
| mailjet          | HTTP                        | requests                                                        | ✅                          |
| meta_ads         | HTTP                        | requests                                                        | ✅                          |
| mixpanel         | HTTP                        | requests                                                        | ✅                          |
| mongodb          | DB protocol                 | pymongo                                                         | ➖                          |
| mssql            | DB protocol                 | pyodbc / pymssql                                                | ➖                          |
| mysql            | DB protocol                 | pymysql                                                         | ➖                          |
| okta             | HTTP                        | requests                                                        | ✅                          |
| notion           | HTTP                        | requests                                                        | ✅                          |
| omnisend         | HTTP                        | requests                                                        | ✅                          |
| paddle           | HTTP                        | requests                                                        | ✅                          |
| pagerduty        | HTTP                        | requests                                                        | ✅                          |
| pendo            | HTTP                        | requests                                                        | ✅                          |
| pinterest_ads    | HTTP                        | requests                                                        | ✅                          |
| pipedrive        | HTTP                        | requests                                                        | ✅                          |
| plain            | HTTP                        | requests                                                        | ✅                          |
| polar            | HTTP                        | requests                                                        | ✅                          |
| postgres         | DB protocol                 | psycopg                                                         | ➖                          |
| postmark         | HTTP                        | requests                                                        | ✅                          |
| productboard     | HTTP                        | requests                                                        | ✅                          |
| recurly          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| recharge         | HTTP                        | requests                                                        | ✅                          |
| reddit_ads       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| redshift         | DB protocol                 | psycopg (Postgres-compatible)                                   | ➖                          |
| resend           | HTTP                        | requests                                                        | ✅                          |
| revenuecat       | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (pull) / ➖ (webhook)    |
| salesforce       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| salesloft        | HTTP                        | requests                                                        | ✅                          |
| sendgrid         | HTTP                        | requests                                                        | ✅                          |
| sentry           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| servicenow       | HTTP                        | requests                                                        | ✅                          |
| shopify          | HTTP                        | requests                                                        | ✅                          |
| shortcut         | HTTP                        | requests                                                        | ✅                          |
| slack            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| smartsheet       | HTTP                        | requests                                                        | ✅                          |
| snapchat_ads     | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| snowflake        | DB protocol                 | snowflake-connector-python                                      | ➖                          |
| square           | HTTP                        | requests                                                        | ✅                          |
| stripe           | HTTP (vendor SDK) + Webhook | stripe (StripeClient + RequestsClient) + `WebhookSourceManager` | ✅ (pull) / ➖ (webhook)    |
| supabase         | DB protocol                 | psycopg (delegates to PostgresSource)                           | ➖                          |
| surveymonkey     | HTTP                        | requests                                                        | ✅                          |
| temporalio       | gRPC (vendor SDK)           | temporalio (`Client`, Rust core via `temporalio.bridge`)        | ⚠️                          |
| tiktok_ads       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| trello           | HTTP                        | requests                                                        | ✅                          |
| twilio           | HTTP                        | requests                                                        | ✅                          |
| typeform         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| vitally          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| webflow          | HTTP                        | requests                                                        | ✅                          |
| woocommerce      | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| workos           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| wrike            | HTTP                        | requests                                                        | ✅                          |
| zendesk          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| zoom             | HTTP                        | requests                                                        | ✅                          |

### Notes on partially-tracked sources

- **bing_ads** uses Microsoft's `bingads` Python SDK, which builds its own HTTP transport via `suds-py3` for
  the SOAP API and a separate Reporting client. The SDK does not expose a session or HTTP-client injection
  hook today. Outbound traffic from this source bypasses the tracked transport.
- **linkedin_ads** uses `linkedin-api`'s `RestliClient`, which constructs its own internal `requests.Session`.
  We don't yet have a session-injection seam on it, so outbound calls bypass the tracked transport. (The file
  imports `requests` only for exception types — those references are expected and don't need a pragma.)
- **temporalio** talks gRPC, but the Python `temporalio` SDK runs its entire gRPC stack in a Rust core
  (`temporalio.bridge`, a PyO3 module) — service RPCs dispatch through `ServiceClient._rpc_call` into the
  bridge, so there is no Python `grpc.Channel` or client-interceptor seam for the tracked gRPC transport to
  wrap. (`Client.connect(interceptors=...)` accepts high-level `temporalio.client.Interceptor`s, a different
  abstraction that wouldn't feed the gRPC observer/metrics.) Outbound traffic bypasses the tracked transport.
- **bigquery** uses two transports: the metadata/management traffic via the BigQuery REST API is HTTP,
  tracked via `AuthorizedSession` + a mounted `TrackedHTTPAdapter`; the Storage Read API uses gRPC,
  tracked via `BigQueryReadGrpcTransport(channel=make_tracked_channel(...))` so `create_read_session` and
  `read_rows` ride the tracked gRPC interceptors.
- **google_ads** is pure gRPC. Every `GoogleAdsClient.get_service(...)` call passes
  `interceptors=tracked_interceptors(host)` so its unary calls (`search`, `search_google_ads_fields`) are
  logged, metered, and eligible for sample capture.

---

## Scaffolded sources

These are registered in `__init__.py` with `unreleasedSource=True` and a stub `source.py`. They have no
sync logic yet — picking up any of them means following the [implementing-warehouse-sources skill](/.agents/skills/implementing-warehouse-sources/SKILL.md).

One source per line (kept alphabetical) so adding or removing a source only touches its own line and
doesn't conflict with concurrent PRs.

- active_campaign
- adjust
- adobe_analytics
- adobe_commerce
- adp_workforce_now
- adroll
- adyen
- airtable
- amazon_ads
- amazon_s3
- amazon_selling_partner
- apollo
- apple_search_ads
- appsflyer
- attentive
- auth0
- azure_blob
- azure_devops
- bigcommerce
- box
- braintree
- branch
- brex
- campaign_manager_360
- checkout_com
- chorus
- circleci
- clari
- cloudflare
- cockroachdb
- coda
- commercetools
- constant_contact
- copper
- cosmosdb
- coupa
- criteo
- crunchbase
- culture_amp
- databricks
- db2
- deel
- delighted
- display_video_360
- dixa
- docusign
- dropbox
- dynamics365
- dynamodb
- ebay
- elasticsearch
- eloqua
- expensify
- facebook_pages
- firebase
- freshbooks
- fullstory
- gladly
- gocardless
- google_ad_manager
- google_analytics
- google_cloud_storage
- google_drive
- guru
- gusto
- heap
- helpscout
- hibob
- incident_io
- instagram
- kafka
- kustomer
- lattice
- lever
- lightspeed_retail
- mailgun
- marketo
- matomo
- microsoft_teams
- mollie
- monday
- netsuite
- onedrive
- opsgenie
- optimizely
- oracle
- oracle_ebs
- oracle_fusion
- ortto
- outbrain
- outreach
- pagerduty
- pandadoc
- pardot
- paylocity
- paypal
- pendo
- personio
- pingdom
- plaid
- planetscale
- qualtrics
- quickbooks
- ramp
- ringcentral
- rippling
- rollbar
- sage_intacct
- sailthru
- salesforce_marketing_cloud
- sap_concur
- sap_erp
- sap_hana
- sap_successfactors
- search_ads_360
- sftp
- sharepoint
- shipstation
- surveymonkey
- taboola
- twitter_ads
- workday
- xero
- youtube_analytics
- zoho_crm
- zoominfo
- zuora

---

## When to update this file

Update SOURCES.md whenever you:

- **Add a new source** (move it from the scaffolded list into the implemented table once it actually syncs).
- **Implement an existing scaffolded source** (move it into the implemented table; record the comm method
  and tracked-transport state).
- **Migrate a vendor SDK** to use `make_tracked_session()` (flip the source from ⚠️ to ✅).
- **Switch a source's protocol** (e.g. swap a REST client for a gRPC SDK, or add webhook support
  alongside the pull API).

Two semgrep rules enforce the tracked transports inside `sources/`:

- [`data-imports-http-transport`](/.semgrep/rules/data-imports-http-transport.yaml) bans direct
  `requests.<verb>` / `requests.Session()` / `httpx.*` — route through `make_tracked_session()`.
- [`data-imports-grpc-transport`](/.semgrep/rules/data-imports-grpc-transport.yaml) bans raw
  `grpc.*_channel(...)` and direct `BigQueryReadClient(...)` / `GoogleAdsClient(...)` construction —
  route through `make_tracked_channel(...)` (for `channel=`/`transport=` SDKs) or
  `tracked_interceptors(host)` (for `interceptors=` SDKs).

Vendor SDKs that genuinely cannot be intercepted should both:

1. Carry a `# nosemgrep: data-imports-...-transport-...` pragma at the call site, with a one-line reason.
2. Be listed here under "Notes on partially-tracked sources" with the `⚠️ Vendor SDK` row state.
