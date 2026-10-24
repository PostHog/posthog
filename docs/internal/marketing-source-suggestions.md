# Marketing source suggestions

Marketing analytics suggests connecting an ad platform when a matching UTM source has events with paid attribution signals.
Connection suggestions display the number of these events over the last seven days and rank platforms by that count.
Events without paid signals and fuzzy-only source matches do not increase the count.
Each event counts at most once for its matched platform, even if it carries multiple paid signals.

The count includes all matching event types, so it does not represent unique visitors or ad clicks.
For example, a source with 700 matching events, including 17 with paid signals, shows 17 events in its connection suggestion.
It ranks below a source with 25 paid events, regardless of that source's total traffic.

These counts guide connection suggestions; they do not change report attribution or connected-source sync checks.

## Background source checks

Source health checks run when the window regains focus and every 30 seconds while a source is syncing.
These checks update source metadata and validation without forcing all dashboard queries to refresh.
Queries reload when their inputs change or when the user refreshes the dashboard.

## MCP setup recommendations

The `marketing-analytics-setup-plan-mcp` feature flag controls whether the MCP server exposes the read-only `marketing-analytics-setup-plan` tool.
The same flag also enables the read-only setup plan API independently of the Setup tab, dashboard, and source onboarding rollouts.
Applying setup operations still requires the Setup or dashboard flag and the existing write permissions.
The tool returns ranked source connection recommendations with evidence and confidence, alongside other setup improvements.
It supports `refresh=true` for an explicit rescan and does not connect accounts or apply changes.
Incomplete or truncated scan results must be presented as such.

## Updating conversion goals through MCP

The update tool requires `conversion_goal_id` outside the `goal` patch.
Omit `kind` for partial updates. Changing `kind` replaces the stored goal, so send the complete new definition, including its name, schema map, and target fields.
An invalid replacement returns `conversion_goal_kind_change_invalid` with the required fields in the response detail.
MCP analytics records the controlled error code and field without storing the response detail.

## Search performance

Reported conversions and reported CPA require a synced ad platform source in the current search filters.
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
The Traffic and Conversions views both include spend when a paid source is ready.
The first column stays visible while the metrics scroll horizontally.
The `marketing-analytics-search-conversions` flag controls PostHog conversion goals in Search performance, independently of the precomputation flags.
When the flag is off or unavailable, the UI hides the goal columns and the backend skips conversion attribution, including requests from older clients.
Platform-reported conversions remain available, and the main Ad performance conversion goals keep their existing behavior.
In Search performance → Conversions, the Ad performance Include conversion goals switch adds the first five supported event or action goals and their cost per conversion.
Goals with missing actions are skipped with a warning before the five-goal limit is applied.
If more goals are configured, a warning directs users to the attribution report for other goals.
This limits each search request to five attribution queries, or ten with period comparison.
Search requests calculate credit for the configured model only, without the attribution report’s visitor counts, revenue, or footer totals.
These conversions use the session attribution engine with the team's attribution model, lookback window, goal filters, and test-account exclusion setting.
Credit is matched after attribution, so other channels retain their share.
Landing pages match by landing URL and search source.
Paid keywords match by the session entry `utm_term` and search source, ignoring case and surrounding whitespace.
Set `utm_term` to the keyword text in Google Ads or Bing Ads tracking URLs.
Click IDs identify the paid source but do not provide a keyword lookup.
Organic query rows do not receive PostHog conversion credit; use Landing pages for organic goals.
Keywords with multiple match types or currencies leave PostHog metrics empty because the same credit cannot be assigned to individual rows.
URL query parameters and fragments are combined in this view.
Opening a combined landing page preserves this URL matching in the organic query details without loading PostHog goals.
With goals off, landing page details keep exact URL matching.
Google organic search, paid Google search, and paid Bing search receive separate credit; campaign source aliases use the existing Marketing analytics mappings.
Canonical Google and Bing source names match regardless of capitalization.
Paid Search sessions can also identify Google through `gclid` and Bing through `msclkid`.
A click ID alone does not classify a session as search traffic; the session must have the Paid Search channel.
When `marketing-analytics-live-session-resolution` is enabled, eligible search goals reuse shared live session resolution.
They do not read session or conversion precomputation tables.
Organic rows have no cost per conversion, and pages with spend in multiple currencies leave PostHog metrics empty because credit cannot be assigned to individual ad accounts.
Data warehouse goals are not supported by search attribution.
Turning the switch off removes PostHog goal columns and stops their queries while keeping platform-reported conversions.
The switch only loads search conversions in the Conversions view; organic detail views do not imply query-level PostHog attribution.
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
Long landing URLs truncate within the first column; hover over the URL to read it in full.
Enable Wrap text in Table options to show complete URLs and keywords across multiple lines, including in the detail view.
The first column stays visible while scrolling horizontally through metrics and conversion goals.
Tables with more than ten results reserve consistent space for values and comparisons and keep room for ten rows on shorter pages.
Tables with ten results or fewer keep their compact layout without reserved space.
Use the page selector to jump directly to a page, or the arrows to move one page at a time.

## Bing Ads landing pages

Search performance includes Bing Ads in the Landing pages view.
Enable `destination_url_performance_report` in the Bing Ads source settings and wait for its first successful sync.
The view groups search distribution metrics by destination URL and currency, with clicks, impressions, spend, and platform-attributed conversions.
The connector uses `ConversionsQualified` because Microsoft deprecated `Conversions` for this report.
Keyword reporting continues to use `keyword_performance_report`.

