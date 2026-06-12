# Queries

- `Query/`
  - Generic component that routes internally to the right node.
  - `<Query query={} setQuery={} />`
- `QueryEditor/`
  - Generic JSON editor
  - `<QueryEditor query={} setQuery={} />`
- `nodes/`
  - The folders in this directory (`EventsNode/`, `DataTable/`, etc) contain React components that display queries of that specific `kind`.
  - Basically everything in `nodes/DataTable/` expects your query to be of kind `DataTable`.
  - The top level component, `DataTable.tsx`, always exports the component `DataTable({ query, setQuery })`
  - There are various sub-components as needed, e.g. `<AutoLoad />`, `<ColumnConfigurator />`. Some of them depend on a logic, likely `dataNodeLogic`, being in a `BindLogic` context, so read the source.
- `examples.ts` - Various examples used in storybook
- `query.ts` - make API calls to fetch data for any query
- `schema.json` - JSON schema, used for query editor, built with `pnpm -w schema:build`
- `schema.ts` - typescript types for all query nodes
- `utils.ts` - type narrowing utilities
