# Checklist: new dashboard widget type

Work in order. Do not skip backend permission wiring (step 2).

Reference implementation: `products/dashboards/frontend/widgets/error_tracking/`

## 1. Backend registry

Files: `products/dashboards/backend/widgets/<widget_type>.py` + `widget_registry.py`

- [ ] `validate_<type>_config(config) -> dict` in `widgets/<widget_type>.py` — normalize defaults; reject bad input with `DRFValidationError`
- [ ] Merge `merge_base_widget_config_fields(config)` for shared fields (`filterTestAccounts`)
- [ ] `run_<type>_widget(team, config) -> dict` — call the **same** query runner the standalone product uses (no parallel query path); pass `resolve_filter_test_accounts(config)` when the query supports it
- [ ] Register in `WIDGET_REGISTRY` with `required_scopes` (docs only) and `required_product_access` when RBAC-gated (must match catalog `required_product_access`)
- [ ] Add type to `EXPECTED_WIDGET_TYPES` (must equal `WIDGET_REGISTRY.keys()` — enforced in tests)
- [ ] Extend `DashboardWidgetType` (`Literal[...]`) with the new canonical `widget_type` string
- [ ] Extend `DashboardWidgetTypeInput` only if the API accepts alternate type aliases for that widget (see `WIDGET_TYPE_ALIASES`)
- [ ] Pass through time-scoped fields (`dateRange`) when the query is date-filtered — use `validate_widget_date_range` from `widgets/config.py`

See [architecture.md](architecture.md) for registry entry shape.

## 2. Backend `run_widgets` permissions — critical

`run_widgets` and widget tile mutations call `get_widget_product_access_error(registry_entry, user_access_control)` from `widget_access.py`.

- [ ] Set `required_product_access` on the `WIDGET_REGISTRY` entry — **do not** add per-type `if widget_type == …` checks in `dashboard.py`
- [ ] Add a friendly denial message to `PRODUCT_ACCESS_DENIED_MESSAGES` in `widget_access.py` only when the generic fallback copy is not good enough — do not pre-populate messages for unshipped types
- [ ] **`required_scopes` is documentation only** — RBAC is driven by `required_product_access`
- [ ] Return per-tile `{ tile_id, error }` — do not fail the whole request for one bad tile
- [ ] Catch query exceptions → per-tile error in response (see existing `dashboard_run_widgets_failed` logging)

## 3. Backend catalog

File: `products/dashboards/backend/widget_catalog.py`

- [ ] Add entry to `WIDGET_CATALOG` with `group_id`, `group_label`, `label`, `description`, `config_schema_hints`, `required_product_access`
- [ ] Keeps REST/MCP catalog in sync with frontend defaults; agents call `dashboard-widget-catalog-list` / `GET .../widget_catalog/`

## 4. Frontend catalog + config schema

- [ ] `widget_types/configSchemas.ts` — extend `baseWidgetConfigSchema` for shared fields (`filterTestAccounts`); use `.parse()` for `defaultConfig`
- [ ] `widget_types/catalog.ts` — add entry to `DASHBOARD_WIDGET_CATALOG` (catalog key = `widget_type`):
  - **`groupId`, `groupLabel`** — required; product area for add-modal grouping. Multiple catalog keys share one group (e.g. `error_tracking_list` and a future variant both use `groupId: 'error_tracking'`, `groupLabel: 'Error tracking'`)
  - **`label`, `description`** — required; variant name within the group (e.g. "Top issues", "Trend chart")
  - `defaultLayout` (`w`, `h`, `minW`, `minH`)
  - `headerLayout`: prefer `'dashboard_tile'` for new widgets (insight-tile parity)
  - Optional: `headerMeta`, `headerTitle`, `titleHref`, `productAccess`
  - Optional: `availability` — simple team-flag prerequisite for `WidgetRuntimeAvailabilityGuard` (omit when the widget handles richer setup gating inline). Gate at **tile render** only (never in add modal). See [availability-and-gating.md](availability-and-gating.md).
