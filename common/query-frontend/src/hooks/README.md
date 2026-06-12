# Hooks

Shared React hooks for query node components.
These help components stay controlled purely through `query` / `setQuery` props — the convention across this package, where kea stores are internal to the `<Query />` tag.

## useDebouncedQuery

Debounces a text input that writes into a query object.
Typing updates a local value immediately; the modified query is pushed through `setQuery` only after the timeout (default 300 ms), so every keystroke doesn't trigger a new API request.
A ref to the latest `query` ensures the debounced write doesn't clobber other query changes made while waiting.

```tsx
import { useDebouncedQuery } from '@posthog/query-frontend/hooks/useDebouncedQuery'
import { GroupsQuery } from '@posthog/query-frontend/schema/schema-general'

function GroupsSearch({
  query,
  setQuery,
}: {
  query: GroupsQuery
  setQuery?: (query: GroupsQuery) => void
}): JSX.Element {
  const { value, onChange } = useDebouncedQuery<GroupsQuery, string>(
    query,
    setQuery,
    (query) => query.search || '', // read the value from the query
    (query, value) => ({ ...query, search: value }) // write the value into the query
  )
  return <input value={value} onChange={(e) => onChange(e.target.value)} />
}
```

Signature:

```ts
useDebouncedQuery<T extends Node, V extends string>(
    query: T,
    setQuery: ((query: T) => void) | undefined,
    getValueFromQuery: (query: T) => V,
    getModifiedQuery: (query: T, value: V) => T,
    timeoutMs: number = 300
): { value: V; onChange: (value: V) => void }
```

Used by `PersonsSearch` (`../nodes/PersonsNode`) and `GroupsSearch` (`../nodes/GroupsQuery`).
