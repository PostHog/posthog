---
title: Working with data warehouse
sidebar: Docs
showTitle: true
---

This is an internal guide to setting up and working with the data warehouse for PostHog engineers. If you're a PostHog user, check out our [data warehouse docs](https://posthog.com/docs/data-warehouse) instead.

## Model namespace reservation

The shared PostHog catalog reserves `models.*` for authored data models. New warehouse tables, endpoint saved queries, and managed viewsets cannot claim that namespace. The bare name `models` is reserved for the namespace container; use a name such as `models.revenue` for a model. Names such as `models_v2` remain available. Saved queries with no origin are treated as authored models for compatibility.

Existing reserved-name rows remain queryable, editable, and deletable. Model validation enforces the reservation on creation and renaming, during saves and `full_clean()`. Authored models can use private materialization backing tables with their model names.

Direct-connection catalogs contain no authored models and are exempt from the reservation. Upstream tables and schemas named `models` remain available there, including case variants resolved by Snowflake and Trino.

This reservation does not add qualified names to existing models or require a namespace on new models.

## SQL editor drafts

The SQL editor keeps unrun edits in browser storage, scoped to the user, project, and saved query. Explicit logout clears these drafts.
An **Edited** label marks changes to a saved view or insight. **Discard changes** restores the saved copy already loaded in memory, then refreshes it from the server. The refresh preserves edits made after discarding.
Insights can be saved or updated before running the SQL. Updating a view still requires a successful run of the current SQL so its result types match the saved query. **Continue in a notebook** is in the update button's dropdown for saved views and insights.

## Choosing data in Business intelligence

**Business intelligence** lists saved worksheets at `/bi` when the `sql-editor-bi-mode` feature flag is enabled. Search all worksheets or switch to those viewed in the last 30 days. **New worksheet** opens `/bi/new`; selecting a saved worksheet opens `/bi/<short_id>` in edit mode. The project tree's **New → Worksheet** entry opens the same editor. Worksheets retain their insight identities and folder placements, but use their own file subtype and no longer appear in the Product analytics insights list. Legacy `/bi?open_insight=...` links and shared worksheet URLs still open the editor. Business intelligence and SQL keep separate unsaved working copies, and existing SQL editor links with `mode=bi` open in Business intelligence.

Choose a connection in the **Data** panel, then select a table below it. **Run** is the first toolbar action, before **Swap rows and columns**.

**Auto update** is off by default and remembers your choice. Selecting a table alone can run a count when you click **Run**. In wide worksheets, drag the divider between the data and analysis panels to resize the data panel, or drag the analysis panel's right edge to resize that panel independently.

BI usage keeps the existing `sql-editor-bi-mode-selected`, `sql-editor-bi-query-run`, and `sql-editor-bi-query-saved` events. Their properties describe table calculations, Top N, comparisons, formatting, axes, totals, and related/property field counts. The `bi-worksheet-action` event's `action` property defines the funnel: `opened`, `source_selected`, `first_chart`, `saved`, `added_to_dashboard`. The first chart is the first nonempty successful result per editor visit; reruns and failures do not count again. Saved and dashboard steps include `insight_id`. Additional actions record drill-down choices, related-table expansion, and property browsing/search. These events exclude SQL, source names, field names, formulas, search text, filter values, and result contents.

**Undo** and **Redo** restore shelves, filters, calculations, formatting, chart settings, and worksheet names. The editor keeps the last 100 changes during a visit; opening another worksheet or discarding changes starts a new history. Use Cmd/Ctrl+Z and Cmd/Ctrl+Shift+Z outside text inputs. Undo respects **Auto update**: with it off, click **Run** to refresh results. **Save a copy** creates a separate worksheet and opens it in the editor without changing the original or copying its dashboard placements. Copy failures leave the original and your edits in place. Usage tracking adds `undo`, `redo`, and `copied` actions.

For older saves without worksheet configuration, discarding query edits preserves the current source and shelves.

SQL query-scan advisories are hidden in Business intelligence. Query errors and warnings about stale sources or restricted data remain visible.

Saving a worksheet preserves its connection, table, shelves, measures, filters, chart type, limit, sort order, and visualization settings in a `BIVisualizationNode`. The wrapper contains the worksheet configuration and a plain `HogQLQuery` source. Saving keeps the worksheet in the BI editor; dashboard tiles can still use the normal insight view. **Edit** reopens Business intelligence when the feature is enabled, including from a dashboard. Leaving a worksheet with unsaved edits asks for confirmation, including when returning to **Worksheets**. **Discard changes** restores the saved worksheet. **Save as SQL view** exports only the generated SQL to a warehouse view; save a worksheet to retain editable worksheet state.

