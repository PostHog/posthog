# @posthog/visualizations

Shared visualization package for PostHog.
This is the single source of truth for chart rendering across the app:
insight visualizations (trends, funnels, retention, stickiness, lifecycle), SQL/data visualization charts, web analytics, surveys, revenue analytics, logs, and product sparklines all render through components in this package.

## How it's consumed

The package is consumed straight from source — there is no build step.
`package.json` exposes `"./*": "./src/*"`, and three places wire up the `@posthog/visualizations/*` alias to `common/visualizations/src/*`:

- `tsconfig.json` (root) — `"@posthog/visualizations/*": ["./common/visualizations/src/*"]`, used by TypeScript and the app bundler
- `frontend/jest.config.ts` — `moduleNameMapper` entry for jest
- `common/storybook/webpack.config.js` — webpack `resolve.alias` for storybook

Import components by path, for example:

```ts
import { LineGraph } from '@posthog/visualizations/LineGraph/LineGraph'
import { Sparkline } from '@posthog/visualizations/Sparkline/Sparkline'
import { Chart, ChartOptions } from '@posthog/visualizations/Chart'
```

## Chart.ts — the Chart.js entry point

`src/Chart.ts` is the only place that imports `chart.js` directly.
All Chart.js usage anywhere in the repo must go through `@posthog/visualizations/Chart` instead of importing `chart.js` — this is enforced via the `no-restricted-imports` lint rule that `Chart.ts` itself disables locally.

It does four things:

1. Registers global Chart.js pieces once: all `registerables`, `chartjs-plugin-crosshair`, `chartjs-plugin-zoom`, and the box plot controller/element from `@sgratzl/chartjs-chart-boxplot`. It also disables animations globally and adds a `cursor` tooltip positioner that places tooltips at the pointer.
2. Exports a `Chart` subclass whose `draw()` is a no-op inside the storybook test runner, because canvas rendering proved flaky in visual regression snapshots.
3. Re-exports the Chart.js types consumers need (`ChartOptions`, `ChartDataset`, `TooltipModel`, `Plugin`, …) plus `defaults` and `registerables`.
4. Exports a `DeepPartial` helper type used for chart option overrides.

Chart-type-specific plugins (`chartjs-plugin-annotation`, `chartjs-plugin-datalabels`, `chartjs-plugin-stacked100`, `chartjs-plugin-trendline`, `chartjs-adapter-dayjs-3`) are registered by the components that need them, not globally.

## Inventory

| Folder                 | What it is                                                                                                                                      |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/Chart.ts`         | Chart.js wrapper: global plugin registration, storybook-safe `Chart` subclass, type re-exports                                                  |
| `src/charts/`          | Chart-agnostic building blocks: `ChartTheme`/`AxisFormat` types, value formatting, theme building, CSS variable color resolution                |
| `src/LineGraph/`       | The main Chart.js insight renderer: line/bar/horizontal bar/area graphs plus `PieChart`, tooltip data mapping, and trends display option inputs |
| `src/BoldNumber/`      | Single big number display for trends and SQL insights, with comparison vs. previous period and auto-fitting text                                |
| `src/BoxPlot/`         | Box-and-whisker chart for trends, with legend and results table                                                                                 |
| `src/Histogram/`       | D3-based histogram, used for funnel time-to-convert distributions                                                                               |
| `src/WorldMap/`        | Choropleth world map (hand-rolled country SVG paths) for country breakdowns                                                                     |
| `src/RegionMap/`       | Choropleth state/province map built on `react-simple-maps` and topojson                                                                         |
| `src/CalendarHeatMap/` | Calendar heatmap (day-of-week × hour) display for trends                                                                                        |
| `src/InsightTooltip/`  | Shared tooltip component and the `useInsightTooltip` singleton hover/pinned tooltip manager                                                     |
| `src/Sparkline/`       | Compact, props-driven bar/line sparkline used across products                                                                                   |

Each folder has its own README with exports, props, and consumers.

## Dependency rules

- The package may depend on `@posthog/query-frontend` (insight logics, schema types, formatting helpers) **today**, but treat that as known debt.
  `LineGraph`, `PieChart`, `BoldNumber`, `BoxPlot`, `WorldMap`, `RegionMap`, `CalendarHeatMap`, and `Histogram` currently read from `insightLogic`, `insightVizDataLogic`, `trendsDataLogic`, `teamLogic`, `groupsModel`, and `themeLogic`, which couples them to the insight rendering pipeline.
  The goal is to unwind this coupling so charts take data and formatting via props.
- **New chart components must be props-driven and logic-free**: no kea logics mounted inside the component, no reads from insight or team state.
  `Sparkline` and the `charts/` utilities are the model to follow.
- Chart.js must only be reached through `@posthog/visualizations/Chart`.
- Heavy runtime dependencies (`chart.js` and its plugins, `d3`, `react-simple-maps`, `react`) are `peerDependencies` — the consuming app provides them.

## Adding a new chart component

1. Create a folder under `src/` (e.g. `src/FancyChart/`) with the component, an `index.ts` re-exporting the public surface, and stories/tests alongside.
2. Design it props-driven: data in, callbacks out, an optional `ChartTheme` from `src/charts/types.ts` for colors. Do not mount kea logics or import from `scenes/`.
3. If it uses Chart.js, import `Chart` and its types from `@posthog/visualizations/Chart` — never from `chart.js` directly.
   Register any component-specific plugin at module load (see `Sparkline/Sparkline.tsx` for the pattern) or pass it per-chart via the `plugins` config array.
4. Reuse `src/charts/utils/` for value formatting, theming, and color resolution before writing new helpers.
5. Consume it from app code via `@posthog/visualizations/FancyChart` — no other wiring is needed thanks to the `./*` export map and the tsconfig/jest/storybook aliases.
