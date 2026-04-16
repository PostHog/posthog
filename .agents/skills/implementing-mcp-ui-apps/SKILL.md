---
name: implementing-mcp-ui-apps
description: 'Guide for adding MCP UI apps — interactive visualizations that render tool results in MCP clients like Claude Desktop. Use when adding a new detail or list view for an MCP tool, creating view components in products/*/mcp/apps/, or linking tools to UI apps via YAML.'
---

# Implementing MCP UI apps

MCP UI apps are interactive React visualizations that render alongside tool results
in MCP clients (e.g. Claude Desktop). They're built with the Mosaic component library
and served via Cloudflare Workers Static Assets.

Full reference: [services/mcp/CONTRIBUTING.md](../../../services/mcp/CONTRIBUTING.md).

## Quick workflow

```sh
# 1. Create view components in your product's mcp/apps/ directory
#    (see "View components" below)

# 2. Add ui_apps entries to your product's mcp/tools.yaml
#    (see "YAML configuration" below)

# 3. Link tools to apps with ui_app: <key> in the tools section

# 4. Generate entry points + registry, then build
pnpm --filter=@posthog/mcp run generate:ui-apps
pnpm --filter=@posthog/mcp run build
```

## When to add a UI app

When an MCP tool returns structured data that benefits from visual presentation —
tables, detail views, charts, status badges, etc. Without a UI app, tool results
are shown as plain text/JSON in the chat.

## Architecture

```filesystem
products/{product}/mcp/
  apps/                          # React view components (you write these)
    EntityView.tsx               # Detail view
    EntityListView.tsx           # List view (uses ListDetailView from Mosaic)
    index.ts                     # Barrel exports
  tools.yaml                     # YAML config: ui_apps + tools

services/mcp/
  src/ui-apps/apps/
    generated/                   # Auto-generated entry points (don't edit)
    debug.tsx                    # Custom/manual entry points
    query-results.tsx
  src/resources/
    ui-apps.generated.ts         # Auto-generated: URI constants, UiAppKey, URI_MAP, UI_APPS
    ui-apps.ts                   # Hand-authored: withUiApp(), registerUiAppResources()
  scripts/
    generate-ui-apps.ts          # The generator — reads YAML, writes entry points + registry
    yaml-config-schema.ts        # Zod schemas for YAML validation (source of truth for field definitions)
```

## View components

Place view components in `products/{product}/mcp/apps/`.

**Detail view** — renders a single entity:

```tsx
import { type ReactElement } from 'react'
import { Card, DescriptionList, Stack } from '@posthog/mosaic'

export interface MyEntityData {
  id: number
  name: string
  // ... fields from the API response
}

export function MyEntityView({ data }: { data: MyEntityData }): ReactElement {
  return (
    <Card title={data.name}>
      <DescriptionList items={[{ label: 'ID', value: String(data.id) }]} />
    </Card>
  )
}
```

**List view** — uses `ListDetailView` from Mosaic for the list-to-detail state machine:

```tsx
import { type ReactElement, type ReactNode } from 'react'
import { DataTable, type DataTableColumn, ListDetailView, Stack } from '@posthog/mosaic'
import { MyEntityView, type MyEntityData } from './MyEntityView'

export interface MyEntityListData {
  results: MyEntityData[]
  _posthogUrl?: string
}

export interface MyEntityListViewProps {
  data: MyEntityListData
  onMyEntityClick?: (entity: MyEntityData) => Promise<MyEntityData | null>
}

export function MyEntityListView({ data, onMyEntityClick }: MyEntityListViewProps): ReactElement {
  return (
    <ListDetailView<MyEntityData>
      onItemClick={onMyEntityClick}
      backLabel="All entities"
      getItemName={(e) => e.name}
      renderDetail={(e) => <MyEntityView data={e} />}
      renderList={(handleClick) => {
        const columns: DataTableColumn<MyEntityData>[] = [
          {
            key: 'name',
            header: 'Name',
            sortable: true,
            render: (row): ReactNode =>
              onMyEntityClick ? (
                <button onClick={() => handleClick(row)} className="text-link underline ...">
                  {row.name}
                </button>
              ) : (
                row.name
              ),
          },
        ]
        return (
          <div className="p-4">
            <Stack gap="sm">
              <DataTable columns={columns} data={data.results} pageSize={10} />
            </Stack>
          </div>
        )
      }}
    />
  )
}
```

