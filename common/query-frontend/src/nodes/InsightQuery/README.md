# InsightQuery

This folder has no component of its own — it holds shared helpers for the _insight query_ family of sources: `TrendsQuery`, `FunnelsQuery`, `RetentionQuery`, `PathsQuery`, `StickinessQuery`, and `LifecycleQuery` (the `InsightQueryNode` union in `../../schema/schema-general.ts`).
It provides per-kind default queries and the conversion layer between modern query nodes and the legacy `FilterType` format that older insights, URLs, and APIs still use.

## Rendering

Insight queries are _sources_, not standalone renderable nodes.
Wrap one in an `InsightVizNode` and pass it to `<Query />`:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'
import { NodeKind } from '@posthog/query-frontend/schema/schema-general'

;<Query
  query={{
    kind: NodeKind.InsightVizNode,
    source: {
      kind: NodeKind.LifecycleQuery,
      series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
    },
  }}
/>
```

The rendering itself lives in `../InsightViz/` (container, editor filters, display) and the per-kind folders (`../TrendsQuery/`, `../FunnelsQuery/`, `../RetentionQuery/`, `../PathsQuery/`).
Stickiness and lifecycle have no folders of their own — they reuse the trends viz components via `TrendInsight` (see `../TrendsQuery/README.md`).

## Key files

- `defaults.ts` — `nodeKindToDefaultQuery` / `getNodeKindToDefaultQuery()`: the default query for each product analytics insight kind (`ProductAnalyticsInsightNodeKind`), seeded with the project's default event. Used when creating a new insight or switching insight type.
- `utils/filtersToQueryNode.ts` — converts legacy `FilterType` filters (e.g. from saved insights created before the query schema) into an `InsightQueryNode`. Includes `actionsAndEventsToSeries`.
- `utils/queryNodeToFilter.ts` — the reverse: converts a query node back into legacy filters (`queryNodeToFilter`, `seriesNodeToFilter`, `nodeKindToInsightType`). Still needed for legacy API surfaces and persons-modal URLs.
- `utils/cleanProperties.ts` — normalizes property filter shapes when converting.
- `utils/eventNameToEventsNode.ts` — small helper to build an `EventsNode` from an event name.
- `utils/legacy.ts` — `isLegacyTrendsFilter` and friends: detect snake_case legacy filter keys.

These helpers are an internal implementation detail of the `<Query />` tag and the insight editing flow; consumers interact through `query`/`setQuery` props on `<Query />`.
