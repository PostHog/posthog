# FacetSearchBar

A search input for lists that turns `facet:value` into removable pills.
People type `status:open`, pick from suggestions, or paste a whole query.
`-status:closed` excludes a value, and `owner:"Jo Doe"` quotes one with spaces.
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
A value shows a count only when you give one.
Send `toFacetQuery(search)` to your API: `{ text, facets: { status: { include: ['open'], exclude: [] } } }`.

```tsx
const facets: ServerFacet[] = [
    { key: 'plan', label: 'Plan', description: 'Billing plan', values: [{ value: 'free', label: 'Free' }] },
    { key: 'team', label: 'Team', description: 'Owning team', loadValues: (search) => api.teams.search(search) },
]

<FacetSearchBar facets={facets} value={search} onChange={setSearch} placeholder="Search accounts" dataAttr="accounts-search" />
```

Loads are debounced and cached per facet and search text. A failed load says so and runs again on the next keystroke.
A pill shows the label of a value once a load has returned it. Until then it shows `formatValue(value)`, so give `formatValue` when a raw value is not readable.

## Keeping the search in the URL

`serializeFacetSearch(search)` writes the pills and the text as one string, such as `status:open -label:bug export`.
`parseFacetSearch(query, facets)` reads it back. Unknown facets stay in the text.

## Keyboard

- ↑ and ↓ move through the suggestions. Enter picks the highlighted one.
- Tab and → pick the first facet or value, never the plain search. On an empty input, Tab moves focus as usual.
- Backspace on an empty input removes the last pill. Esc closes the suggestions.