**Barrel export** (`index.ts`):

```ts
export { MyEntityView, type MyEntityData } from './MyEntityView'
export { MyEntityListView, type MyEntityListData, type MyEntityListViewProps } from './MyEntityListView'
```

## YAML configuration

The `ui_apps` section in `products/{product}/mcp/tools.yaml` defines UI apps.
Each key becomes the app identifier (used in URIs, constants, and `withUiApp` calls).

There are three app types: `detail`, `list`, and `custom`.

### `type: detail` — single-entity view

Renders one entity using a view component wrapped in `AppWrapper`.

**Required fields:**

| Field       | Description                                                                                                                              |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `type`      | Must be `'detail'`.                                                                                                                      |
| `view_prop` | The React prop name passed to the view component (e.g. `data`, `action`, `flag`). Cannot be derived — must match your component's props. |

**Optional fields** (derived by convention when omitted):

| Field              | Default                           | Description                                                                                              |
| ------------------ | --------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `app_name`         | `"PostHog " + titleCase(key)`     | Display name shown in the MCP client. Example: key `error-details` → `"PostHog Error Details"`.          |
| `description`      | `titleCase(key) + " detail view"` | Short description for the MCP resource registry.                                                         |
| `component_import` | `products/{product}/mcp/apps`     | Import path for the view component. Auto-derived from the YAML file's location in the product directory. |
| `data_type`        | `PascalCase(key) + "Data"`        | TypeScript type for the tool result. Example: key `error-details` → `ErrorDetailsData`.                  |
| `view_component`   | `PascalCase(key) + "View"`        | React component name. Example: key `error-details` → `ErrorDetailsView`.                                 |

**Minimal example:**

```yaml
ui_apps:
  action:
    type: detail
    view_prop: action
```

