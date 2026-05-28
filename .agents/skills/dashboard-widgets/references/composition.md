# WidgetCard composition

Symptom/fix tables: [pitfalls.md](pitfalls.md).

Follow the Quill `Card` pattern: **thin shell + compound subcomponents composed at the callsite**. `WidgetCard` is chrome only — no header/body props.

| File / export | Role |
| ------------- | ---- |
| `WidgetCard` | Thin tile shell: decorative resize handles, edit-mode edge overlay, RGL slot. **No product/header/body props** |
| `WidgetCardHeader` (+ internal title/actions helpers) | Layout router: `simple` vs `dashboard_tile`; exports `widgetCardShouldHideMoreButton` |
| `WidgetCardBody.tsx` | Body slot; locked/error shell states. Also exports `WidgetCardContent`, `WidgetCardBodyMessage`, `WidgetLoadingState`, `WidgetCardBodySkeleton` |
| `WidgetCardContent` | Scrollable column + optional footer (list/table widgets) — from `WidgetCardBody.tsx` |
| `WidgetCardBodyMessage` | Empty / inline status text — from `WidgetCardBody.tsx` |
| `WidgetLoadingState` / `WidgetCardBodySkeleton` | Widget-owned loading UI — from `WidgetCardBody.tsx` |
| `DashboardWidgetItem` | Production callsite — composes header + body, wires ⋯ menu, edit modal portal, product RBAC lock |

`WidgetCardHeaderDescription` is exported from `WidgetCardHeader.tsx` for tests only. Widget `Component`s never render card chrome — only body content primitives (`WidgetCardContent`, `WidgetCardBodyMessage`, …).

## Compound pattern

```tsx
<WidgetCard
    ref={ref}
    className={className}
    style={style}
    showResizeHandles={showResizeHandles}
    canEnterEditModeFromEdge={canEnterEditModeFromEdge}
    onEnterEditModeFromEdge={onEnterEditModeFromEdge}
    gridChildren={rglHandles} // react-grid-layout injects these
>
    <WidgetCardHeader
        layout={headerLayout}
        title={title}
        defaultTitle={defaultTitle}
        // …catalog-driven header fields
        shouldHideMoreButton={widgetCardShouldHideMoreButton(placement, showEditingControls)}
        moreButtonOverlay={…}
    />
    <WidgetCardBody locked={locked} error={error}>
        <WidgetComponent … />
    </WidgetCardBody>
</WidgetCard>
```

Render order inside `WidgetCard` (matches `InsightCard`):

1. `children` — composed header + body
2. `DashboardResizeHandles` when `showResizeHandles`
3. `EditModeEdgeOverlay` when edge-enter-edit is enabled
4. `gridChildren` — RGL `.react-resizable-handle` nodes

## Do

- Keep `WidgetCard` as the outermost node in `DashboardWidgetItem` — RGL injects `className`/`style` via `ref` on the card root
- Compose `WidgetCardHeader` + `WidgetCardBody` in `DashboardWidgetItem` (or story wrappers) — not inside `WidgetCard`
- Pass RGL handles via `gridChildren`, not `children`
- Let the widget `Component` decide skeleton vs content from `loading` prop
- Use `min-w-0` + `overflow-auto` chain (`WidgetCardContent` already scrolls vertically)
- Store time period in `config.dateRange` — options, edit modal, and header display: [layout-and-ux.md](layout-and-ux.md)
- Prefer `headerLayout: 'dashboard_tile'` — Refresh data as direct ⋯ menu item via `DashboardTileRefreshDataButton` (matches insight tiles; no flyout submenu)
- Edit title/description in the widget settings modal only (`WidgetSettingsModalSections` Tile details) — card header is read-only display

## Don't

- Add header/body props back to `WidgetCard` — that defeats the compound pattern
- Put loading placeholders in `WidgetCard` shell — breaks resize/empty-state behavior
- Put widget body content in `gridChildren` — RGL owns that slot for resize handles only
- Duplicate headers, menus, card chrome, or filter toggles inside the widget component — filters belong in the settings modal, not the ⋯ menu
- Register in `registry.tsx` without a matching `DASHBOARD_WIDGET_CATALOG` entry

## Header layouts (`catalog.ts`)

| Layout | Behavior |
| ------ | -------- |
| `simple` | Single title row — prefer `dashboard_tile` for new types. Refresh via tile ⋯ menu only |
| `dashboard_tile` | Compact `CardMeta` style: type • date range + title + divider; Refresh in ⋯ menu |

Date range display is derived in `WidgetCardHeader` from `config.dateRange` + catalog `headerMeta` (via `dateFilterToText`).

## Loading ownership

The widget `Component` receives `loading` from scene logic and must early-return with `WidgetLoadingState`. The shell (`DashboardWidgetItem` → composed `WidgetCardBody`) does not show skeletons for widget body content.

## RGL and overflow

- Widget content lives inside composed `WidgetCardBody`
- `gridChildren` is reserved for react-grid-layout resize handles only
- Wide tables: horizontal scroll **inside** `WidgetCardContent`, not the dashboard grid

## Storybook

Platform primitives under **Dashboards/Dashboard Widgets/**:

- `WidgetCard/` — `WidgetCard.stories.tsx` (header + body composition patterns)
- `Overview/` — `DashboardWidgetsOverview.stories.tsx` (all catalog types)

Shared frame/mocks: `widgetCardStoryFixtures.tsx`.

Per-type stories: `widgets/<product>/<Component>.stories.tsx` under **Widget types/<groupLabel>/<label>/**.

- Meta `title` must be a **string literal** derived from catalog `groupLabel` / `label` (CSF rejects dynamic titles)
- Compose with `WidgetCard` + `WidgetCardHeader` + `WidgetCardBody` + catalog header metadata — see `ErrorTrackingWidget.stories.tsx`
- Product setup state: Kea seed helpers live in `errorTrackingWidgetStoryDecorators.tsx` — do not export decorators from `*.stories.tsx` (Storybook treats exports as stories)
- Stack decorators carefully: story-level `withErrorTrackingProjectState(false)` must not be overridden by a meta decorator that seeds `true`

## Widget settings modal

Same compound pattern as `WidgetCard` — thin shell, sections composed in each `Edit*WidgetModal`.

| Export | Role |
| ------ | ---- |
| `WidgetSettingsModalSections` | Outer `flex flex-col gap-4` wrapper only |
| `WidgetSettingsModalSection` | Titled section + 2-column form grid |
| `WidgetSettingsModalDivider` | `LemonDivider` between sections — insert at callsite when needed |
| `WIDGET_SETTINGS_FORM_GRID_CLASS` / `WIDGET_SETTINGS_FIELD_FULL_WIDTH_CLASS` | Grid layout helpers for fields inside a section |

```tsx
<WidgetSettingsModalSections>
    {onSaveMetadata && (
        <WidgetSettingsModalSection title="Tile details">{/* name, description */}</WidgetSettingsModalSection>
    )}
    {showFilters && (
        <>
            {onSaveMetadata && <WidgetSettingsModalDivider />}
            <WidgetSettingsModalSection title="Filters">{/* TestAccountFilter */}</WidgetSettingsModalSection>
        </>
    )}
    {showTypeFields && (
        <>
            {(onSaveMetadata || showFilters) && <WidgetSettingsModalDivider />}
            <WidgetSettingsModalSection title={catalogEntry.groupLabel}>{/* type-specific fields */}</WidgetSettingsModalSection>
        </>
    )}
</WidgetSettingsModalSections>
```

Reference: `EditErrorTrackingWidgetModal.tsx`. Omit sections you do not need — do not pass optional slot props to the shell.
