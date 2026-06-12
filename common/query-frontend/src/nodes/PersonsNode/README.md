# PersonsNode

Search, filter, and row-action components for person and actor source queries.
They render in the `DataTable` toolbar when the source is a `PersonsNode` or `ActorsQuery` and write edits back via `setQuery` — data fetching belongs to `dataNodeLogic`.

In the schema, `PersonsNode` is deprecated in favor of `ActorsQuery`, which supports `select` columns, `search`, `properties`, `orderBy`, pagination, and an optional `source` (e.g. `InsightActorsQuery` for insight drill-downs, or a `HogQLQuery`).
The components here accept both kinds.
See `ActorsQuery` and `PersonsNode` in `src/schema/schema-general.ts`.

## Usage

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

<Query
    query={{
        kind: 'DataTableNode',
        source: {
            kind: 'ActorsQuery',
            select: ['person_display_name -- Person', 'id', 'created_at', 'person.$delete'],
            search: '',
            properties: [
                { type: 'person', key: '$browser', operator: 'exact', value: 'Chrome' },
            ],
        },
        showSearch: true, // -> PersonsSearch
        showPropertyFilter: true, // -> PersonPropertyFilters
    }}
    setQuery={(query) => {...}}
/>
```

## Key files

- `PersonsSearch.tsx` — debounced free-text search (via `useDebouncedQuery`) writing `query.search`; placeholder adapts when the actors query targets groups
- `PersonPropertyFilters.tsx` — `PropertyFilters` wrapper writing `query.properties`; for `ActorsQuery` it also offers cohort and HogQL expression filters
- `DeletePersonButton.tsx` — row action that opens the person delete modal and reloads the bound `dataNodeLogic` afterwards (rendered for the `person.$delete` column)

There are no kea logics in this folder; `DeletePersonButton` relies on a `dataNodeLogic` already bound by the surrounding table.
Those logics are internal to the `<Query />` tag — consumers interact via `query` / `setQuery` props only.
