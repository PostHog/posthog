---
name: working-with-charts
description: >
  Helps engineers add or change charts that consume @posthog/quill-charts in the main app, product frontends, desktop, or MCP apps.
  Use for chart selection, series, axes, themes, tooltips, legends, overlays, and chart interactions.
  Routes to existing examples and package docs; insight-specific integration is optional.
  For changes inside the chart library, use its CONTRIBUTING.md instead.
---

# Working with charts

Use the package's components and defaults before adding chart code.
Read only the example or reference needed for the task.
For library changes, use [CONTRIBUTING.md](../../../packages/quill/packages/charts/src/docs/CONTRIBUTING.md) instead.

## 1. Choose a chart and an example

Use the package's [chart-selection table](../../../packages/quill/packages/charts/AGENTS.md#choosing-a-chart).
Start with the nearest existing consumer or a small story:

- [LineChart stories](../../../packages/quill/packages/charts/src/charts/LineChart/LineChart.stories.tsx) for categorical labels.
- The `DateAxis` example in [TimeSeriesLineChart stories](../../../packages/quill/packages/charts/src/charts/TimeSeriesLineChart/TimeSeriesLineChart.stories.tsx) for date labels.
- [Other chart stories](../../../packages/quill/packages/charts/src/charts/) for bars, distributions, funnels, and other shapes.

Do not copy a full insight renderer for a small product chart.
If the chart consumes insight results, use [insight integration](./references/insights.md).

## 2. Use the host's theme

- Main app and product frontends: use `useChartTheme` from [lib/charts/hooks](../../../frontend/src/lib/charts/hooks.ts).
  It uses the app's palette and tooltip styling.
  Prefer its `useChartConfig` helper for memoized config.
- Quill-native surfaces, including desktop and MCP apps: use `useChartTheme` from `@posthog/quill-charts`.
  Follow the package's [setup and theme guidance](../../../packages/quill/packages/charts/src/README.md#setup).

Both theme hooks track theme changes.
Keep product state and data fetching outside the library.
Do not add a transform module unless the data conversion needs one.

## 3. Prepare data and dimensions

- Use stable series keys and typed `meta` for tooltip or click data; do not identify results by array position.
- For label-based charts, keep labels unique and align each series' data with them.
- Use ISO date labels with `TimeSeries*` charts; format ticks through the axis config.
- Represent missing numeric values with `NaN`, not zero.
- Keep series, config, and callbacks stable across unrelated renders.
- Give the chart container real dimensions, including a nonzero height.

Read the selected chart's props and [Series type](../../../packages/quill/packages/charts/src/core/types.ts) for details.
Omit series colors to use the theme palette unless the product assigns a specific meaning to each color.

## 4. Use built-in behavior first

Keep the chart's built-in tooltip and legend unless the requirement needs more.
Prefer config options and exported overlays before custom renderers.
Read only the relevant reference:

| Task                                          | Reference                                                                        |
| --------------------------------------------- | -------------------------------------------------------------------------------- |
| Axis formatting, ranges, or multiple axes     | [Axes](../../../packages/quill/packages/charts/src/docs/axes.md)                 |
| Bar layouts or per-bar styling                | [Bars](../../../packages/quill/packages/charts/src/docs/bars.md)                 |
| Tooltip content or drill-down                 | [Tooltips](./references/tooltips.md)                                             |
| Legend visibility or interaction              | [Legend](../../../packages/quill/packages/charts/src/docs/legend.md)             |
| Annotations, goals, alerts, or custom markers | [Overlays](./references/overlays.md)                                             |
| Clicks, zoom, or selection                    | [Interactions](../../../packages/quill/packages/charts/src/docs/interactions.md) |

In the main app, use [useDateRangeZoom](../../../frontend/src/lib/charts/hooks.ts) for date-range zoom so it follows the shared rollout gate.

## 5. Verify the changed behavior

Keep loading, empty, and error states distinct; reuse the host's existing handling.
Check the rendered chart in light and dark themes, at wide and narrow scene widths (about 520px).
Check the interactions you changed, including their behavior in shared or read-only views where applicable.
Extend relevant tests and stories rather than adding a fixed set of files for every chart.
Use [testing and stories](./references/testing-and-stories.md) when changing coverage.

Keep library behavior in the package docs and app-specific decisions in this skill's references.
