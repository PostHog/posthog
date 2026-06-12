# WebOverview

Renders a `WebOverviewQuery` — the headline metrics strip of web analytics (visitors, page views, sessions, session duration, bounce rate, and conversion metrics when a conversion goal is set).
The component fetches data through `dataNodeLogic` (see `../DataNode`) and displays the response with the shared `OverviewGrid` (or `OverviewMetricCardGrid` behind the `web-analytics-metric-cards` feature flag).

In the schema, `WebOverviewQuery` extends the shared web analytics query base: `dateRange`, `properties` (web analytics property filters), `conversionGoal`, `compareFilter`, `filterTestAccounts`, `samplingFactor`, and more.
The response is a list of `WebOverviewItem`s (`key`, `value`, `previous`, `changeFromPreviousPct`, `kind`).
See `WebOverviewQuery` in `src/schema/schema-general.ts`.

## Usage

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

;<Query
  query={{
    kind: 'WebOverviewQuery',
    dateRange: { date_from: '-7d' },
    properties: [],
    compareFilter: { compare: true },
    filterTestAccounts: true,
  }}
/>
```

The node is display-only: there is no `setQuery` editing UI here.
Filters are owned by the host scene (web analytics builds the query in `webAnalyticsLogic` and re-renders with a new query object).

## Key files

- `WebOverview.tsx` — the component: mounts `dataNodeLogic` with the query, maps `WebOverviewQueryResponse.results` (or a cached insight's `result`) into overview items, and picks labels via `labelFromKey`.
  Also surfaces a per-tile warning when no reverse proxy is configured (counts may be underreported), sampling notices, and pre-aggregation/precompute badges with an `onDisableWebAnalyticsPrecompute` context hook.
- `EvenlyDistributedRows.tsx` — layout helper that wraps children into visually balanced rows; also used by `OverviewGrid`.

The grid components themselves live in `../OverviewGrid`.

The kea store (`dataNodeLogic`) is internal to the `<Query />` tag — consumers pass a `query` prop (plus optional `cachedResults` and `context`) and never bind to the logic directly.
