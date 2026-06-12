# PathsQuery

`PathsQuery` visualizes the paths users take through your product as a Sankey diagram.
The response is a list of `PathsLink` edges (`source` → `target` with a `value` count and average conversion time).
The required `pathsFilter` (which may be `{}`) controls included event types (pageviews, screens, custom events, HogQL expression), start/end points, exclusions, wildcard groupings, path cleaning rules, and edge/step limits.
An optional `funnelPathsFilter` shows paths leading to or from a specific funnel step.

## Rendering

`PathsQuery` is an insight _source_ — wrap it in an `InsightVizNode` and pass that to `<Query />`:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'
import { NodeKind } from '@posthog/query-frontend/schema/schema-general'

;<Query
  query={{
    kind: NodeKind.InsightVizNode,
    source: {
      kind: NodeKind.PathsQuery,
      dateRange: { date_from: '-7d' },
      pathsFilter: {},
    },
  }}
/>
```

See `InsightPathsQuery` in `../../examples.ts`.

## Key files

- `Paths.tsx` — top-level component; manages the canvas element, resize handling, and empty/error states, and delegates drawing to `renderPaths.ts`.
- `renderPaths.ts` — imperative d3 rendering: builds the Sankey layout (`lib/d3/sankey`), draws nodes and links into an SVG, and exposes `PathsHoverHandlers` so hover state flows back into kea.
- `pathsDataLogic.ts` — kea logic keyed by `InsightLogicProps`. Connects to `insightVizDataLogic` and derives the `paths` graph data from the response, exposes `pathsFilter`/`funnelPathsFilter` plus update actions, opens the persons modal for a node's continuing/dropped-off users (via `InsightActorsQuery` with `pathStartKey`/`pathEndKey`/`pathDropoffKey`), and can convert a path into a funnel (`buildFunnelEventsFromPathNode`).
- `pathsInteractionLogic.ts` — hover and node-card UI state (`resolvedNodeCards`, `activeIndices`).
- `pathUtils.ts`, `types.ts`, `constants.ts` — node naming, `PathNodeData`, and shared types.

The kea logics here are an internal implementation detail of the `<Query />` tag.
Consumers pass `query`/`setQuery` props to `<Query />` and should not bind these logics directly.

## Notable sub-components

- `PathNodeCard.tsx` — the floating card overlaid on each Sankey node, with `PathNodeCardButton.tsx` and `PathNodeCardMenu.tsx` for drill-down actions (view continuing/drop-off users, set as start/end point, exclude, create funnel).
- `PathsLabel.tsx` — canvas legend/label row.
- `views/PathStepPicker.tsx` — step limit picker; the remaining paths editor controls (event types, start/end target, exclusions, HogQL, wildcards) live in `../InsightViz/EditorFilters/`.

Unlike trends or funnels, paths draws directly with d3 rather than going through chart components from `@posthog/visualizations`.
