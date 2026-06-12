# WebVitals

Renders the web vitals queries of web analytics: `WebVitalsQuery` (the dashboard with INP, LCP, FCP, and CLS metric tabs plus a trend chart) and `WebVitalsPathBreakdownQuery` (per-path breakdown of one metric into good / needs improvement / poor bands).
Both components fetch through `dataNodeLogic` (see `../DataNode`) and are display-only — the active tab and percentile come from the web analytics scene (`webAnalyticsLogic`), not from `setQuery`.

In the schema, `WebVitalsQuery` wraps a `source` insight query (a `TrendsQuery` over `$web_vitals` events, one series per metric × percentile) and returns `WebVitalsItem[]`.
`WebVitalsPathBreakdownQuery` takes `percentile`, `metric`, and frontend-supplied `thresholds: [good, poor]`.
See both in `src/schema/schema-general.ts`, and the `WebVitals` / `WebVitalsPathBreakdown` examples in `src/examples.ts`.

## Usage

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

<Query
    query={{
        kind: 'WebVitalsQuery',
        properties: [],
        dateRange: { date_from: '-7d' },
        source: {
            kind: 'TrendsQuery',
            dateRange: { date_from: '-7d' },
            interval: 'day',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$web_vitals',
                    name: '$web_vitals',
                    custom_name: 'LCP',
                    math: 'p90',
                    math_property: '$web_vitals_LCP_value',
                },
                // ... one series per metric (INP, LCP, CLS, FCP) and percentile (p75, p90, p99)
            ],
        },
    }}
/>

<Query
    query={{
        kind: 'WebVitalsPathBreakdownQuery',
        properties: [],
        dateRange: { date_from: '-7d' },
        percentile: 'p90',
        metric: 'CLS',
        thresholds: [0.1, 0.25],
    }}
/>
```

## Key files

- `WebVitals.tsx` — the dashboard: four `WebVitalsTab` cards (one per metric) and, below, the trend for the selected metric rendered with a nested `<Query />` over `webVitalsMetricQuery` from `webAnalyticsLogic`
- `WebVitalsPathBreakdown.tsx` — three-column good / needs improvement / poor path lists
- `definitions.ts` — metric metadata: `WEB_VITALS_THRESHOLDS`, `getMetric` / `getMetricBand`, value formatting, and explanatory copy per metric
- `WebVitalsTab.tsx`, `WebVitalsContent.tsx`, `WebVitalsProgressBar.tsx` — tab card, description panel, and threshold bar

The kea stores (`dataNodeLogic`, plus scene state in `webAnalyticsLogic`) are internal — consumers render via the `<Query />` tag with a `query` prop only.
