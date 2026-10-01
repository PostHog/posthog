---
title: Working with data warehouse
sidebar: Docs
showTitle: true
---

This is an internal guide to setting up and working with the data warehouse for PostHog engineers. If you're a PostHog user, check out our [data warehouse docs](https://posthog.com/docs/data-warehouse) instead.

## Apple Ads in Marketing analytics

Marketing analytics support is controlled by the boolean organization flag `marketing-analytics-apple-ads` and is off by default.
Enable the flag for an organization to show the integration and include its data in live and precomputed marketing queries.
Disable it to stop using the integration in Marketing analytics without deleting the connection or its imported data.
Data warehouse syncs continue independently of this flag.

Sync `campaigns` and `campaign_report` to include Apple Ads in Marketing analytics.
Sync `ad_groups` and `ad_group_report` to enable the ad group breakdown.
Apple Ads does not provide an ad-level report through this connector.
Taps appear as clicks, and installs appear as reported conversions.
The adapter accepts both Campaign Management API 5 `installs` and Ads Platform API `totalInstalls`, including tables that contain rows from both versions.
Spend uses the currency in Apple's `localSpend` object and the reporting date to convert into the project's currency.
Apple does not report conversion revenue through these reports, so reported conversion value is zero.

## OpenAI Ads in Marketing analytics

Marketing analytics support is controlled by the boolean organization flag `marketing-analytics-openai-ads` and is off by default.
Enable the flag for an organization to show the integration and include its data in live and precomputed marketing queries.
Disable it to stop using the integration in Marketing analytics without deleting the connection or its imported data.
Data warehouse syncs continue independently of this flag.

Sync `campaigns` and `campaign_insights` to include OpenAI Ads campaign delivery in Marketing analytics.
Spend is already in major currency units; the importer adds `currency_code` from the account metadata so reports can convert spend at each bucket date.
Existing connections need a full resync of `campaign_insights` to populate currency on historical rows.
Without the currency column, cost tiles are unavailable and the campaign table excludes the source.
The dashboard and source settings show a warning with a link to the affected warehouse source and instructions to fully resync `campaign_insights`.
Queries with empty historical currency values stop with a resync message.
Reported conversions and revenue are zero because the importer currently requests delivery metrics only.
Ad groups and individual ads are not included in the native integration.

## Source warnings in Marketing analytics

The dashboard and source settings show validation errors for connected native and mapped external sources.
They use the same adapter validators as campaign queries, so warnings follow each integration's supported checks without a separate frontend list of required columns.
Warnings identify the affected connection and link to its settings.
Mapped sources with missing required column mappings remain visible in these warnings until corrected.
The dashboard also shows missing or disabled required tables and running, failed, paused, or cancelled syncs.
Reload the dashboard after correcting the configuration or resyncing a table to refresh validation.
This check uses table metadata and configuration; it does not scan imported rows for data quality issues.
Query execution errors still appear on the affected dashboard tile or table.

## Amazon Ads in Marketing analytics

Marketing analytics support is controlled by the boolean organization flag `marketing-analytics-amazon-ads` and is off by default.
Enable the flag for an organization to show the integration and include its data in live and precomputed marketing queries.
Disable it to stop using the integration in Marketing analytics without deleting the connection or its imported data.
Data warehouse syncs continue independently of this flag.

Sync `sp_campaigns` and `sp_campaign_reports` to include Sponsored Products campaigns in Marketing analytics.
Spend uses `cost`, with currency conversion at each report date using `campaign_budget_currency_code`.
Reported conversions and revenue use the 14-day purchase and sales metrics; the other attribution windows are not added to these totals.
Sponsored Brands, Sponsored Display, ad groups, and individual ads are not included because the importer does not provide their performance reports.

Monetary tiles require the report date and currency columns; reports without currency can still supply impressions and clicks.

## Rokt Ads in Marketing analytics

Marketing analytics support is controlled by the boolean organization flag `marketing-analytics-rokt-ads` and is off by default.
Enable the flag for an organization to show the integration and include its data in live and precomputed marketing queries.
Disable it to stop using the integration in Marketing analytics without deleting the connection or its imported data.
Data warehouse syncs continue independently of this flag.

