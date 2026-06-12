# SessionsNode

Filter controls for `SessionsQuery` sources — the tabular sessions list.
The single component here renders in the `DataTable` toolbar and writes edits back via `setQuery`; data fetching belongs to `dataNodeLogic`.

In the schema, `SessionsQuery` selects session rows with `select` columns and supports session-level `properties`, event-level `eventProperties` (sessions containing matching events), `event`/`actionId` containment filters, `after`/`before`, `orderBy`, and pagination.
See `SessionsQuery` in `src/schema/schema-general.ts`.

## Usage

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

<Query
    query={{
        kind: 'DataTableNode',
        source: {
            kind: 'SessionsQuery',
            select: ['session_id', 'timestamp', 'person', '$entry_current_url'],
            after: '-24h',
            properties: [
                { type: 'session', key: '$entry_utm_source', operator: 'exact', value: ['google'] },
            ],
        },
        showPropertyFilter: true, // -> SessionPropertyFilters
        showEventFilter: true, // -> EventName from ../EventsNode
    }}
    setQuery={(query) => {...}}
/>
```

## Key files

- `SessionPropertyFilters.tsx` — `PropertyFilters` wrapper offering session, event, person, feature flag, cohort, and HogQL expression filter types.
  It presents `query.properties` and `query.eventProperties` as one filter list, then splits edits back: event, feature, and cohort filters go to `eventProperties`, everything else to `properties`.

Related components live in sibling folders: `EventName` and `EventPropertyFilters` (`../EventsNode`) also accept `SessionsQuery`, and the date range, reload, and pagination controls come from `../DataNode`.

There are no kea logics in this folder — the component is controlled purely through `query` / `setQuery` props.
The surrounding table's kea stores are internal to the `<Query />` tag.
