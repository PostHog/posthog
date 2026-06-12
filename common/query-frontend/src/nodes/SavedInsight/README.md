# SavedInsight

`SavedInsightNode` renders an insight that is already saved in PostHog, referenced by its `shortId`, instead of embedding the full query inline.
The component loads the insight from the API, resolves its stored query, and re-renders it through `<Query />` — so a saved trends insight ends up in `InsightViz`, a saved SQL insight in `DataVisualization`, and so on.
Because it extends both `InsightVizNodeViewProps` and `DataTableNodeViewProps` in the schema, the node can carry the same view flags (`full`, `showHeader`, `showTable`, `embedded`, ...) as the node kind it resolves to.

## Rendering

Unlike insight query sources, `SavedInsightNode` is a top-level renderable node — pass it to `<Query />` directly:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'
import { NodeKind } from '@posthog/query-frontend/schema/schema-general'

;<Query
  query={{
    kind: NodeKind.SavedInsightNode,
    shortId: 'abcd1234', // InsightShortId of the saved insight
    full: true,
  }}
/>
```

This is how dashboards and other surfaces embed saved insights without copying the query JSON.

## Key files

- `SavedInsight.tsx` — the whole implementation. It:
  1. builds `InsightLogicProps` with `dashboardItemId: query.shortId`,
  2. mounts `insightLogic` (fetches the insight model) and `insightDataLogic` (resolves the stored query) from `../InsightViz/`,
  3. shows a loading bar while the insight loads,
  4. merges the node's view props onto the resolved query and renders it with a nested `<Query />`, passing the loaded insight as `cachedResults`.

There is no kea logic specific to this folder; `insightLogic` and `insightDataLogic` do the work.
Those logics are an internal implementation detail of the `<Query />` tag — consumers pass `query` props and should not bind them directly (use the `attachTo` prop if a scene logic needs to track them).
