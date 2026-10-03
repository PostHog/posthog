# FacetSearchBar

A search input for lists that turns `facet:value` into removable pills.
People type `status:open`, pick from suggestions, or paste a whole query.
A space ends a value, so `owner:"Jo Doe"` quotes one with spaces. `-status:closed` excludes a value.
Pills on one facet are OR, pills on different facets are AND, and the free text is AND with the pills.

You give it three things: the facets, the search state, and the data.
Parsing, suggestions, counts, keyboard navigation and the combobox aria stay inside.

## Client mode: the browser holds the rows

Pass the rows as `data`. Each facet reads its values from a row with `getValues`.
Suggestions show how many rows each value matches.
`filterFacetRows` gives you the rows to show.

```tsx
const facets: ClientFacet<Ticket>[] = [
    { key: 'status', label: 'Status', description: 'Open or closed', showOnFocus: true, getValues: (t) => [t.status] },
    { key: 'label', aliases: ['tag'], label: 'Label', description: 'Any label', getValues: (t) => t.labels },
]
const data: FacetSearchRows<Ticket> = { rows: tickets, matchesText: (t, text) => t.title.includes(text) }

<FacetSearchBar facets={facets} data={data} value={search} onChange={setSearch} placeholder="Search tickets" dataAttr="tickets-search" />
<TicketTable tickets={filterFacetRows(data, search, facets)} />
```

## Server mode: an API filters the rows

Leave out `data`. Each facet lists its `values` up front, or loads them with `loadValues(search)` as the person types after the colon.
A word of two or more characters typed without a facet also calls every `loadValues`, so values from any facet can be picked straight away.
A value shows a count only when you give one.
Send `toFacetQuery(search)` to your API: `{ text, facets: { status: { include: ['open'], exclude: [] } } }`.

```tsx
// Outside the component, so `loadValues` stays the same function between renders.
const facets: ServerFacet[] = [
    { key: 'plan', label: 'Plan', description: 'Billing plan', showOnFocus: true, values: [{ value: 'free', label: 'Free' }] },
    { key: 'team', label: 'Team', description: 'Owning team', loadValues: (search) => api.teams.search(search) },
]

<FacetSearchBar facets={facets} value={search} onChange={setSearch} placeholder="Search accounts" dataAttr="accounts-search" />
```

Loads are debounced and cached per facet and search text.
The bar shows what `loadValues` returns as is, so it can match on fields the label leaves out, such as an email.
A failed load shows the error message and runs again on the next keystroke.
Keep `loadValues` stable between renders: a new function drops the values the old one loaded.
A pill restored from a URL takes its label from `loadValues('')`. If that list can miss the value, give `formatValue` too.
While that load runs, the pill shows the raw value with a spinner. If it fails, the pill keeps the raw value, and its tooltip and screen reader text add "couldn't load the label".

## Keeping the search in the URL

`serializeFacetSearch(search)` writes the pills and the text as one string, such as `status:open -label:bug export`.
`parseFacetSearch(query, facets)` reads it back. Unknown facets stay in the text.

## Keyboard

- ↑ and ↓ move through the suggestions. Enter picks the highlighted one. The search row starts highlighted, so Enter on a typed word runs the search.
- Tab and → pick the first facet or value, never the plain search. Until the person types, Tab moves focus as usual.
- Backspace on an empty input removes the last pill. Esc closes the suggestions.