## Source connection context

Setup scan recommendations include a connection link with the suggested source kind, a project-scoped `returnUrl`, and `returnLabel=Marketing analytics`.
The `entry_point` query parameter identifies the originating surface separately from the visible return label.
Marketing links identify MCP (`marketing_analytics_mcp`), onboarding, Setup, the integration menu, search suggestions, and search detail.
The connection flow preserves return URLs, labels, access mode, and origin metadata through OAuth.
The `warehouse source connect completed` event records the originating entry point.
Users complete platform authorization through the connection flow.

## Google Ads campaign trends

Campaign trend charts accept both `campaign_overview_stats` and the legacy `campaign_stats` schema.
The current schema takes precedence when both are available.
Table resolution uses schema metadata when available and otherwise recognizes source and custom table-name prefixes.

## Source scan caching and readiness

The setup plan caches event scans for seven days per project. Explicit refresh requests respect a one-hour cooldown.
Source health polling refreshes metadata without forcing every dashboard query.
Campaign reporting waits for all required schemas to complete their first sync.

## Source connection components

The integration catalog includes a search field and orders native sources by usage.
Connection panels distinguish scanning, errors, pending first sync, and ready sources.
Search connections use a separate card controlled by `marketing-analytics-organic-keywords`.

Review fixes preserve source data after request failures and provide a retry for connection errors.
Blocked required imports show Needs attention with a Manage source link.
Dashboard dismissals use the shared Setup restore controls.
Source refresh failures retain the previous list and allow a later retry.
Native source readiness checks include required schema failures and paused imports.

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

The rescan cooldown uses the server scan time. Failed plan requests can retry without a fresh scan.
Search controls and the Search Console connection action remain available during paid sync.

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

The redesigned dashboard preserves its existing source suggestions and dashboard view when source onboarding is disabled.

After ad data is ready, remaining source suggestions use a compact card without first-sync messages or already-ready connections.
Connections needing attention remain actionable beside the suggestions.
Source setup component stories cover panel states; source onboarding stories cover only dashboard integration, independent search sources, and flag rollback.

Ad and Search setup cards use the same heading size and content inset.
Source onboarding stories cover the current dashboard; they do not add snapshots for the experimental dashboard.

A missing setup plan stays in the scanning state until a request fails.
Manual retries bypass the event scan cache, including retries without a loaded plan.
Managed external tables count as ready only when their schema sync status is completed; self-managed mapped tables remain available directly.

The source onboarding header opens the in-app feedback form directly. The legacy feedback banner remains unchanged when source onboarding is disabled.

## Bing Ads reconnection warning

The `legacy-oauth-reconnect-warning` feature flag controls the reconnection banner in Marketing analytics and its settings.
The banner only appears when a project has a Bing Ads integration marked with `oauth_uses_legacy_client`.
It asks users to reconnect before November 30, 2026.
The flag controls the warning only; changing it does not disable fallback credentials or migrate existing grants.
Use project targeting to release the warning gradually.

## Required table status

The source status banner names each required table that needs attention and links native connections directly to their Schemas tab.
Disabled imports, missing tables, running syncs, failures, pauses, cancellations, and tables awaiting a completed sync have separate messages.
Multiple table problems remain visible together, even when the connection has one overall status.
Google Ads connections using the legacy `campaign_stats` schema retain support and display that actual schema name.

## Connection issues

The source onboarding panel groups connected sources by integration and identifies each connection by its prefix, or its source ID when no prefix exists.
Expand an integration to review the affected tables and open the connection’s source settings.
The panel includes the source validation details shown by the status banner.
When the panel displays a connection, its duplicate status banner entry is hidden.
Configuration validation failures and issues for sources outside the panel remain in the banner.
With source onboarding disabled, the existing banner remains available.

## Ad performance metric cards

The Ad performance summary uses the same metric cards as Web analytics.
Cards preserve period comparisons, currency formatting, and missing-value labels, and wrap to the available scene width.

Ad performance cards include time-series sparklines for advertising metrics, including platform-reported conversions.
Select an advertising metric card to update the existing trend chart while keeping the date range, interval, and source filters.
CPC, CTR, reported ROAS, and cost per reported conversion use ratios of bucket totals in both sparklines and the main trend, with monetary values converted to the project currency; undefined ratios leave gaps rather than zeroes.
Attributed PostHog conversion goals retain their summary cards without sparklines or selection.

Advertising metrics appear first, followed by attributed conversion goals and their cost per conversion.
The goal cards use a separate grid so cards without sparklines keep a compact height.

The overview loads on demand so other query surfaces do not load marketing-specific validation eagerly.

The Ad performance summary groups metrics by source: Ad platforms contains platform-reported metrics, and PostHog contains configured conversion goals and their costs.
Configure metrics uses the same apply-and-cancel interaction as Configure columns.
It lets users show or hide individual metrics, show or hide an entire group, and reorder metrics within each group with the move buttons.
Each group can also collapse without changing which metrics are selected.
The summary saves visibility, order, and collapsed groups in browser storage per project and view, matching table column preferences.
These preferences survive reloads in the same browser; they do not change table columns or the underlying queries.
New metrics appear by default, and removed goals do not leave empty cards.
