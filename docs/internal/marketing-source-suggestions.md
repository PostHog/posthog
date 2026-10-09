# Marketing source suggestions

Marketing analytics suggests connecting an ad platform when a matching UTM source has events with paid attribution signals.
Connection suggestions display the number of these events over the last seven days and rank platforms by that count.
Events without paid signals and fuzzy-only source matches do not increase the count.
Each event counts at most once for its matched platform, even if it carries multiple paid signals.

The count includes all matching event types, so it does not represent unique visitors or ad clicks.
For example, a source with 700 matching events, including 17 with paid signals, shows 17 events in its connection suggestion.
It ranks below a source with 25 paid events, regardless of that source's total traffic.

These counts guide connection suggestions; they do not change report attribution or connected-source sync checks.

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

## Source onboarding

Marketing analytics skips source onboarding when a marketing source is configured, including sources whose first sync is still running.
For projects without sources, onboarding scans UTM-tagged events and suggests matching ad platforms.
Users can continue to the dashboard at any time, connect more platforms while a sync runs, or choose from all supported sources when no platform is detected.
The event scan is cached for seven days per project and lookback window; source connection and sync health continue to use current configuration.
Use **Scan events again** in Setup → Sources to bypass the event cache.
The dashboard keeps pending source suggestions and sync status visible so missing spend data is not mistaken for zero spend.
Conversion goals are configured within the product rather than as an onboarding step.

The source onboarding shows scan progress while it runs, then detected platforms and their connection benefits.
**Browse integrations** opens the complete source selector without leaving the dashboard.
The scan message states its seven-day detection window.

On the current dashboard, spend and ad performance tiles stay hidden until a source supplies data.
The connection notice or detected-source suggestions explain what needs to be connected.

Source health refreshes on window focus without replacing the resolved dashboard or cached event suggestions with a loading screen.
Health-only changes refresh source metadata and validation without forcing all dashboard queries to run again.
Campaign reporting waits for every required campaign and campaign-statistics schema to be enabled and finish its first sync.
The initial source check shows separate loading states for Ad performance and Search performance, without offering connections before the source list is known.
Projects without sources show a connection card instead of empty metric placeholders.
Search performance stays visible while the paid-source event scan runs, fails, or returns no platforms.
Search performance remains behind `marketing-analytics-organic-keywords`.
The paid-source onboarding and automatic dashboard scan are behind `marketing-analytics-source-onboarding`.
Disabling this flag restores the original welcome, source connection, and conversion-goal wizard, including its source catalog and dashboard loading state.
The source scan, enhanced catalog, dashboard section changes, and header feedback action require this flag.
Google Search Console onboarding stays behind its independent `marketing-analytics-organic-keywords` flag.
Mounting source setup state does not start the UTM audit; Integration health loads the audit when opened.
Search onboarding stays independent under `marketing-analytics-organic-keywords`.
The read-only setup plan is available with `marketing-analytics-source-onboarding`, `marketing-analytics-setup`, or `new-marketing-analytics-dashboard`; other setup operations keep their existing flag requirements.

Source setup uses a consistent panel for connection checks, event scanning, suggestions, empty results, and recoverable errors.
Detected platforms show concise evidence with expandable details.
Configured connections show their first-sync status beside pending platforms.
The manual catalog supports search and returning to suggestions.
The current dashboard shows metric filters only once marketing data is available; beta feedback is available in the scene header.

Source setup panels are centered within the scene.
**Browse integrations** opens the searchable catalog in place; **Back to suggestions** restores the pending connections without another scan.
When `marketing-analytics-organic-keywords` enables Search performance, setup and the manual catalog show Google Search Console as an optional organic-search connection, separate from detected ad platforms.

The source setup panel explains how connections centralize campaign performance and how conversion goals based on PostHog events measure conversion costs and return on ad spend.
When Search performance is enabled, it also explains paid-keyword and organic-query analysis for optimizing search ads.
Pending-source cards offer the source connection buttons and **Browse integrations**; they do not redirect users to Setup to review the same suggestions.

