# Node

Shared UI primitives that work for any query node kind.
These are small buttons used across node components (`DataTable`, `DataNode`, ...) — there is no `Node` query kind rendered from this folder, and no kea logic.

## Key files

- `OpenEditorButton.tsx` — `OpenEditorButton({ query })`: opens the given query as a new insight (`urls.insightNew({ query })`).
  Used by the fallback `DataNode` JSON view and the `DataTable` toolbar so any rendered query can be lifted into a full editing scene.
- `EditHogQLButton.tsx` — `EditHogQLButton({ hogql })`: opens the given SQL string in the SQL editor (`urls.sqlEditor({ query })`).
  Shown for sources that expose their generated HogQL.

Both extend `LemonButtonWithoutSideActionProps`, so any `LemonButton` prop (size, type, tooltip, ...) can be passed through.

## Usage

```tsx
import { EditHogQLButton } from '@posthog/query-frontend/nodes/Node/EditHogQLButton'
import { OpenEditorButton } from '@posthog/query-frontend/nodes/Node/OpenEditorButton'

<OpenEditorButton
    query={{
        kind: 'DataTableNode',
        source: { kind: 'EventsQuery', select: ['*', 'event', 'timestamp'] },
    }}
/>

<EditHogQLButton hogql="select event, count() from events group by event" />
```

These are presentation-only components — they navigate, and never mutate the query they are given.
Query state itself is owned by the `<Query />` tag's internal kea stores, which consumers reach only via `query` / `setQuery` props.
