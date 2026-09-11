# Marketing configuration writes

Settings updates send only the changed field and refresh the Marketing configuration under a row lock, preserving unrelated concurrent changes.

Explicit conversion-goal list updates still replace the list; simultaneous edits to that same list are not merged.

Loading a project replaces the current and saved Marketing settings with that project’s configuration, including an empty configuration when none exists.

Setup is available when either `marketing-analytics-setup` or `new-marketing-analytics-dashboard` is enabled for the requesting person. Both Setup endpoints use the same rule; existing project permissions still apply.

Setup usage emits `marketing analytics setup section viewed` on entry and section changes.
Suggestion review, dismissal, restoration, batch review, capability filters, rescans and navigation have separate events.
`marketing analytics setup change submitted`, `change completed` and `change failed` share the same prefix and report operation types, counts, source and whether the change is an undo. Completed reports the server's applied count, which may be zero.
`marketing analytics setup sync retry completed` reports requested and failed counts; it measures scheduling retries, not completed syncs.
Payloads exclude suggestion IDs, titles, evidence, goal names and UTM values. Source navigation measures entry into connection flows; existing warehouse connection events measure their completion.

## Acquisition preview

With `new-marketing-analytics-dashboard` enabled, the dashboard shows visitors, sessions and pageviews using the existing Web Overview query and metric cards. The date range, comparison and saved test-account filter apply to both the summary and channel table. Reload summary refreshes only the summary. The legacy dashboard remains available when the flag is off.

Revenue in the new dashboard uses event/action goals marked as revenue that sum an amount property. It displays one goal at a time through the existing attribution table, counts repeat purchases and shares attribution date, breakdown and exclusion filters. Projects without eligible goals link to Setup. Warehouse goals remain in Ad performance.

Revenue ranks rows by their highest attributed value across models before the server limit and chart limit. Conversion queries retain conversion-count ordering.

Engagement displays session duration and bounce rate from the same Web Overview response as Acquisition. Both sections share date, comparison and test-account filters; rendering Engagement adds no extra query.

The new dashboard embeds the existing Attribution explorer as Conversion when `marketing-analytics-attribution` is enabled. It keeps goal selection, attribution models, conversion paths and the explorer’s date and test-account filters.

The new dashboard also embeds the existing Retention explorer when `marketing-analytics-retention` is enabled. It shares the acquisition date range and keeps the explorer’s cohort controls, reload and empty state. Previous-period comparison and the traffic test-account filter do not apply to Retention.