Manual event scans are available from onboarding and the dashboard with **Scan again**.
A successful scan starts a one-hour cooldown per project; the server also reuses the scan during this cooldown.
Failed scans can be retried. Suggested connections stay visible during a refresh.
When no platforms are detected, the panel explains how UTM parameters on ad links help PostHog identify platforms.

With Search performance enabled, a connected Google Search Console source also skips onboarding.
The current dashboard shows Search performance below a compact ad-source connection panel when no ad data is ready.
Search Console does not unlock ad spend metrics; its sync and data readiness remain independent.

The Search Console connection card explains how connecting Google Ads adds paid keyword, spend, and conversion data alongside organic search queries.

When none of Google Ads, Bing Ads, or Google Search Console is connected, the enabled Search performance flag shows a separate search connection card with all three integrations.

Search connections appear as a separate card below both the source suggestions and the manual integration catalog.

The integration catalog opened inside the dashboard has no continue action because the user is already on the dashboard.
The initial onboarding catalog offers **Skip for now** when no sources are connected.

The integration catalog places its back action in the same footer as the browse action in suggestions.
The separate search connection card offers Google Ads, Bing Ads, and Google Search Console with their connection states.

The legacy dashboard and ad performance tab show search tables only after a search source is connected. Without one, the connection card remains visible without empty filter controls.

Dashboard sections keep the Ad performance and Search performance headings outside their setup cards. The cards retain titles that describe the current setup state.

The empty ad setup card uses the money hedgehog illustration. The search connection card uses the magnifying glass hedgehog. Both sit to the right of their headings and descriptions.

The money hedgehog stays in the manual integration catalog so switching from suggestions keeps the same illustration.

Integration buttons show the external-link icon because their connection panels open in a new tab.

The native integration catalog uses a consistent display order: Google Ads, Meta Ads, Bing Ads, LinkedIn Ads, TikTok Ads, Reddit Ads, Pinterest Ads, Snapchat Ads, OpenAI Ads, Apple Ads, Amazon Ads, Rokt Ads, and X Ads. Google Search Console stays in the search section.

The separate Ad performance tab is available only with `new-marketing-analytics-dashboard` enabled.
Enabling Search performance alone keeps paid and organic reporting inside the current Dashboard tab.

Detected-source suggestions keep the money hedgehog in the header, matching the empty state and manual catalog.

Resolved ad-source panels retain the money hedgehog while connections wait or sync, including the compact panel above organic search.
Storybook covers Search Console without ads and ads without Search Console, with ready and first-sync variants.

A connected Google Ads or Bing Ads source shows Search performance below the ad metrics or first-sync panel.
The full search connection card appears only when no search source is connected, so a paid-only project does not repeat Search performance above its ad metrics.

## Google Ads campaign trends

Campaign trend charts accept both `campaign_overview_stats` and the legacy `campaign_stats` schema.
The current schema takes precedence when both are available.
Table resolution uses schema metadata when available and otherwise recognizes source and custom table-name prefixes.

Source refresh failures preserve the last successful source list and retry with a bounded backoff while the onboarding flow is mounted.
An initial connection failure offers a retry in both paid and search sections.
The one-hour rescan cooldown uses the server's seven-day source scan timestamp; loading a cached plan does not start a new cooldown.
A failed plan request can retry during the cooldown without forcing an event scan.
Dashboard dismissals share Setup's restore controls; existing dashboard dismissals migrate to the shared list.
When all detected platforms are dismissed, the card offers Restore suggestions instead of reporting no detections.
Required tables that are missing, disabled, failed, paused, or canceled show Needs attention with a Manage source link before the first sync.
Search date and comparison controls remain available with only Search Console connected, and Search Console can be connected while paid sources sync.
Background source refreshes keep the Search performance table mounted.
Manual source setup opens with the originating project in the URL.
