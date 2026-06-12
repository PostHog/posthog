# HogQLX

Renders HogQL extension (HogQLX) tags returned in query results.
HogQL lets a query return UI elements — e.g. `select <Sparkline data={[1, 2, 3]} />` — which the backend serializes as nested `['__hx_tag', ...]` arrays.
This folder turns those values back into React elements wherever query results are displayed (most notably `DataTable` cells via `renderColumn`).

This is not a query node kind: there is no `HogQLX` query.
The tags arrive inside the results of any HogQL-powered query.

## Usage

Write the tags directly in SQL and render the query as usual:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

;<Query
  query={{
    kind: 'DataTableNode',
    source: {
      kind: 'HogQLQuery',
      query: `select event, <Sparkline data={[1, 2, 3]} /> as chart from events limit 10`,
    },
  }}
/>
```

Or render a HogQLX value programmatically:

```tsx
import { renderHogQLX } from '@posthog/query-frontend/nodes/HogQLX/render'

renderHogQLX(['__hx_tag', 'a', 'href', 'https://posthog.com', 'children', 'PostHog'])
```

## Key files

- `render.tsx` — everything lives here:
  - `parseHogQLX(value)` — converts the `['__hx_tag', ...]` wire format into plain objects
  - `renderHogQLX(value)` — recursively renders the parsed tree, wrapping each element in an error boundary

## Supported tags

The tag list must stay in sync with the backend allowlist in `posthog/hogql/hogqlx.py`:

- `<Sparkline />` — inline mini chart from numeric data
- `<RecordingButton />` — opens a session recording in a modal (`sessionId`, `recordingStatus`)
- `<ExplainCSPReport />` — AI explanation button for `$csp_violation` event properties
- `<a>` — safe link rendering via `Link` (`href`, `target`, `children`)
- `<blink>`, `<marquee>`, `<redacted>` — styled span effects
- Plain structural HTML tags with no attributes other than `key` and `children`: `em`, `strong`, `span`, `div`, `p`, `pre`, `code`, `h1`–`h6`, `ul`, `ol`, `li`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `blockquote`, `hr`, `b`, `i`, `u`

Objects without a `__hx_tag` render as a collapsible JSON viewer; unknown tags render an "Unknown tag" placeholder.
