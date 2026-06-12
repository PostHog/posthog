# DataNode

The headless data-fetching layer for every data node kind.
`dataNodeLogic` runs any `DataNode` query (`EventsQuery`, `ActorsQuery`, `HogQLQuery`, `SessionsQuery`, `GroupsQuery`, web analytics queries, ...) against the `/query` API and manages loading state, async polling, cancellation, refresh, auto-load, and pagination.
Table and visualization nodes (`DataTable`, `DataVisualization`, `WebOverview`, ...) all mount a `dataNodeLogic` instance under the hood.
The `DataNode.tsx` component itself is only the fallback renderer used by `<Query />` when no specialized component matches the query kind: it shows the raw JSON response in a Monaco editor.

## Usage

Any `DataNode` kind without a dedicated renderer falls through to this component:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

;<Query
  query={{
    kind: 'EventsQuery',
    select: ['*', 'event', 'person', 'timestamp'],
    after: '-24h',
    limit: 100,
  }}
/>
```

In practice you usually wrap a source query in a `DataTableNode` or `DataVisualizationNode` instead — see those folders.

## Key files

- `dataNodeLogic.ts` — the workhorse kea logic, keyed per query instance (`DataNodeLogicProps`: `key`, `query`, `cachedResults`, `refresh`, `loadPriority`, `modifiers`, `filtersOverride`, `variablesOverride`, ...)
  - `loadData` / `cancelQuery` — fetch and abort, with per-scene concurrency controllers
  - `loadNewData` — poll for newer rows (`EventsQuery` only), highlighting fresh rows via `highlightRows`; auto-polls every `AUTOLOAD_INTERVAL` (30 s) when the auto-load toggle is on
  - `loadNextData` / `nextQuery` / `canLoadNextData` — pagination for events, persons, actors, groups, sessions, and similar list queries
  - `response`, `responseLoading`, `responseError`, `elapsedTime`, `pollResponse` — the values consumers read
  - cached results (`cachedResults` prop) make the logic implicitly read-only
- `dataNodeCollectionLogic.ts` — tracks a set of data nodes (e.g. all tiles on a page) so they can be reloaded together (`reloadAll`) and report aggregate loading state
- `DataNode.tsx` — fallback JSON renderer (Monaco editor + `OpenEditorButton`)

The kea logics are internal to the `<Query />` tag — consumers interact via the `query` / `setQuery` props only and should not bind to `dataNodeLogic` from app code.

## Sub-components

Reusable UI bits that expect a bound `dataNodeLogic` (via `BindLogic`), used by `DataTable` and `DataVisualization`:

- `Reload.tsx` — `Reload` (reload one node) and `ReloadAll` (reload the whole collection)
- `LoadNext.tsx` — "Load more" button and row-count preview text driven by `nextQuery`
- `ElapsedTime.tsx` — query duration display, plus `Timings` for a detailed per-step breakdown
- `DateRange.tsx` — date range picker writing `after` / `before` (or `filters.dateRange` for HogQL) back into the query
- `TestAccountFilters.tsx` — "filter out test accounts" toggle
- `SupportTracesFilters.tsx` — extra filters for `TracesQuery` sources
- `QueryExecutionDetails.tsx` — debug details about the executed query
