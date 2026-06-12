# EventsNode

Filter controls for event-based source queries.
These components render in the `DataTable` toolbar (and other hosts) and write user edits back into the query via `setQuery` — they don't fetch any data themselves.
They accept the event-flavored query kinds: `EventsNode`, `EventsQuery`, `SessionsQuery`, and for property filters also `HogQLQuery`, `SessionAttributionExplorerQuery`, and `TracesQuery`.

In the schema, `EventsNode` is the entity node used inside insight queries (`TrendsQuery.series`, funnel steps, ...) with `event`, `properties`, and math fields, while `EventsQuery` is the tabular events list (`select`, `where`, `orderBy`, `after`/`before`, `limit`).
See both in `src/schema/schema-general.ts`.

## Usage

These components appear when a `DataTableNode` enables the matching flags:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

<Query
    query={{
        kind: 'DataTableNode',
        source: {
            kind: 'EventsQuery',
            select: ['*', 'event', 'person', 'timestamp'],
            properties: [
                { type: 'event', key: '$browser', operator: 'exact', value: ['Chrome'] },
            ],
            event: '$pageview',
        },
        showEventFilter: true, // -> EventName
        showEventsFilter: true, // -> EventsFilter (EventsQuery only)
        showPropertyFilter: true, // -> EventPropertyFilters
    }}
    setQuery={(query) => {...}}
/>
```

Or use them directly:

```tsx
import { EventPropertyFilters } from '@posthog/query-frontend/nodes/EventsNode/EventPropertyFilters'

;<EventPropertyFilters query={eventsQuery} setQuery={setEventsQuery} />
```

## Key files

- `EventName.tsx` — single event picker; writes `query.event` (`null`/empty means all events)
- `EventsFilter.tsx` — multi-event chips with a taxonomic popover; writes `query.events` (`EventsQuery` only)
- `EventPropertyFilters.tsx` — `PropertyFilters` wrapper; knows where each query kind keeps its properties (`query.properties`, `query.eventProperties` for `SessionsQuery`, `query.filters.properties` for `HogQLQuery`) and offers event, person, group, cohort, element, and HogQL expression filter types

There are no kea logics in this folder — the components are controlled purely through `query` / `setQuery` props.
State for the surrounding table lives in `dataTableLogic` / `dataNodeLogic`, which are internal to the `<Query />` tag.
