# @posthog/query-frontend

The frontend for PostHog's query system, extracted from `frontend/src/queries`.
This package owns the `<Query />` tag — the single component that can render any PostHog query node — plus the query schema and the per-kind implementations (trends, funnels, retention, paths, data tables, SQL visualizations, and more).

## Usage

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

// a data table over an events query
<Query
    query={{
        kind: 'DataTableNode',
        source: { kind: 'EventsQuery', select: ['*', 'event', 'person', 'timestamp'] },
    }}
/>

// a trends insight
<Query
    query={{
        kind: 'InsightVizNode',
        source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }] },
    }}
/>
```

`<Query query={} setQuery={} />` routes on `query.kind` to the right node component.
Pass `setQuery` to make the rendered node editable (column configuration, date ranges, filters); omit it for read-only rendering.
See `src/examples.ts` for a catalog of working example queries used in storybook.

## Module resolution

The package is consumed through the `@posthog/query-frontend/*` path alias, which maps to `common/query-frontend/src/*`:

- TypeScript and esbuild: `paths` in the root `tsconfig.json`
- Jest: `moduleNameMapper` in `frontend/jest.config.ts`
- Storybook: `resolve.alias` in `common/storybook/webpack.config.js`

## Layout

| Folder               | Contents                                                                            |
| -------------------- | ----------------------------------------------------------------------------------- |
| `src/Query/`         | The `<Query />` tag itself — routes a query JSON object to the right node component |
| `src/QueryEditor/`   | Generic JSON editor for any query, backed by the JSON schema                        |
| `src/schema/`        | TypeScript source of truth for all query types (`TrendsQuery`, `EventsQuery`, …)    |
| `src/schema.json`    | Generated JSON schema (`pnpm --filter=@posthog/frontend schema:build:json`)         |
| `src/nodes/<Kind>/`  | One folder per query node kind — components, kea logics, and docs for that kind     |
| `src/persons-modal/` | The persons drill-down modal opened from chart data points                          |
| `src/shared/`        | Cross-kind helpers, e.g. `mathsLogic` (the aggregation math taxonomy)               |
| `src/hooks/`         | Shared React hooks for query components                                             |
| `src/query.ts`       | API layer — executes any query node against `/api/environments/:id/query`           |
| `src/utils.ts`       | Type-narrowing utilities (`isTrendsQuery`, `isDataTableNode`, …)                    |

Each node folder has its own `README.md` describing the query kind, an example query, and the components and logics that implement it.

## State management

Kea logics (`dataNodeLogic`, `insightVizDataLogic`, `trendsDataLogic`, …) are an internal concern of the `<Query />` tag.
Consumers interact with the component through `query` / `setQuery` props only — do not bind to this package's logics from app code.
The stores stay separated per node kind; there is no package-global store.

## Schema code generation

`src/schema/*.ts` is the source of truth that generates:

- `src/schema.json` — via `pnpm --filter=@posthog/frontend schema:build:json` (`frontend/bin/build-schema-json.mjs`)
- `src/validators.js` — ajv validators, same script
- `posthog/schema.py` — via `pnpm -w schema:build:python` (`bin/build-schema-python.sh`)
- `src/latest-versions.json` — via `bin/build-schema-latest-versions.py`

Run `hogli build:schema` after changing schema types to rebuild everything.

## Visualization components

Chart surfaces shared across query kinds (line graphs, pie charts, bold numbers, maps, tooltips) live in `@posthog/visualizations` (`common/visualizations`).
This package wires query data into those surfaces; the chart rendering itself has one source of truth there.

## Known coupling

The code was extracted from `frontend/src` by location first; it still imports app-level modules (`lib/*`, `scenes/*`, `~/*` aliases) such as `lib/lemon-ui`, taxonomic filters, and `scenes/insights/insightLogic`.
Untangling those imports so the package stands alone is incremental follow-up work — new code added here should avoid reaching into `frontend/src` whenever possible.
