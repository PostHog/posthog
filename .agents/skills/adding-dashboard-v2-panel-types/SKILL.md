---
name: adding-dashboard-v2-panel-types
description: >
  Guides adding or changing a panel type in dashboards v2 (`products/dashboards_v2/frontend/panels/`):
  the PanelSpec, definePanel, config schema, tile slots (Component, Loading, HeaderExtra, Footer),
  menuActions, allowedCustomizations and lazy loading, with the markdown type as the worked example.
  Use when creating a new kind of tile content for a dashboards v2 host, changing a panel type's config,
  or reviewing a diff under `frontend/panels/`. Not for v1 dashboard widgets (`manage-dashboard-widgets`).
---

# Adding a dashboards v2 panel type

A panel type is the content a tile shows, such as a chart or markdown.
The tile owns the frame: title, description, menu, dragging, resizing and the error boundary.
Read `products/dashboards_v2/.agents/primitives.md` and `.agents/performance.md` first.

## Files

Give the type its own folder, `frontend/panels/<type>/`:

- `<type>Spec.ts` holds the config schema, the `PanelSpec` and the `definePanel` call.
- Each component has its own file, such as `<Type>Panel.tsx`.

The layout functions, `validateDashboard` and tools that write dashboards as code load the spec file, sometimes outside the browser.
So the spec file loads its components with `React.lazy` and never imports one directly.
`panelDefinition.tsx` depends only on React, so keep it that way: UI such as messages and error reporting goes in `PanelView` or the tile.

## Rules

- Define `config` as a `z.strictObject`, and take its TypeScript type from the schema with `z.infer`. `definePanel` checks every saved config against the schema before any part of the type gets it, so the parts never cast `config` and never type it as `unknown`.
- Give the spec its config type and its literal type name: `PanelSpec<MarkdownConfig, 'markdown'>`.
- The `type` and every config field are saved in dashboard documents. Renaming one breaks saved dashboards, so it needs a migration, not a rename.
- A panel type fills only its slots: `Component`, `Loading`, `HeaderExtra`, `Footer` and `menuActions`. Do not draw a title or add an error boundary in a panel.
- Give the type a `Loading` shaped like its content when it has one. Off-screen tiles and suspended tiles show it, so a tile looks like itself before it mounts.
- A type that shows data takes a `sampleData` option in its factory, as `createChartPanel` does. The host sets it while it has no real data, and the type then draws made-up data in `Component` and runs no queries. Mark it as sample data and keep its made-up numbers out of tooltips.
- Components read only the small contexts they need, such as `FiltersContext` and `PanelHostContext`, and never the dashboard state. A component that changes the dashboard's filters or time range reads `FilterControlsContext`.
- `showOnInteractiveOnly(panel)` returning true leaves the tile out of snapshots, such as images and printed pages.
- `movable(panel)` returning false stops a person dragging, resizing, moving or removing the tile. Left out, every tile is movable.
- `keepMounted(panel)` returning true keeps the panel mounted after it scrolls out of view. Use it only for a panel that holds state a person would lose, because the panel then stays in memory.
- To show a product's own component rather than add a type, use `/adding-dashboard-v2-custom-content`.
- `allowedCustomizations` lists the tile customizations the type allows, such as `['backgroundColor']`. The values a person picks are saved on the tile's `panel.appearance`.
- `menuActions(actions, context)` returns the tile's menu. Append entries to `actions` with a stable `key`, and change the config with `context.setConfig`, which saves one undo step.
- Add the type to `DEFAULT_PANELS` only when every host should get it. Otherwise a host passes the type in its own list.
- A pure function in the spec, such as `sizeFor`, gets a unit test.

## Example: markdown

`frontend/panels/markdown/markdownSpec.ts`:

```ts
export const markdownConfigSchema = z.strictObject({ text: z.string() })

export type MarkdownConfig = z.infer<typeof markdownConfigSchema>

export const markdownSpec: PanelSpec<MarkdownConfig, 'markdown'> = {
  type: 'markdown',
  size: { w: 8, h: 8, minW: 3, minH: 4 },
  configSchema: markdownConfigSchema,
  allowedCustomizations: ['backgroundColor'],
}

const MarkdownPanel = lazy(() => import('./MarkdownPanel').then((module) => ({ default: module.MarkdownPanel })))

export const markdownPanel = definePanel({
  ...markdownSpec,
  addTileOptions: [
    { label: 'Text', create: () => ({ type: 'markdown', config: { text: 'Write notes in **Markdown**.' } }) },
  ],
  Component: MarkdownPanel,
})
```

`MarkdownPanel` gets `panel: ContentPanel<MarkdownConfig>`, so `panel.config.text` is a checked string.
A host passes the type in its list, such as `panels={[createChartPanel({ runQuery }), markdownPanel]}`.

The chart type is a factory instead, `createChartPanel`, because a host adds its own kinds of chart and its query runner.
Follow it only when a host must configure the type.

## Before you report done

- `pnpm --filter=@posthog/frontend typescript:check` and the dashboards v2 Jest tests pass.
- The new type renders on the `/dashboard-v2` kitchen sink: its content, its loading state, and the "not valid" message for a broken config.
- Its tile can still be moved, resized and removed when the panel throws.
