# HogQLQuery

The SQL editor for `HogQLQuery` nodes.
`HogQLQueryEditor` is a Monaco-based editor with HogQL syntax support, live error checking, an AI prompt to draft queries, and "save as view" for the data warehouse.
It edits the query text only — running the query and rendering results is handled by the host node (`DataTable` shows the editor above the table when `showHogQLEditor` is set, `DataVisualization` renders charts from the same source kind).

In the schema, `HogQLQuery` holds the SQL string in `query`, plus optional `filters` (global date range and property filters referenced as `{filters}` in the SQL), `variables` (`{variables.foo}` placeholders), and `values`.
See `HogQLQuery` in `src/schema/schema-general.ts`.

## Usage

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

<Query
    query={{
        kind: 'DataTableNode',
        full: true, // enables the SQL editor, export, reload, ...
        source: {
            kind: 'HogQLQuery',
            query: `select event, count()
                    from events
                    where {filters}
                    group by event
                    order by count() desc`,
            filters: { dateRange: { date_from: '-24h' } },
        },
    }}
    setQuery={(query) => {...}}
/>
```

The editor can also be used standalone:

```tsx
import { HogQLQueryEditor } from '@posthog/query-frontend/nodes/HogQLQuery/HogQLQueryEditor'

;<HogQLQueryEditor query={hogQLQuery} setQuery={setHogQLQuery} />
```

## Key files

- `HogQLQueryEditor.tsx` — the editor component (`query`, `setQuery`, `onChange`, `embedded`, `editorFooter` props); wires Monaco, error display, the AI prompt input, and the update/save-as-view buttons
- `hogQLQueryEditorLogic.tsx` — kea logic per editor instance: draft query input (`queryInput`, `setQueryInput`), `saveQuery`, AI drafting (`setPrompt`, `draftFromPrompt`, `draftFromMetadataFix`), and `saveAsView` / `onUpdateView` for warehouse views

Syntax validation comes from the shared `codeEditorLogic` (`lib/monaco`), which queries HogQL metadata as you type.

The kea logic is internal to the editor — consumers interact via `query` / `setQuery` (or `onChange` for uncontrolled text updates) only.