- [ ] `widgets/<product>/<type>WidgetConfigValidation.ts` — map Zod errors to edit-modal fields; export API error parser for `utils.ts`

No change to `AddWidgetModal` grouping for normal adds — `getDashboardWidgetCatalogGroups()` derives groups from catalog entries automatically.

### 4b. Adding a variant to an existing group

Use when the product area already has a widget and you need another visualization (e.g. a chart alongside a list widget in the same group).

- [ ] New **unique** catalog key / `widget_type` (e.g. `error_tracking_trends`) — not a config fork of the existing type
- [ ] Reuse sibling **`groupId` and `groupLabel`** exactly
- [ ] Distinct **`label`**, **`description`**, **`defaultConfig`**, **`defaultLayout`** (and usually `headerTitle`)
- [ ] Full backend stack: new `widgets/<widget_type>.py`, `WIDGET_REGISTRY` entry with `required_product_access`, `EXPECTED_WIDGET_TYPES`, extend `DashboardWidgetType`
- [ ] Full frontend stack: new component (same `widgets/<product>/` dir), edit modal, preview in `widgetPreviews.tsx`, registry entry in `registry.tsx`, extend `DashboardWidgetProductAccess` + `userHasWidgetProductAccess` case when RBAC-gated
- [ ] Tests: assert shared `groupId` in `registry.test.tsx` like existing ET variants

## 5. Frontend widget component

Directory: `products/dashboards/frontend/widgets/<product>/` (snake_case product area — e.g. `error_tracking/` for `error_tracking_list`)

- [ ] Implement `Component` with `DashboardWidgetComponentProps` (`tileId`, `config`, `result`, `loading`, `error`, `onRefresh`, `onUpdateConfig`)
- [ ] Setup gating: catalog `availability` for simple team-flag checks, or private setup gate inside the widget `Component` for richer rules — do not modify product `SetupPrompt`
- [ ] **Own loading UI** — early-return with `WidgetLoadingState` (typed skeleton as `children` when helpful)
- [ ] Use `WidgetCardContent` for scrollable lists/tables; `WidgetCardBodyMessage` for empty states
- [ ] Do **not** render card chrome — `DashboardWidgetItem` + catalog handle headers/menus

Minimal skeleton:

```tsx
export function YourWidget({ result, loading, config }: DashboardWidgetComponentProps): JSX.Element {
    if (loading) {
        return (
            <WidgetLoadingState>
                <YourTypedSkeleton />
            </WidgetLoadingState>
        )
    }
    const rows = (result as YourResult)?.results ?? []
    if (rows.length === 0) {
        return <WidgetCardBodyMessage>No data found.</WidgetCardBodyMessage>
    }
    return (
        <WidgetCardContent>
            <YourList data={rows} />
        </WidgetCardContent>
    )
}
```

See [composition.md](composition.md) for WidgetCard rules.

## 5b. Storybook

File: `products/dashboards/frontend/widgets/<product>/<YourWidget>.stories.tsx`

Reference: `products/dashboards/frontend/widgets/error_tracking/ErrorTrackingWidget.stories.tsx`

- [ ] Storybook meta: **string literal** `title: 'Dashboards/Dashboard Widgets/Widget types/<groupLabel>/<label>'` (must match catalog — CSF rejects function calls), `layout: 'padded'`, `WidgetTileFrame` decorator (see `ErrorTrackingWidget.stories.tsx`; platform primitives in `WidgetCard.stories.tsx`)
- [ ] Compose stories with `WidgetCard` + `WidgetCardHeader` + `WidgetCardBody` + catalog header metadata — not the bare widget component
- [ ] Export Kea seed decorators from the primary `*.stories.tsx` when multiple story files need them — no separate `*StoryDecorators.tsx` until shared across products
- [ ] Mock `DashboardWidgetComponentProps` via `args` — no Kea, no `run_widgets` fetch
- [ ] Export stories for each visual state the tile can show:
  - **Populated** — realistic `result` payload (shape matches `run_*` output)
  - **Loading** — `loading: true`, `result: null`
  - **Empty** — `loading: false`, empty `result` (e.g. `{ results: [] }`)
  - **Error** — when the component renders `error` (pass a string or error-shaped prop your component expects)
