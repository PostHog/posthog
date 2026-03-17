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
    ui-apps.generated.ts         # Auto-generated: URI constants, UiAppKey, withUiApp, UI_APPS
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

Add `ui_apps` to your product's `mcp/tools.yaml`. Most fields are derived by convention —
you only specify what differs from the defaults.

**Detail app** — only `view_prop` required:

```yaml
ui_apps:
  my-entity:
    type: detail
    view_prop: data # the prop name your view component accepts
```

**List app** — only `detail_tool` required:

```yaml
ui_apps:
  my-entity-list:
    type: list
    detail_tool: my-entity-get # tool called when clicking a list item
```

**Convention defaults** (derived from app key + product directory):

| Field              | Derived from                               | Example (key: `my-entity`)     |
| ------------------ | ------------------------------------------ | ------------------------------ |
| `app_name`         | `"PostHog " + titleCase(key)`              | `PostHog My Entity`            |
| `component_import` | product dir                                | `products/my_product/mcp/apps` |
| `data_type`        | `PascalCase(key) + "Data"`                 | `MyEntityData`                 |
| `view_component`   | `PascalCase(key) + "View"`                 | `MyEntityView`                 |
| `list_data_type`   | `PascalCase(singularKey) + "ListData"`     | `MyEntityListData`             |
| `item_data_type`   | `PascalCase(singularKey) + "Data"`         | `MyEntityData`                 |
| `click_prop`       | `"on" + PascalCase(singularKey) + "Click"` | `onMyEntityClick`              |
| `detail_args`      | `{ id: item.id }`                          |                                |
| `item_name_field`  | `name`                                     |                                |
| `entity_label`     | kebab-to-space of key                      | `my entity`                    |

Override any field when the convention doesn't match:

```yaml
ui_apps:
  feature-flag-list:
    type: list
    detail_tool: feature-flag-get-definition
    detail_args: '{ flagId: item.id }' # param name is flagId, not id
    item_name_field: key # display key, not name
    click_prop: onFlagClick # shorter than onFeatureFlagClick
```

## Linking tools to UI apps

In the `tools` section of the same YAML, use `ui_app` to reference a `ui_apps` key:

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

For handwritten tools (not YAML-generated), use `withUiApp` in TypeScript:

```typescript
import { withUiApp } from '@/resources/ui-apps.generated'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'

type Result = WithPostHogUrl<MyEntityData>

export default (): ToolBase<typeof schema, Result> =>
  withUiApp('my-entity', {
    name: 'my-entity-get',
    schema,
    handler: async (context, params) => {
      const data = await fetchEntity(context, params)
      return await withPostHogUrl(context, data, `/my-entities/${data.id}`)
    },
  })
```

## Custom (manual) UI apps

For apps needing fully custom logic (e.g. `query-results.tsx`):

1. Add `type: custom` in YAML with explicit `app_name` and `description`
2. Create the entry point manually at `services/mcp/src/ui-apps/apps/{key}.tsx`
3. Run `pnpm --filter=@posthog/mcp run generate:ui-apps` to update the registry

## CI validation

CI checks that generated files are up to date. If you change YAML `ui_apps` sections,
run `pnpm --filter=@posthog/mcp run generate:ui-apps` and commit the result.