Older saves containing only SQL still open in the SQL editor. Their original shelves cannot be reconstructed without the worksheet configuration from a draft or shared URL.

The worksheet date picker supports rolling windows, fixed ranges, this/last month and quarter, and year to date. **Date** selects the column that receives dashboard date ranges; **No date column** explicitly opts out. A dashboard range replaces the worksheet range. Dashboard property filters combine with worksheet conditions. Event-based tables retain standard PostHog property filtering with any date-column selection, using `{filters.native(date_expression)}` or `{filters.native(null)}` when overriding the default date column. Other tables bind dashboard property keys to worksheet fields, including the property key in a field such as `properties.plan`. Unmapped or ambiguous property keys produce a query error instead of silently applying the wrong filter. Reopen and save older BI worksheets to update their generated SQL with dashboard-aware placeholders.

The comparison picker adds the previous period or a custom offset, including one year earlier. Tables, bar, line, and area charts support comparisons with up to two dimensions. Previous-period dates align to the current axis, and the legend identifies each period. Both periods use the effective dashboard date range and property filters. Comparisons require a bounded range and turn off when the worksheet switches to all time or an unsupported chart.

Generated comparison queries use `{filters.previous}` (or its column-bound form) for the comparison range and `{filters.compareDate(expr)}` to align date dimensions. Custom native date columns use `{filters.previous.native(expr)}`. Month, quarter, and year dimensions pass their bucket as a second argument to `compareDate`, so month lengths and leap years do not move points into the wrong bucket. `HogQLFilters.compareFilter` supplies the comparison offset; missing offsets use the previous period.

Use the table picker in the data pane to browse PostHog, warehouse, view, and system tables, with direct-connection tables grouped by schema.
The selected table is highlighted; expanding a folder does not select it.
Direct connections group tables by schema. Search matches table and folder names without changing the sidebar search.

**Related tables** exposes existing lazy joins, virtual tables, and configured warehouse joins as expandable nodes. Fields reached through a relation keep the original source and a qualified path, so adding a customer's field to a charges worksheet does not switch tables. PostHog property fields, including `person.properties` under events, expand into searchable, paginated property definitions. Numeric definitions become measures; other definitions become dimensions. Restricted and hidden properties are excluded. Warehouse relationships use the existing join configuration; the worksheet does not create joins or infer arbitrary JSON keys.

**Search fields** also searches property definitions in the selected table and expanded related tables. Search for `$browser`, `$pathname`, or a custom property name to open matching property groups, then drag or double-click a property onto a shelf. Clearing the search restores each group's previous expansion and local search. Searching for a group's name, such as `properties`, shows all its definitions.

## Calculated measures in BI mode

The **Marks** card offers table calculations per measure: percent of total, running total, difference or percent change from the preceding point, trailing moving average, and rank. **Compute using** selects the dimension to traverse, with the date dimension chosen by default; other dimensions partition the calculation. Moving averages count returned points, including the current point. Missing date buckets are not filled. Calculations run before the result limit, and zero denominators produce empty cells.

The **Analysis** card ranks **Top N** categories by a selected measure across the full current date range. **Include "Other"** combines the remaining source rows and re-aggregates them, including averages and distinct counts. Removing the ranking measure turns Top N off. Previous-period comparisons use the current period's category selection. Tables offer a grand total; pivot tables offer row and column grand totals. Both support hierarchy subtotals when an axis has multiple dimensions. Totals re-aggregate source rows; table-calculation cells remain blank on total rows. Summary rows can occupy at most half the result limit, reserving room for detail cells. The BI visualization requests an extra row to determine whether more results exist, then removes it before building tables and charts. Saved SQL and exports retain the worksheet's configured limit. A notice appears only when the response confirms more results beyond that limit, which also applies across comparison periods. Cached results and execution caps may prevent the extra row from being returned.

Each measure's **Format and display** dialog sets its label, currency, decimal precision, abbreviation, percentage format, and suffix. Percentage formatting expects fractional values (0.25 displays as 25%); percent-of-total and percent-change calculations produce that scale automatically. Formats persist in saved insights and apply to charts, tables, and pivot cells. Bar, line, and area charts support a separate series style and left/right axis for each measure. **Combine line + bar** assigns two measures to separate axes with bar and line styles.

