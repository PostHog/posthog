# DataTable

Renders a `DataTableNode` — a table around any tabular source query (`EventsQuery`, `ActorsQuery`, `PersonsNode`, `GroupsQuery`, `HogQLQuery`, `SessionsQuery`, `TracesQuery`, web analytics tables, ...).
The node wraps a `source` query with view options: which columns to show, and which toolbar features to enable (filters, search, export, reload, column configurator, saved filters, table views).
Data fetching is delegated to `dataNodeLogic` (see `../DataNode`); this folder owns column rendering and the table chrome.

## Usage

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

<Query
    query={{
        kind: 'DataTableNode',
        source: {
            kind: 'EventsQuery',
            select: ['*', 'event', 'person', 'timestamp'],
            after: '-24h',
            limit: 100,
        },
        showExport: true,
        showReload: true,
        showColumnConfigurator: true,
        showEventFilter: true,
        showPropertyFilter: true,
    }}
    setQuery={(query) => {...}} // omit for read-only
/>
```

`full: true` enables most options at once.
See `DataTable.examples.ts` and `src/examples.ts` for more working examples, and `DataTableNode` in `src/schema/schema-general.ts` for every `show*` flag plus `columns`, `hiddenColumns`, and `pinnedColumns`.

## Key files and logics

- `DataTable.tsx` — the component: assembles the toolbar from the source query's features and renders a `LemonTable`
- `dataTableLogic.ts` — per-table state: columns in the query, expanded rows, derived `sourceFeatures`
- `dataTableSavedFiltersLogic.ts` — saved filters, persisted in `localStorage` per team and `uniqueKey` (requires `showSavedFilters` and a `uniqueKey`)
- `queryFeatures.ts` — `getQueryFeatures(source)` maps each source kind to its supported features (date range picker, property filters, column configurator, pagination, ...), which decides what UI the table shows
- `renderColumn.tsx` / `renderColumnMeta.tsx` — cell and header rendering, including HogQLX values and date-time formatting
- `defaultEventsQuery.ts`, `utils.ts` — default columns and column expression helpers (`extractExpressionComment`, ...)
- `insightActorsQueryOptionsLogic.ts` — options (day/series/breakdown selectors) when the source is an `InsightActorsQuery`
- `exportTransformers.ts`, `clipboardUtils.ts` — export and copy helpers

The kea logics are internal to the `<Query />` tag — consumers interact via the `query` / `setQuery` props only.

## Sub-components

- `ColumnConfigurator/` — modal for adding, removing, and reordering columns (writes back into `query.columns` / `source.select`)
- `TableView/` — named table views selector (`showTableViews`)
- `DataTableExport.tsx` — export menu (CSV, XLSX, ...)
- `DataTableCount.tsx` — total / filtered row counts (`showCount`)
- `DataTableSavedFilters.tsx` + `DataTableSavedFiltersButton.tsx` — saved filters UI
- `SavedQueries.tsx` — preset event queries (`showSavedQueries`)
- `EventRowActions.tsx` — per-row kebab menu for events (`showActions`)
- `InsightActorsQueryOptions.tsx` — series/interval pickers for insight actor drill-downs
- `BackToSource.tsx`, `DataTableOpenEditor.tsx`, `DataTableViewReplays.tsx` — navigation helpers
- Toolbar filters come from sibling folders: `EventsNode/`, `PersonsNode/`, `SessionsNode/`, `GroupsQuery/`, `HogQLQuery/`, and `DataNode/` (date range, reload, load next, test accounts)
