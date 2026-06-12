# Query frontend source

See the [package README](../README.md) for the overview, usage, and codegen pipeline.

- `Query/`
  - Generic component that routes internally to the right node.
  - `<Query query={} setQuery={} />`
- `QueryEditor/`
  - Generic JSON editor
  - `<QueryEditor query={} setQuery={} />`
- `nodes/`
  - One folder per query node `kind` (`TrendsQuery/`, `FunnelsQuery/`, `DataTable/`, `InsightViz/`, etc.) containing the React components and kea logics that display queries of that kind.
  - The top level component is named after the folder, e.g. `DataTable.tsx` exports `DataTable({ query, setQuery })`.
  - There are various sub-components as needed, e.g. `<AutoLoad />`, `<ColumnConfigurator />`. Some of them depend on a logic, likely `dataNodeLogic`, being in a `BindLogic` context, so read the source.
  - Each folder has a `README.md` documenting the query kind and an example query.
- `persons-modal/` - drill-down modal showing the actors behind a data point
- `shared/` - helpers shared across node kinds (e.g. `mathsLogic`)
- `examples.ts` - Various examples used in storybook
- `query.ts` - make API calls to fetch data for any query
- `schema.json` - JSON schema, used for query editor, built with `pnpm -w schema:build`
- `schema/` - typescript types for all query nodes
- `utils.ts` - type narrowing utilities