Click a bar, line point, table cell, or pivot cell to explore its source rows. **Filter in new worksheet** preserves the original insight and adds the selected dimensions to a new worksheet. **View underlying rows** loads up to 1,000 matching source rows before aggregation; **Open in SQL editor** carries the same conditions, connection, and effective dashboard filters. Total cells omit rolled-up dimensions, and **Other** selects the categories outside the current Top N. Comparison-period points open rows from their original dates; their filtered-worksheet action is disabled to avoid combining current dates with prior-period conditions. These actions are unavailable on public shared insights.

**Compare previous period** turns date comparison on or off in one click. The adjacent comparison picker still supports custom offsets. Select a bounded date range before enabling comparison.

With `SQL_EDITOR_BI_MODE` enabled, open **Business intelligence**, select a table and choose **Add calculated measure** in the data pane.
Enter a name and an aggregate SQL formula, such as `sum(revenue) / nullIf(count(DISTINCT user_id), 0)` for average revenue per user.
Use field names from the selected table. Filters apply before the formula runs for each group on the worksheet.

The measure appears on Rows. Its menu lets you edit the name and formula, sort by the measure, or remove it.
Cancel discards the draft. Names and formulas persist with the worksheet's BI configuration; measures are not shared across worksheets.
Calculated measures cannot become dimensions or row filters.
If a measure name conflicts with a field or another result column, the generated query adds a numeric suffix to its column name. The worksheet keeps the name you entered on the measure pill and sort menu.

## Filters in BI mode

Drop a field onto the compact Filters shelf beside or below the data pane. Quick filters on the right
show the current selection; click a value to edit it, or use the checkbox beside its name to toggle it.
Wider worksheets show quick filters in two columns. In tight scenes, click a filter pill on the left
to edit its values and settings. String fields start with
**Is any of**: select several values, or type a value and press Enter. **Is none of** excludes the
selected values. An empty selection leaves all values included. Suggestions load when the picker
opens, respect the other applied filters, and show up to 100 distinct values; additional values can
always be entered manually.

Use **Between** for numeric or date fields. Both bounds are inclusive, and either can be left empty
for an open-ended range. Date-time fields include the time. Uncheck **Apply filter** in the editor to temporarily
ignore a filter without losing its settings. Click the field pill to edit the field expression, date
part, or custom SQL condition, or to remove the filter. Filter changes respect the worksheet's
auto-update setting and are preserved with its saved configuration.
Numeric filters preserve the precision of entered values. Invalid numbers show an error and prevent the worksheet from running until corrected or disabled.

**Row filters** apply before aggregation. **Result filters** apply to aggregated measures, calculated measures, and table calculations after they run, before sorting and the final row limit. For example, add result filters for revenue greater than 1,000 and purchase count at least five. Each filter can be disabled without removing it. Removing a measure removes its result filters; the remaining filters keep their measure assignments.

Both cards have **AND / OR groups**. Choose **AND — match all** or **OR — match any**, add nested groups, and move existing filters into them. Empty groups have no effect. Ungroup returns its conditions to the outer group. Existing worksheets retain their flat AND conditions. Date ranges and dashboard filters always combine with worksheet row conditions using AND; drill-down selections do too.

Top N selects categories before result filters run. Comparison periods apply the same result conditions independently. Result filters hide detail groups; totals still aggregate all data matching the row filters. Table calculations use the full aggregated result before result filtering. Query usage events include result-filter and group counts without their values.

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

## Connected fields in BI mode

Below Dimensions and Measures, **Connections** lists the selected table's linked tables and views.
Expand a connection to load its dimensions, measures, and nested connections. Inside connections,
fields and further links appear without section headings.

Drag connected fields onto a shelf, double-click them, or press Enter or Space to add dimensions to Rows and measures to Values.
Measures are aggregated automatically. The worksheet keeps its original source table and uses the full
connection path in queries and shelf labels, such as `person.company.name`.
Connections expand on demand, including repeated links to the same table. Search filters the fields
inside expanded connections, and a failed field load has a Retry button.
Aliases load any intermediate tables automatically. Loading and failed connections stay visible during search.
Virtual connections expose the field names provided by the existing schema as dimensions. The schema does
not include their field types or nested link definitions, so these connections do not infer measures or further links.