Sync `CampaignPerformance` to include Rokt Ads in Marketing analytics.
The report provides campaign identity and daily metrics in one table, so the integration aggregates it without joining the report to itself.
Spend uses `gross_cost`, clicks use `referrals`, and reported conversions and revenue use `conversions` and `conversion_value`.
Missing optional conversion metrics show zero.
The importer stores the requested cost currency on each row, defaulting to USD.
Rokt reports `conversion_value` in USD regardless of the requested cost currency.
Marketing analytics converts spend from the stored cost currency and conversion value from USD at each report date.
Changing the source currency affects newly synced rows; historical rows retain their own currency.
Existing connections need a full resync of `CampaignPerformance` to backfill currency before using monetary metrics.
Missing currency columns prevent monetary tiles, and empty historical currency values stop queries with a resync message.
Creative, audience, demographic, and publisher reports are excluded to avoid counting overlapping breakdowns twice.

## Adding a new source

Looking to add a new source to data warehouse? [We have a detailed guide in the codebase](https://github.com/PostHog/posthog/blob/master/products/warehouse_sources/backend/temporal/data_imports/sources/README.md).

> If you're a customer of PostHog Cloud and are looking to import data into your project, then you're likely looking for [this section of the docs instead](https://posthog.com/docs/cdp/sources)

Selecting a source in the `Advertising` category records Marketing analytics product intent as well as Data warehouse intent.
This happens when the user selects the connector, before credentials are validated or data syncs.
The category covers new advertising connectors automatically; it does not mean Marketing analytics supports their data natively.
Selecting a source outside this category, such as BigQuery, records only Data warehouse intent.
Supported self-managed providers keep their separate Marketing analytics intent tracking.

## Marketing source suggestions

Marketing analytics suggests connecting an ad platform only when a matching `utm_source` has events with paid attribution signals.
A source match, referral, fuzzy alias, or `utm_campaign` alone does not establish paid traffic.
For example, [ChatGPT adds `utm_source=chatgpt.com` to referral links](https://help.openai.com/en/articles/12627856-publishers-and-developers-faq), and [campaign tags also describe non-ad marketing](https://support.google.com/analytics/answer/10917952).

An explicit paid medium (`cpc`, `cpm`, `cpv`, `cpa`, `ppc`, `retargeting`, or a `paid` prefix) qualifies for any matched platform.
The following platform-specific signals also qualify, in event properties or the query string of the same event's `$current_url`:

| Platform              | Additional paid signal                                                                                                                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Google Ads            | [`gclid`, `gbraid`, `wbraid`](https://developers.google.com/google-ads/api/docs/conversions/legacy_oci_guide), [`gad_source`, `gad_campaignid`](https://support.google.com/google-ads/answer/16193746) |
| OpenAI Ads            | [`oppref`](https://developers.openai.com/ads/conversion-tracking)                                                                                                                                      |
| Microsoft Advertising | [`msclkid`](https://learn.microsoft.com/en-us/advertising/guides/uet-conversion-api-integration?view=bingads-13)                                                                                       |
| LinkedIn Ads          | [`li_fat_id`](https://learn.microsoft.com/en-us/linkedin/marketing/conversions/enabling-first-party-cookies?view=li-lms-2026-03)                                                                       |
| Reddit Ads            | [`rdt_cid`](https://ads-api.reddit.com/docs/v3/capi-click-id-persistence)                                                                                                                              |
| Snapchat Ads          | [`ScCid`](https://developers.snap.com/marketing-api/Conversions-API/UsingTheAPI#sending-click-id) or `sccid`, not the `_scid` cookie                                                                   |
| TikTok Ads            | [`ttclid`](https://ads.tiktok.com/resources/help/article/tiktok-click-id?lang=en)                                                                                                                      |
| Rokt Ads              | [`rtid`](https://docs.rokt.com/developers/integration-guides/web/advanced/rokt-id-tag/)                                                                                                                |
| Pinterest Ads         | [`pp=0`](https://help.pinterest.com/en/business/article/the-pp-query-string-parameter); `pp=1` excludes earned clicks even when paid campaign tags remain                                              |

Meta, Amazon, and Apple rely on an explicit paid medium in this detector.
`fbclid` and `epik` alone do not qualify.
Apple app attribution requires [AdServices attribution records](https://developer.apple.com/documentation/AdServices/AAAttribution/attributionToken%28%29); an App Store campaign link does not establish an Apple Ads interaction.

Each event counts at most once for its matched platform, even if it has both a paid medium and an ad identifier.
Custom source mappings select which platform's signals apply; another platform's identifier cannot make that source paid.
This check retains the UTM source catalogue's time window and top-500 limit, so it does not discover untagged sources or verify billable clicks.
Missing signals mean insufficient evidence to recommend a connection, not proof that traffic is organic.
The medium count describes only matched events in the lookback window; zero can also mean no events matched that integration.
This changes setup recommendations and diagnostic actions, not report attribution or connected-source sync checks.

## Importing your local Postgres instance

1. Head to the [new source flow](http://localhost:8010/project/pipeline/new/source) in your local app, hit the link button next to Postgres
2. Use the following settings:
   1. host = 127.0.0.1
   2. port = 5432
   3. database = posthog
   4. user = posthog
   5. password = posthog
   6. schema = public
3. Hit next, then select which tables you'd like to import. [More info on the sync types can be found here](https://posthog.com/docs/cdp/sources#incremental-vs-append-only-vs-full-table). For the Postgres-specific `xmin` (cursorless incremental) sync type and its limitations, see the [Postgres source README](https://github.com/PostHog/posthog/blob/master/products/warehouse_sources/backend/temporal/data_imports/sources/postgres/README.md)
4. Hit next and finish the import - `temporal-worker-data-warehouse` will then import the data into your local object storage

## Accessing object storage

All your data warehouse data is stored in your local object storage (SeaweedFS, S3-compatible, running at `http://localhost:19000`). Unlike MinIO, SeaweedFS has no web console, so inspect it with any S3 client. For example, with the AWS CLI:

```bash
AWS_ACCESS_KEY_ID=object_storage_root_user AWS_SECRET_ACCESS_KEY=object_storage_root_password \
  aws --endpoint-url http://localhost:19000 s3 ls s3://data-warehouse/ --recursive
```

There's a separate folder under the `data-warehouse` bucket for each table you sync.

## Setting up a MySQL source

If you want to set up a local MySQL database as a source for the data warehouse, there are a few extra set up steps you'll need to complete:

First, install MySQL:

```bash
brew install mysql
brew services start mysql
```

Once MySQL is installed, create a database and table, insert a row, and create a user who can connect to it:

```bash
mysql -u root
```

```sql runInPostHog=false
CREATE DATABASE posthog_dw_test;
CREATE TABLE IF NOT EXISTS payments (id INT AUTO_INCREMENT PRIMARY KEY, timestamp DATETIME, distinct_id VARCHAR(255), amount DECIMAL(10,2));

INSERT INTO payments (timestamp, distinct_id, amount) VALUES (NOW(), 'testuser@example.com', 99.99);

CREATE USER 'posthog'@'%' IDENTIFIED BY 'posthog';
GRANT ALL PRIVILEGES ON posthog_dw_test.* TO 'posthog'@'%';
FLUSH PRIVILEGES;
```

To verify everything is working as expected:

1. Navigate to "Data pipeline" in the PostHog application.
2. Create a new MySQL source using the settings above (username and password both being `posthog`)
3. Once the source is created, click on the "MySQL" item. In the schemas table, click on the triple dot menu and select the "Reload" option.

After the job runs, clicking on the synced table name should take you to your data.

## Working with a MS SQL source

You'll need to install MS SQL drivers for the PostHog app to connect to a MS SQL database. Learn the entire process in [posthog/warehouse/README.md](https://github.com/PostHog/posthog/blob/master/posthog/warehouse/README.md). Without the drivers, you'll get the following error when connecting a SQL database to data warehouse:

```text
symbol not found in flat namespace '_bcp_batch'
```
