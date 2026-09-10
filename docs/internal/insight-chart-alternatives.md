# Insight chart alternatives

The `product-analytics-chart-alternatives` feature flag enables visual chart choices in the Trends editor.
Keep the flag off until the interface passes product review.

## Behavior

The editor shows the current chart and up to three compatible alternatives above the result.
The previews are illustrations, not additional query results.
Select **All chart types** to browse the full catalog.
Unavailable choices explain their requirements.

Selecting a type updates the unsaved query through the existing chart-update path.
A selection that removes a breakdown or formula, or changes the map's country breakdown, requires confirmation.
**Return to original** restores the full query from before chart exploration.
It remains available while the result loads.
Another query edit or a successful save clears that return state.

The feature applies only to editable Trends insights in the standard editor.
Dashboard tiles, embedded insights, shared insights, and other insight families keep their existing controls.
The standard dropdown and visual catalog share chart metadata and eligibility rules.

## Local preview

Run Storybook with `pnpm --filter=@posthog/storybook start`.
Open **Scenes-App → Insights → Chart alternatives**.
The stories cover the flag-off baseline, the enabled editor, numeric properties, country breakdowns, a narrow scene, and the open catalog.
Story parameters enable the flag without changing its production rollout.

## Measurement

`insight chart alternative selected` records the previous display, selected display, and source (`strip` or `gallery`).
`insight chart alternative returned` records the reverse action with the same properties.
These events contain no query contents or property values.
Use the existing `insight saved` event to measure target-type saves.
Selection counts alone do not establish usefulness.

Before widening the flag, check target-type saves and overall saving.
Check query errors and latency for regressions.
Review whether users understand the selected charts and return to their saved insights.
