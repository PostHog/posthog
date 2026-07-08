# WidgetCard composition

Follow the Quill `Card` pattern: **thin shell + compound subcomponents composed at the callsite**. `WidgetCard` is chrome only — no header/body props.

| File / export                                         | Role                                                                                                                                                                                                                                                                         |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WidgetCard`                                          | Thin tile shell: decorative resize handles, edit-mode edge overlay, RGL slot. **No product/header/body props**                                                                                                                                                               |
| `WidgetCardHeader` (+ internal title/actions helpers) | Layout router: `simple` vs `dashboard_tile`; exports `widgetCardShouldHideMoreButton`                                                                                                                                                                                        |
| `WidgetCardBody.tsx`                                  | Body slot; locked/error shell states. Also exports `WidgetCardContent`, `WidgetCardBodyMessage`, `WidgetLoadingState`, `WidgetCardBodySkeleton`, **`WidgetCardSharedPlaceholderBody`** (public/shared placeholder)                                                           |
| `WidgetCardContent`                                   | Scrollable column + optional footer (list/table widgets) — from `WidgetCardBody.tsx`                                                                                                                                                                                         |
| `WidgetCardBodyMessage`                               | Empty / inline status text — from `WidgetCardBody.tsx`                                                                                                                                                                                                                       |
| `WidgetLoadingState` / `WidgetCardBodySkeleton`       | Widget-owned loading UI — from `WidgetCardBody.tsx`                                                                                                                                                                                                                          |
| `DashboardWidgetItem`                                 | Production callsite — composes header + body, wires ⋯ menu, edit modal portal, product RBAC lock; mounts registry **`TileFilters`** when `hasProductAccess` (hidden on RBAC denial); **public** placement uses `WidgetCardSharedPlaceholderBody` instead of live widget body |

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

**Public / shared dashboard** — same header, but body is placeholder-only (no `run_widgets` data):

```tsx
{showSharedPlaceholder ? (
    <WidgetCardSharedPlaceholderBody
        copy={headerCatalogEntry.sharedPlaceholder ?? DEFAULT_SHARED_DASHBOARD_WIDGET_PLACEHOLDER}
    />
) : (
    <WidgetCardBody locked={locked} error={error} …>
        <WidgetComponent … />
    </WidgetCardBody>
)}
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
- Default header layout is `dashboard_tile` via `getDashboardWidgetCatalogEntry()` — only set `headerLayout` / `headerMeta` on a catalog entry when overriding defaults
- Edit title/description in the widget settings modal only (`EditWidgetModalTileDetailsSection`) — card header is read-only display

## Don't

- Add header/body props back to `WidgetCard` — that defeats the compound pattern
- Put loading placeholders in `WidgetCard` shell — breaks resize/empty-state behavior
- Put widget body content in `gridChildren` — RGL owns that slot for resize handles only
- Duplicate headers, menus, card chrome, or filter toggles inside the widget component — limit/sort/test accounts in edit modal; date/status/property filters on tile bar (not ⋯ menu)
- Register in `registry.tsx` without a matching `DASHBOARD_WIDGET_CATALOG` entry

## Header layouts (`catalog.ts`)

| Layout           | Behavior                                                                               |
| ---------------- | -------------------------------------------------------------------------------------- |
| `simple`         | Single title row — prefer `dashboard_tile` for new types. Refresh via tile ⋯ menu only |
| `dashboard_tile` | Compact `CardMeta` style: type • date range + title + divider; Refresh in ⋯ menu       |

Date range display is derived in `WidgetCardHeader` from `config.dateRange` + resolved catalog `headerMeta` (via `dateFilterToText`). Product type chip text comes from `getDashboardWidgetGroupLabel(groupId)`.

## Loading ownership

The widget `Component` receives `loading` from scene logic and must early-return with `WidgetLoadingState`. The shell (`DashboardWidgetItem` → composed `WidgetCardBody`) does not show skeletons for widget body content.

## RGL and overflow

- Widget content lives inside composed `WidgetCardBody`
- `gridChildren` is reserved for react-grid-layout resize handles only
- Wide tables: horizontal scroll **inside** `WidgetCardContent`, not the dashboard grid

## Product visual parity

When the widget surfaces data from an **existing PostHog product** (variant in an existing `groupId`, or first widget in a product area that already has a scene):

