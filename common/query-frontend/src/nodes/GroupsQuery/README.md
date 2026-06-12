# GroupsQuery

Search and filter controls for `GroupsQuery` sources — the tabular list of group analytics groups (organizations, accounts, ...).
The components render in the `DataTable` toolbar and write edits back via `setQuery`; data fetching belongs to `dataNodeLogic`.

In the schema, `GroupsQuery` requires a `group_type_index` (which group type to list) and supports `select` columns, free-text `search`, group-scoped `properties`, `orderBy`, and pagination.
See `GroupsQuery` in `src/schema/schema-general.ts`.

## Usage

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

<Query
    query={{
        kind: 'DataTableNode',
        source: {
            kind: 'GroupsQuery',
            group_type_index: 0,
            select: ['group_name', 'key', 'created_at'],
            search: '',
        },
        showSearch: true, // -> GroupsSearch
        showPropertyFilter: true, // -> GroupPropertyFilters
    }}
    setQuery={(query) => {...}}
/>
```

## Key files

- `GroupsSearch.tsx` — debounced search input (via `useDebouncedQuery` from `@posthog/query-frontend/hooks/useDebouncedQuery`) writing `query.search`; matches by group name or identifier
- `GroupPropertyFilters.tsx` — `PropertyFilters` wrapper writing `query.properties`; scopes the taxonomic filter to the query's `group_type_index` and also offers HogQL expression filters

There are no kea logics in this folder — the components are controlled purely through `query` / `setQuery` props.
The surrounding table's kea stores (`dataTableLogic`, `dataNodeLogic`) are internal to the `<Query />` tag.
