# Queries

- `nodes/` 
  - The folders in this directory (e.g. `EventsNode/`, `DataTable/`, ...) contain components for rendering each `NodeKind`, and its related components (e.g. the reload button). 
  - The top level component always has the structure `DataTable({ query, setQuery })`
  - There are various sub-components for each node kind (e.g. `<AutoLoad />`, `<ColumnConfigurator />`) that can be used. Some of them depend on a logic, likely `dataNodeLogic`, being in a `BindLogic` context, so read the source.
- `Query/`
  - Generic component that routes internally to the right node. 
  - `<Query query={} setQuery={} />`
- `QueryEditor/`
  - Generic JSON editor 
  - `<QueryEditor query={} setQuery={} />`
- `examples.ts` - Various examples used in storybook
- `query.ts` - fetch data for any query
- `schema.json` - JSON schema, used for query editor
- `schema.ts` - typescript types for all query nodes
- `utils.ts` - type narrowing utilities