**Example with overrides** (when conventions don't match the actual code):

```yaml
ui_apps:
  llm-costs:
    type: detail
    view_prop: data
    data_type: LLMCostsData # convention would produce LlmCostsData
    view_component: LLMCostsView # convention would produce LlmCostsView
```

### `type: list` — list with drill-down

Renders a list component. When an item is clicked, calls a detail tool via
`app.callServerTool()` and shows the detail view inline. Falls back to a chat
message if the MCP client doesn't support tool calls from apps.

**Required fields:**

| Field         | Description                                                                                                                                                           |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `type`        | Must be `'list'`.                                                                                                                                                     |
| `detail_tool` | Tool name to call when a list item is clicked (e.g. `'action-get'`, `'cohorts-retrieve'`). Must be a valid tool name defined in the `tools` section of any YAML file. |

**Optional fields with behavioral defaults:**

| Field             | Default                                    | Description                                                                                                                                                                                                                                                                    |
| ----------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `detail_args`     | `'{ id: item.id }'`                        | JS expression for arguments passed to `detail_tool`. The variable `item` refers to the clicked list item. Override when the tool uses a different param name, e.g. `'{ flagId: item.id }'`.                                                                                    |
| `item_name_field` | `'name'`                                   | Field on the item object used for display in loading states and fallback chat messages. Override when items are identified by something other than `name`, e.g. `key` for feature flags.                                                                                       |
| `click_prop`      | `'on' + PascalCase(singularKey) + 'Click'` | Prop name for the click handler passed to the list component. The singular key is derived by stripping the `-list` suffix. Example: key `action-list` → `onActionClick`. Override when your component uses a shorter name, e.g. `onFlagClick` instead of `onFeatureFlagClick`. |
| `entity_label`    | kebab-to-space of singular key             | Human-readable label used in the fallback chat message ("Show me the details for {entity_label} ..."). Example: key `error-issue-list` → `error issue`.                                                                                                                        |

**Optional fields with convention defaults** (same pattern as detail apps):

| Field              | Default                                | Description                                                                           |
| ------------------ | -------------------------------------- | ------------------------------------------------------------------------------------- |
| `app_name`         | `"PostHog " + titleCase(key)`          | Display name.                                                                         |
| `description`      | `titleCase(key) + " view"`             | Short description.                                                                    |
| `component_import` | `products/{product}/mcp/apps`          | Import path.                                                                          |
| `list_data_type`   | `PascalCase(singularKey) + "ListData"` | TypeScript type for the list response. Example: key `action-list` → `ActionListData`. |
| `item_data_type`   | `PascalCase(singularKey) + "Data"`     | TypeScript type for a single item. Example: key `action-list` → `ActionData`.         |
| `view_component`   | `PascalCase(key) + "View"`             | React component name. Example: key `action-list` → `ActionListView`.                  |

**Minimal example:**

```yaml
ui_apps:
  action-list:
    type: list
    detail_tool: action-get
```

**Example with overrides:**

```yaml
ui_apps:
  feature-flag-list:
    type: list
    detail_tool: feature-flag-get-definition
    detail_args: '{ flagId: item.id }' # tool expects flagId, not id
    item_name_field: key # flags are identified by key, not name
    click_prop: onFlagClick # component uses onFlagClick, not onFeatureFlagClick
```

### `type: custom` — handwritten entry point

For apps that need fully custom logic (e.g. `debug.tsx`, `query-results.tsx`).
The generator does NOT create an entry point — you maintain it manually at
`services/mcp/src/ui-apps/apps/{key}.tsx`. Only the registry entry is generated.

**Required fields:**

| Field         | Description                                                                                                          |
| ------------- | -------------------------------------------------------------------------------------------------------------------- |
| `type`        | Must be `'custom'`.                                                                                                  |
| `app_name`    | Display name. Required because there's no convention to derive it from (custom apps may not follow naming patterns). |
| `description` | Short description. Required for the same reason.                                                                     |

**Example:**

```yaml
ui_apps:
  query-results:
    type: custom
    app_name: Query Results
    description: Interactive visualization for PostHog query results
```

### Where the schemas live

The Zod schemas that validate these YAML fields live in
[services/mcp/scripts/yaml-config-schema.ts](../../../services/mcp/scripts/yaml-config-schema.ts).
Each field has a JSDoc comment explaining its purpose and default.

To add a new field to an app type:

1. Add it to the relevant Zod schema (`DetailUiAppSchema`, `ListUiAppSchema`, or `CustomUiAppSchema`)
   with `.optional()` if it has a default
2. Add it to the matching `Resolved*` interface (`ResolvedDetailUiApp` or `ResolvedListUiApp`)
3. Add the default derivation in `resolveDetailApp()` or `resolveListApp()` in `generate-ui-apps.ts`
4. Use the resolved value in `generateDetailApp()` or `generateListApp()`

All schemas use `.strict()` — unknown keys are rejected at build time, catching typos.

## Linking tools to UI apps

In the `tools` section of the same YAML file, use `ui_app` to reference a `ui_apps` key:

```yaml
tools:
  my-entity-get:
    operation: my_entities_retrieve
    enabled: true
    ui_app: my-entity # references ui_apps.my-entity
  my-entity-list:
    operation: my_entities_list
    enabled: true
    ui_app: my-entity-list # references ui_apps.my-entity-list
```

The generator validates that every `ui_app` value points to a key that exists
in some `ui_apps` section across all YAML files.

For handwritten tools (not YAML-generated), use `withUiApp` in TypeScript:

```typescript
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

type Result = WithPostHogUrl<MyEntityData>

export default (): ToolBase<typeof schema, Result> =>
  withUiApp('my-entity', {
    name: 'my-entity-get',
    schema,
    handler: async (context, params) => {
      const projectId = await context.stateManager.getProjectId()
      const data = await fetchEntity(context, params)
      return await withPostHogUrl(context, data, `/my-entities/${data.id}`)
    },
  })
```

The `appKey` parameter is type-checked against the generated `UiAppKey` union —
invalid keys are compile-time errors.

## CI validation

CI checks that generated files are up to date in both `ci-mcp.yml` and `ci-mcp-ui-apps.yml`.
If you change YAML `ui_apps` sections, run `pnpm --filter=@posthog/mcp run generate:ui-apps`
and commit the result.
