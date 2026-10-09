# Marketing source suggestions

Marketing analytics suggests connecting an ad platform when a matching UTM source has events with paid attribution signals.
Connection suggestions display the number of these events over the last seven days and rank platforms by that count.
Events without paid signals and fuzzy-only source matches do not increase the count.
Each event counts at most once for its matched platform, even if it carries multiple paid signals.

The count includes all matching event types, so it does not represent unique visitors or ad clicks.
For example, a source with 700 matching events, including 17 with paid signals, shows 17 events in its connection suggestion.
It ranks below a source with 25 paid events, regardless of that source's total traffic.

These counts guide connection suggestions; they do not change report attribution or connected-source sync checks.

## MCP setup recommendations

The `marketing-analytics-setup-plan-mcp` feature flag controls whether the MCP server exposes the read-only `marketing-analytics-setup-plan` tool.
The tool returns ranked source connection recommendations with evidence and confidence, alongside other setup improvements.
It supports `refresh=true` for an explicit rescan and does not connect accounts or apply changes.
Incomplete or truncated scan results must be presented as such.

## Search performance

Spend and conversions require a synced ad platform source in the current search filters.
Google Search Console reports organic traffic metrics only.
The Traffic view always includes the Position column when Google Search Console, Google Ads, or Bing Ads is ready.
The Position cell shows the organic average position for Google Search Console, or top and first-position impression percentages for Google Ads keywords and Bing Ads.
Hover over each label or value, or focus it with the keyboard, for its definition.
Google Ads keyword placement comes from the `keyword_placement_stats` table, selected by default for new connections.
For existing connections, enable it in the Google Ads source settings and wait for its first successful sync to see Top and First percentages.
These percentages use Google Search impressions, weighted by impressions, and exclude Search partners.
The placement table does not include click-type segmentation, which Google Ads does not allow with these metrics.
Clicks, spend, conversions, and total impressions continue to come from `keyword_stats`.
When keyword traffic tables are ready but placement data is unavailable, a separate notice explains how to enable or restore `keyword_placement_stats`.
Traffic remains visible while placement data is pending.
If the placement table is missing or the user cannot access it, the report omits its placement data and shows an access notice.
Google Ads landing page breakdowns show no placement percentages because Google Ads does not support these metrics for the landing page resource.
Historical placement columns in `keyword_stats` and `landing_page_stats` are ignored.
Bing Ads percentages use Microsoft Advertising report values, weighted by impressions.
They do not identify second or third position, or the search results page.
Bing Ads connections need to sync `keyword_performance_report` or `destination_url_performance_report`.
Older rows without placement data show no value.
When no paid source is ready, the disabled control directs users to check their source settings or filters.
For Google Ads landing pages, enable `landing_page_stats` and wait for its first sync to finish.

## X Ads

X Ads uses `twitter`, `x`, `twitter_ads`, and `x_ads` as its default source aliases.
The `marketing-analytics-twitter-ads` flag controls availability in Marketing analytics, independently of the warehouse connector's `dwh-twitter-ads` release flag.
When the Marketing analytics flag is off, X Ads is excluded from native reporting, connection menus, and health diagnostics, including attribution suggestions.
Report UTM normalization stays stable across flag changes, as it does for the other native integrations.
The connector retains its existing OAuth setup requirements.
The new-source announcement uses the shared dismissal key: adding X Ads does not show it again to users who already opened the announcement.

Import `campaigns` and `campaign_stats` for campaign reporting, and `line_items` and `line_item_stats` for ad group reporting.
All four tables are recommended and selected by default when setting up a new X Ads source.
Existing connections keep their selected tables until the user changes them.
Daily spend is converted from micros using each row's funding-instrument currency and report date.
Monetary tiles require the currency column; impressions remain available when only currency is missing.
Clicks include the engagement clicks reported by X, not only outbound link clicks.
The current import provides spend, clicks, and impressions; platform-reported conversions and revenue are not imported.
PostHog conversion goals still work through campaign attribution.
Ad-level reporting is unavailable because the connector does not import promoted-post statistics.

## Search performance

Keywords and queries includes paid keywords from ad platforms and organic queries from Google Search Console.
Search Console requires a synced `search_analytics_by_query` or `search_analytics_by_query_page` table; the integration and paid/organic filters determine which sources appear.
Each search table has a reload control and query duration.
Pagination stays within the table without scrolling the scene, and changing between keywords and landing pages starts on page 1.
Tables with more than ten results reserve consistent space for values and comparisons and keep room for ten rows on shorter pages.
Tables with ten results or fewer keep their compact layout without reserved space.
Use the page selector to jump directly to a page, or the arrows to move one page at a time.

## Bing Ads landing pages

Search performance includes Bing Ads in the Landing pages view.
Enable `destination_url_performance_report` in the Bing Ads source settings and wait for its first successful sync.
The view groups search distribution metrics by destination URL and currency, with clicks, impressions, spend, and platform-attributed conversions.
The connector uses `ConversionsQualified` because Microsoft deprecated `Conversions` for this report.
Keyword reporting continues to use `keyword_performance_report`.

## Google Ads campaign trends

Campaign trend charts accept both `campaign_overview_stats` and the legacy `campaign_stats` schema.
The current schema takes precedence when both are available.
Table resolution uses schema metadata when available and otherwise recognizes source and custom table-name prefixes.

## Source scan caching and readiness

The setup plan caches event scans for seven days per project. Explicit refresh requests respect a one-hour cooldown.
Source health polling refreshes metadata without forcing every dashboard query.
Campaign reporting waits for all required schemas to complete their first sync.
Source refresh failures retain the previous list and allow a later retry.
Native source readiness checks include required schema failures and paused imports.