**Default:** Reuse the same presentation the product scene uses — list rows, cards, empty copy, skeletons, setup prompts. A dashboard tile is a smaller viewport; users should still recognize it as the same product data they see in-app (e.g. `ErrorTrackingIssueList` on `/error-tracking`, not a bespoke widget-only table). **Chart-primary bodies do not belong in widgets** — use insight tiles ([architecture.md § Charts → insight tiles](architecture.md#charts--use-insight-tiles-not-widgets)).

### Where to look

Intake should already have run [repo discovery](widget-intake.md#discover-product-ui-in-the-repo) — use those component paths first.

1. Start from intake **product UI reference** when the engineer named a scene path, tab, Storybook story, or sibling widget — do not guess a different screen.
2. Otherwise open the primary scene for that product (list, overview, or detail index).
3. Note which components render the main data block — often under `products/<product>/frontend/components/` or `scenes/<area>/`.
4. Import those into `products/dashboards/frontend/widgets/<product>/` and compose inside `WidgetCardContent` (or the product's setup gate wrapper).

Shipped reference: `ErrorTrackingWidget` imports `ErrorTrackingIssueList`, `ErrorTrackingIssueListSkeleton`, and `ErrorTrackingIngestionPrompt` from `products/error_tracking/frontend/`.

### Platform vs product chrome

| Layer                                                | Owner                                        |
| ---------------------------------------------------- | -------------------------------------------- |
| Tile header, ⋯ menu, resize, edit modal shell        | Dashboard (`WidgetCard`, `EditWidgetModal*`) |
| Rows, empty states, loading skeletons, setup prompts | Product (import shared components)           |

Do not duplicate product menus, filters, or page-level chrome inside the widget body — config belongs in the widget settings modal ([layout-and-ux.md](layout-and-ux.md)).

### Charts

**Out of scope for widgets.** Time series, funnels, and other graph visualizations belong on **insight tiles**, not a new `widget_type`. Do not embed product chart components as the primary widget body.

### Storybook and review

Populated stories should render through the **same product components** with realistic `run_*` payloads so visual review catches drift from the scene. Compare side-by-side with the product Storybook story or scene when unsure.

### When parity is not feasible

Say so in the PR (e.g. scene is full-page with inline filters and no extracted list). Prefer a thin extract into the product package over a one-off dashboard-only presentation — keeps the next widget variant consistent too.

## Storybook

Platform primitives under **Dashboards/Dashboard Widgets/**:

- `WidgetCard/` — `WidgetCard.stories.tsx` (header + body composition patterns)
- `Overview/` — `DashboardWidgetsOverview.stories.tsx` (all catalog types)

Shared frame/mocks: `widgetCardStoryFixtures.tsx`.

Per-type stories: `widgets/<product>/<Component>.stories.tsx` under **Widget types/<Group label>/<label>/** (e.g. `Error tracking/Top issues`).

- Meta `title` must be a **string literal** matching `DASHBOARD_WIDGET_GROUP_LABELS[groupId]` / `label` (CSF rejects dynamic titles)
- Compose with `WidgetCard` + `WidgetCardHeader` + `WidgetCardBody` + catalog header metadata — see `ErrorTrackingWidget.stories.tsx`
- Product setup state: Kea seed helpers live in `widgetCardStoryFixtures.tsx` (`withErrorTrackingProjectState`, etc.) — do not export decorators from `*.stories.tsx` (Storybook treats exports as stories)
- Frozen dates: spread `widgetStorybookParameters` in story `parameters` and align fixture timestamps in `widgetOverviewStoryFixtures.ts` to `WIDGET_STORYBOOK_MOCK_DATE` so TZLabel / relative copy stays stable in visual review
- Stack decorators carefully: story-level `withErrorTrackingProjectState(false)` must not be overridden by a meta decorator that seeds `true`

## Unknown / deploy-skew widget types

When the FE catalog lacks a `widget_type` (partial deploy, unrebased stack):

- **Header** — `tryGetDashboardWidgetCatalogEntry` + `getUnknownDashboardWidgetCatalogFallback` so title and ⋯ menu (remove, duplicate, copy/move) still work
- **Body** — `ErrorBoundary` wraps `DashboardWidgetItemBody`, which calls `getDashboardWidgetCatalogEntry` (throws → full error UI)
- **Fetch errors** — do not pass `run_widgets` fetch `error` into `WidgetCardBody` for unknown types; no Refresh data action in ⋯ menu
- **Analytics** — `getDashboardWidgetDefinition` still dedupes a PostHog `captureException` per canonical type — add the registry entry

## Widget settings modal

`LemonModal` + sections per `Edit*WidgetModal` — no shared wrapper. Copy `EditErrorTrackingWidgetModal.tsx`.

| Path                                                       | Role                                                                                                |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `EditWidgetModalTileDetailsSection.tsx`                    | Tile name/description                                                                               |
| `EditWidgetModalFiltersSubsection.tsx`                     | Test accounts + limit/sort under product `h5`                                                       |
| `editWidgetModalBuilders.ts`                               | Shared kea actions; `buildWidgetTileMetadataPatch` — spread actions only, inline reducers per logic |
| `edit*WidgetModalLogic.ts`                                 | Validate + save listener                                                                            |
| `widgetConfigValidation.ts` + `*WidgetConfigValidation.ts` | Zod; registry **`parseConfigApiError`**                                                             |
| `widgetFilters.ts`                                         | `widgetFilters` persist/HogQL; edit setups; tile persist/restore hooks                              |
| `widgetFiltersUi.tsx`                                      | Filter chips (edit flow)                                                                            |
| `widgetTileFiltersReadOnly.tsx`                            | `WidgetTileFiltersBar` + read-only labels                                                           |
| `*WidgetTileFilters.tsx`                                   | Registry **`TileFilters`** — always-visible bar                                                     |
| `constants.ts`                                             | Fetch error copy, `WIDGET_TILE_REFRESH_DEBOUNCE_MS`, `formatWidgetListCountFooter`                  |

```tsx
<LemonModal … footer={/* Cancel + Save with saveDisabledReason / saving */}>
  <div className="flex flex-col gap-4">
    {showTileDetails ? (
      <EditWidgetModalTileDetailsSection
        tileName={tileName}
        tileDescription={tileDescription}
        defaultTitle={defaultTitle}
        saving={saving}
        setTileName={setTileName}
        setTileDescription={setTileDescription}
      />
    ) : null}
    {showTypeSettings ? (
      <>
        {showTileDetails ? <LemonDivider className="my-0" /> : null}
        <section className="flex flex-col gap-3">
          <h5 className="text-sm font-semibold m-0">
            {getDashboardWidgetGroupLabel('error_tracking')}
          </h5>
          <div className="flex flex-col gap-4">
            <EditWidgetModalFiltersSubsection title="Issue filters" …>
              <TestAccountFilter … />
              {/* limit, sort — property/date/status filters are on the tile bar, not here */}
            </EditWidgetModalFiltersSubsection>
            <div>{/* Sorting subsection */}</div>
          </div>
        </section>
      </>
    ) : null}
  </div>
</LemonModal>
```

References: `EditErrorTrackingWidgetModal.tsx`, `EditSessionReplayWidgetModal.tsx`. Omit sections you do not need — gate with booleans like `showTileDetails` / product-specific setup flags.

Filterable **list widgets:** tile filter bar, pagination footer, `titleHref` — [list-widget-patterns.md](list-widget-patterns.md).

### Kea edit-modal logic

- Spread **actions** from `editWidgetModalBuilders.ts` (`widgetEditModalListFieldActions`, `widgetEditModalTileActions`, `widgetEditModalFilterTestAccountsActions`)
- **Inline reducers** in each logic file — do not spread `widgetEditModal*Reducers` (kea typegen loses reducer types)
- Inline `setFieldErrors`, `clearFieldError`, `activeFieldErrors`, and `saveDisabledReason` with the per-type `*FieldErrors` type
- `setOrderBy` action accepts `string`; reducer casts to the config enum type
- `submit` listener: `validate*WidgetConfigInput` → `onSave(config, buildWidgetTileMetadataPatch(...))` — one PATCH for config + name + description
- Connect `filterTestAccountsDefaultsLogic` and initialize `filterTestAccounts` via `resolveWidgetFilterTestAccounts`

### Config validation

- Per-type persisted config + modal form schema from `generated/widget-configs.zod.ts`; colocated `*WidgetConfigValidation.ts` for API error parsing only (reuse `widgets/widgetConfigValidation.ts` for shared HogQL helpers — no hand-rolled field guards)
- Register **`parseConfigApiError`** on the `DASHBOARD_WIDGET_REGISTRY` entry (dispatched via `parseDashboardWidgetConfigApiError` in `registry.tsx` → `updateDashboardWidgetTile` in `utils.ts`). Config/codegen: [config-and-codegen.md](config-and-codegen.md).
