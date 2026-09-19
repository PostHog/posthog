# Insight chart alternatives

The `product-analytics-chart-alternatives` feature flag replaces the chart type dropdown in the Trends editor with a popover that previews chart types on the chart itself when hovered.
Keep the flag off until the interface passes product review.

## Behavior

The chart type button opens a popover listing the chart types.
The list starts with up to three types suggested for the current data, then the remaining types grouped as in the dropdown.
Unavailable choices explain their requirements.
Table is never suggested and only appears in the list.

Hovering or focusing a type swaps the main chart to that type, rendered with the insight's own data.
The real chart returns when the hover ends or the popover closes.
A short hover delay stops a skim down the list from requesting every type.

Selecting a type updates the unsaved query through the existing chart-update path.
A selection that removes a breakdown or formula, or changes the map's country breakdown, requires confirmation.

## Previews

Opening the gallery never computes a query.
Every tile is built from the insight's loaded result, so the gallery renders as soon as the main chart has.
Types in the current chart's category render the loaded result as is.
Cumulative and slope tiles are derived from the loaded time series and are exact.
Total value tiles sum the loaded buckets, which is exact for count and sum maths and an estimate for unique, average, and percentile maths.
Number and metric tiles fold a breakdown into one series, which is an estimate when the breakdown is capped.
World map, calendar heatmap, and box plot tiles show fixed sample data, because their results cannot be built from a time series.
A tile that is an estimate is labeled "Approximate values", and a sample tile is labeled "Sample data"; selecting either runs the real query through the normal path.

When the loaded result is a total value, such as a number or pie, the time series tiles need the raw buckets for the same query.
The logic remembers the last time series it saw for that query in the browser, so switching from a line chart to a pie and opening the gallery costs nothing.
With nothing remembered it asks the server once with `force_cache`, which returns the cached time series when there is one and never starts a computation.
On a cache miss those tiles show their icon instead of a chart.

## Local preview

Run Storybook with `pnpm --filter=@posthog/storybook start`.
Open **Scenes-App → Insights → Chart alternatives**.
The stories cover the flag-off baseline, the enabled editor, the open popover, a hovered type with its preview loaded, and the open popover with a country breakdown.
Story parameters enable the flag without changing its production rollout.

## Measurement

`insight chart alternative selected` records the previous display, selected display, and source (`recommended`, `gallery`, or `preview`).
These events contain no query contents or property values.
Use the existing `insight saved` event to measure target-type saves.
Selection counts alone do not establish usefulness.

Before widening the flag, check target-type saves and overall saving.
Check query errors and latency for regressions.
Review whether users understand the selected charts and return to their saved insights.
