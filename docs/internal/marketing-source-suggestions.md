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

Reported conversions and reported CPA require a synced ad platform source in the current search filters.
Google Search Console reports organic traffic metrics only.
The Traffic and Conversions views both include spend when a paid source is ready.
The first column stays visible while the metrics scroll horizontally.
In Landing pages, Include PostHog conversions adds each configured event or action goal and its cost per conversion.
These conversions use the session attribution engine with the team's attribution model, lookback window, goal filters, and test-account exclusion setting.
Credit is matched by landing URL and search source after attribution, so other channels retain their share.
URL query parameters and fragments are combined in this view.
Google organic search and paid Google search receive separate credit; campaign source aliases use the existing Marketing analytics mappings.
Organic rows have no cost per conversion, and pages with spend in multiple currencies leave PostHog metrics empty because credit cannot be assigned to individual ad accounts.
Data warehouse goals are not supported by landing-page attribution.
The checkbox only loads conversions in the Landing pages Conversions view; keyword detail views do not imply query-level PostHog attribution.
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
