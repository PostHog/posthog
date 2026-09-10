# Insight chart alternatives

The `product-analytics-chart-alternatives` feature flag replaces the chart type dropdown in the Trends editor with a visual catalog.
Keep the flag off until the interface passes product review.

## Behavior

The chart type control in the options bar shows the current chart.
Selecting it opens a modal with every chart type, each with an illustration and a one-line description.
The illustrations are static, not additional query results.
Unavailable choices explain their requirements.

A **Recommended for this data** group at the top lists up to three compatible types the query's shape makes useful:
a box plot for a numeric property, a world map for a country breakdown, and a metric or number for a single series.
The current chart is never recommended.

Selecting a type updates the unsaved query through the existing chart-update path.
A selection that removes a breakdown or formula, or changes the map's country breakdown, requires confirmation.

## Previews

A **Preview as** carousel under the main chart renders the same data in other chart types.
Tiles are ordered by fit: the catalog's recommended types come first, then the rest.
Types in the current chart's category render from the main result, so they cost no extra request:
line, area, bar, stacked bar, and metric share the time-series payload, and number, table, horizontal bar, pie, and donut share the total-value payload.
Types from the other category share one extra request, sent once the main result is in.
That request repeats whenever the query changes, including a switch between the two categories.
Cumulative, slope, box plot, world map, and calendar heatmap change the query itself, so they appear only in the catalog.
Selecting a tile goes through the same selection and confirmation flow as the catalog.

The feature applies only to editable Trends insights in the standard editor.
Dashboard tiles, embedded insights, shared insights, and other insight families keep the dropdown.
The dropdown and the catalog share chart metadata and eligibility rules.

## Local preview

Run Storybook with `pnpm --filter=@posthog/storybook start`.
Open **Scenes-App → Insights → Chart alternatives**.
The stories cover the flag-off baseline, the enabled editor, the open catalog, the open catalog with a country breakdown, and the preview carousel with the extra previews loaded.
Story parameters enable the flag without changing its production rollout.

## Measurement

`insight chart alternative selected` records the previous display, selected display, and source (`recommended`, `gallery`, or `preview`).
These events contain no query contents or property values.
Use the existing `insight saved` event to measure target-type saves.
Selection counts alone do not establish usefulness.

Before widening the flag, check target-type saves and overall saving.
Check query errors and latency for regressions.
Review whether users understand the selected charts and return to their saved insights.
