---
name: working-with-charts
description: >
  Guides consumers of @posthog/quill-charts through chart selection, data, themes, sizing, and composition.
  Use when adding or changing a chart built with the package, including its axes, tooltips, legend, overlays, or interactions.
  Links to package examples and API docs. Does not cover product integration or library internals.
---

# Consuming quill-charts

Use the package's components and defaults before writing custom chart code.
Read only the example or topic needed for the task.
For changes inside the library, use [CONTRIBUTING.md](../../../packages/quill/packages/charts/src/docs/CONTRIBUTING.md) instead.

## Choose a component

Use the [chart-selection table](../../../packages/quill/packages/charts/AGENTS.md#choosing-a-chart), then read a matching [package story](../../../packages/quill/packages/charts/src/charts/).
For a date axis, start with `DateAxis` in [TimeSeriesLineChart stories](../../../packages/quill/packages/charts/src/charts/TimeSeriesLineChart/TimeSeriesLineChart.stories.tsx).
Import components and types from `@posthog/quill-charts`, not internal source paths.

## Supply data, theme, and dimensions

- Use stable series keys and typed `meta` for tooltip or click data.
- For label-based charts, keep labels unique and align each series' data with them.
- Use ISO date labels with `TimeSeries*` charts; format ticks through the axis config.
- Use `NaN` for missing numeric series values, not zero.
- Keep series, config, and callbacks stable across unrelated renders.
- Give charts that fill their container a parent with real dimensions, including a nonzero height.

Reuse the host's existing chart theme setup.
For a new host without chart theming, use the package's `useChartTheme` hook.
Follow the [setup and theme docs](../../../packages/quill/packages/charts/src/README.md#setup) for tokens and CSS.
Omit series colors to use the theme palette; resolve CSS variables before passing explicit canvas colors.
Read the selected chart's props and the [Series type](../../../packages/quill/packages/charts/src/core/types.ts) for its data contract.

## Configure before customizing

Prefer the selected chart's built-in tooltip and legend.
Use config options and exported overlays before custom renderers.
Load only the relevant topic:

| Task                                        | Package docs                                                                     |
| ------------------------------------------- | -------------------------------------------------------------------------------- |
| Axis formatting, ranges, or multiple axes   | [Axes](../../../packages/quill/packages/charts/src/docs/axes.md)                 |
| Bar layouts or per-bar styling              | [Bars](../../../packages/quill/packages/charts/src/docs/bars.md)                 |
| Tooltip formatting or content               | [Tooltips](../../../packages/quill/packages/charts/src/docs/tooltips.md)         |
| Legend visibility or interaction            | [Legend](../../../packages/quill/packages/charts/src/docs/legend.md)             |
| Reference lines, labels, or custom overlays | [Overlays](../../../packages/quill/packages/charts/src/docs/overlays.md)         |
| Clicks, zoom, or selection                  | [Interactions](../../../packages/quill/packages/charts/src/docs/interactions.md) |

## Verify

Render at the intended container sizes and in light and dark themes.
Check missing values, long labels, and any interactions you changed.
Extend relevant tests and stories; use the [consumer testing guide](../../../packages/quill/packages/charts/src/docs/TESTING.md#testing-code-that-uses-hog-charts) for chart accessors.

Keep detailed API behavior in the package docs rather than copying it into this skill.