- [ ] Include `tileId`, `config` (defaults from catalog), and stub `onUpdateConfig` / `onRefresh` where the component needs them

Run locally:

```sh
pnpm storybook
```

Repo rule: presentational widget components belong in Storybook (see `.cursor/rules/react-typescript.mdc`).

## 6. Edit modal + add-widget preview

- [ ] `EditModal` — Zod validate → `LemonField` errors; disable save while `saving` / invalid
- [ ] Compose `WidgetSettingsModalSections` + `WidgetSettingsModalSection` (+ `WidgetSettingsModalDivider` between sections): **Tile details** (`name`, `description`), **Filters** (`TestAccountFilter` when query honors `filterTestAccounts`), type-specific section titled with `groupLabel`
- [ ] Date-filtered widgets: date range select from `WIDGET_DATE_RANGE_SELECT_OPTIONS` in `widgetDateRangeOptions.ts` (`-1h`, `-3h`, `-24h`, `-7d`, …)
- [ ] Wire `parseWidgetConfigApiError` in `frontend/utils.ts` when inline tile config updates should surface field errors
- [ ] Preview in `widgets/previews/`; register in `widgetPreviews.tsx` for `AddWidgetModal`

## 7. Frontend registry

File: `products/dashboards/frontend/widgets/registry.tsx`

```typescript
import { EditYourWidgetModal } from './your_product/EditYourWidgetModal'
import { YourWidget } from './your_product/YourWidget'

export const DASHBOARD_WIDGET_REGISTRY = {
    your_type: {
        Component: YourWidget,
        EditModal: EditYourWidgetModal,
        productAccess: 'your_product',
    },
} satisfies Record<DashboardWidgetCatalogKey, DashboardWidgetDefinition>
```

- [ ] When RBAC-gated: set `productAccess` on the registry entry (must match catalog), extend `DashboardWidgetProductAccess` in `types.ts`, and add a `case` to `userHasWidgetProductAccess` in `DashboardWidgetItem.tsx`

## 8. Tests

Backend:

```sh
hogli test products/dashboards/backend/api/test/test_dashboard_widgets.py
hogli test products/dashboards/backend/api/test/test_run_widgets.py
hogli test products/dashboards/backend/api/test/test_widget_access.py
```

Frontend:

```sh
hogli test products/dashboards/frontend/widgets/registry.test.tsx
hogli test products/dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem.test.tsx
hogli test products/dashboards/frontend/widgets/<product>/
hogli test products/dashboards/frontend/components/WidgetCard/
pnpm storybook   # manual: loading / empty / error (if applicable) / populated stories
```

- [ ] Assert `EXPECTED_WIDGET_TYPES == WIDGET_REGISTRY.keys()`
- [ ] `registry.test.tsx`: every catalog key registered; unknown types report once via `registry.tsx`
- [ ] Test create/update config validation, activity logging, permission denial in `run_widgets`
- [ ] Registry test: component, edit modal, catalog defaults, header layout
- [ ] Analytics: first insert fires `dashboard tile added` with `widget_type` on PATCH and POST add paths (`test_dashboard_widgets.py`)
- [ ] No empty test scaffolds — every `.test.tsx` must assert real behavior

## 9. OpenAPI / generated types

After serializer changes in `dashboard.py`:

```sh
hogli build:openapi
```

Regenerates `products/dashboards/frontend/generated/api.ts`, `api.schemas.ts`. Do not edit generated files.

Invoke `improving-drf-endpoints` before editing serializers. Invoke `adopting-generated-api-types` when migrating manual API calls.
