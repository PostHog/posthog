# Checklist: new dashboard widget type

**Audience:** PostHog engineers shipping a type that does not exist yet.

1. Complete [widget-intake.md](widget-intake.md) — infer, batched questions, **spec confirmation** (mandatory).
2. Work **§1 → §8 below in order**. Do not skip step 2 (permissions).
3. **§5b, §9, §10** — after MVP tests green.

Default **implementation template:** mirror `products/dashboards/frontend/widgets/error_tracking/` (`error_tracking_list`). Use `session_replay_list` / `widgets/session_replay/` when replay throttles, availability, or session RBAC apply.

## 1. Backend registry

Files: `products/dashboards/backend/widgets/<widget_type>.py` + `widget_registry.py`

- [ ] `validate_<type>_config(config) -> dict` in `widgets/<widget_type>.py` — normalize defaults; reject bad input with `DRFValidationError`
- [ ] Merge `merge_base_widget_config_fields(config)` for shared fields (`filterTestAccounts`)
- [ ] `run_<type>_widget(team, config) -> dict` — call the **same** query runner the standalone product uses (no parallel query path); pass `resolve_filter_test_accounts(config)` when the query supports it
- [ ] Register in `WIDGET_REGISTRY` with `required_scopes` (docs only) and `required_product_access` when RBAC-gated (must match catalog `productAccess`)
- [ ] Add type to `EXPECTED_WIDGET_TYPES` and `frontend/widget_types/expectedWidgetTypes.ts` (must equal `WIDGET_REGISTRY.keys()` — enforced in tests)
- [ ] Extend `DashboardWidgetType` (`Literal[...]`) with the new canonical `widget_type` string
- [ ] Use `DEFAULT_WIDGET_LIST_LIMIT` from `backend/constants.py` unless this type needs a different default
- [ ] Pass through time-scoped fields (`dateRange`) when the query is date-filtered — use `validate_widget_date_range` from `widgets/config.py`
- [ ] List widgets with `orderDirection`: mirror `z.enum(['ASC', 'DESC'])` from existing list schemas in `configSchemas.ts`
- [ ] Throttled product listings (session replay): wire the same throttle checks in `run_widgets` that the standalone API uses

See [architecture.md](architecture.md) for registry entry shape.

## 2. Backend `run_widgets` permissions — critical

Follow [permissions-and-sharing.md § Product RBAC](permissions-and-sharing.md#product-rbac). Checklist:

- [ ] Set `required_product_access` on the `WIDGET_REGISTRY` entry when RBAC-gated (must match catalog `productAccess`)
- [ ] Optional friendly denial in `PRODUCT_ACCESS_DENIED_MESSAGES` / catalog `product_access_denied_message`
- [ ] Return per-tile `{ tile_id, error }` — do not fail the whole request for one bad tile
- [ ] Catch query exceptions → per-tile error in response (see existing `dashboard_run_widgets_failed` logging)

## 3. Backend catalog (agents + REST)

File: `products/dashboards/backend/widget_catalog.py`

- [ ] Add entry to `WIDGET_CATALOG` with `group_id`, `group_label`, `label`, `description`, `config_schema_hints`, `required_product_access`
- [ ] **`config_schema_hints`** — structured hints for MCP/agents (mirror validate defaults). Per field: `type`, optional `min`/`max`, `choices`, `default`, `optional`, nested objects (e.g. `dateRange.date_from` with `choices` from `WIDGET_DATE_FROM_VALUES`). See `error_tracking_list` / `session_replay_list` entries in `widget_catalog.py`.
- [ ] **`availability_requirements`** — string ids for agent catalog (e.g. `["session_replay_enabled"]`). Set even when FE omits catalog `availability` and uses inline setup gating in the widget `Component` (ET still sets `["exception_autocapture"]` on BE).
- [ ] **`product_access_denied_message`** (optional) — friendly RBAC copy for catalog/MCP when generic fallback is not enough
- [ ] Keeps REST/MCP catalog in sync with frontend defaults; agents call `dashboard-widget-catalog-list` / `GET .../widget_catalog/`

## 4. Frontend catalog + config schema

- [ ] `widget_types/configSchemas.ts` — per-type Zod schema extending `baseWidgetConfigSchema`; list widgets also export a form schema via `widgetListFormSchema(orderBySchema)` (or extend shared list fields)
- [ ] `widget_types/catalog.ts` — add entry to `DASHBOARD_WIDGET_CATALOG` (catalog key = `widget_type`):
  - **`groupId`** — required; product area for add-modal grouping. Add label to `DASHBOARD_WIDGET_GROUP_LABELS` when introducing a new group
  - **`label`, `description`** — required; variant name within the group (e.g. "Top issues", "Recent recordings")
  - `defaultLayout` (`w`, `h`, `minW`, `minH`)
  - Do **not** set `headerLayout` / `headerMeta` unless overriding defaults — `getDashboardWidgetCatalogEntry()` resolves `dashboard_tile` + default meta
  - Optional: `headerTitle`, `titleHref`, `productAccess`, **`sharedPlaceholder`** (public/shared dashboard body copy when `run_widgets` is not loaded)
  - Optional: `availability` — simple team-flag prerequisite for `WidgetRuntimeAvailabilityGuard` (omit when the widget handles richer setup gating inline). Gate at **tile render** only (never in add modal). See [availability-and-gating.md](availability-and-gating.md).
- [ ] `widgets/<product>/<type>WidgetConfigValidation.ts` — thin wrapper around shared helpers in `widgets/widgetConfigValidation.ts` (no hand-rolled typeof guards for config fields)

No change to `AddWidgetModal` grouping for normal adds — `getDashboardWidgetCatalogGroups()` derives groups from catalog entries automatically.

### 4b. Adding a variant to an existing group

Use when the product area already has a widget and you need another **list/table/card** presentation in the same group — not a chart ([architecture.md § Charts → insight tiles](architecture.md#charts--use-insight-tiles-not-widgets)).

- [ ] Confirmed the ask is **not** chart-primary — trends/graphs → insight tile on the dashboard
- [ ] New **unique** catalog key / `widget_type` (e.g. `error_tracking_top_issues`) — not a config fork of the existing type
- [ ] Reuse sibling **`groupId`** exactly; label comes from `DASHBOARD_WIDGET_GROUP_LABELS[groupId]`
- [ ] Distinct **`label`**, **`description`**, **`defaultConfig`**, **`defaultLayout`** (and usually `headerTitle`)
- [ ] Full backend stack: new `widgets/<widget_type>.py`, `WIDGET_REGISTRY` entry with `required_product_access`, `EXPECTED_WIDGET_TYPES`, extend `DashboardWidgetType`
- [ ] Full frontend stack: new component (same `widgets/<product>/` dir), edit modal + kea logic, preview in `widgets/previews/` + `DASHBOARD_WIDGET_PREVIEWS` in `catalog.ts`, registry entry in `registry.tsx`, extend `DashboardWidgetProductAccess` + `WIDGET_PRODUCT_ACCESS_CHECKS` in `widgetProductAccess.ts` when RBAC-gated
- [ ] Tests: assert shared `groupId` in `registry.test.tsx` like existing ET variants

### 4c. First widget in a new product area

Use when introducing a new **`groupId`**, not just another variant in an existing group.

- [ ] Add **`groupId`** to `DASHBOARD_WIDGET_GROUP_LABELS` in `catalog.ts`; matching **`group_id`** / **`group_label`** in BE `WIDGET_CATALOG`
- [ ] Storybook title path: `'Dashboards/Dashboard Widgets/Widget types/<groupLabel>/<label>'`
- [ ] **UI + query reuse** — pick one pattern (do not fork query paths):

| Pattern                 | Backend `run_*`                                           | Frontend UI                                             | Shipped example       |
| ----------------------- | --------------------------------------------------------- | ------------------------------------------------------- | --------------------- |
| Product module          | Import query runner from `products/<product>/backend/…`   | Import list/UI from `products/<product>/frontend/…`     | `error_tracking_list` |
| Scenes / posthog helper | Import shared helper (e.g. `posthog.session_recordings…`) | Import from `scenes/<area>/…` when UI still lives there | `session_replay_list` |

- [ ] If importing **`products/<product>/frontend/…`**: add **`products.<product>`** to `tach.toml` → `products.dashboards` `depends_on`
- [ ] **Product visual parity** — tile body uses the same list/card/empty/skeleton/setup components as the product scene where they exist; see [composition.md § Product visual parity](composition.md#product-visual-parity)
- [ ] RBAC: extend `DashboardWidgetProductAccess`, `WIDGET_PRODUCT_ACCESS_CHECKS`, BE `required_product_access` (+ optional `PRODUCT_ACCESS_DENIED_MESSAGES` / catalog `product_access_denied_message`)
- [ ] Availability: new `WidgetAvailabilityRequirementId` in `widgetAvailability.ts` + BE `availability_requirements` string when catalog uses `availability`; optional branch in `WidgetAvailabilitySetupPrompt`
- [ ] Optional **`titleHref`** on catalog — product scene route for header "View" link (`urls.*` or scene path)
- [ ] Net-new product: see [`products/README.md`](../../../products/README.md) for product bootstrap before wiring the widget

## 5. Frontend widget component

Directory: `products/dashboards/frontend/widgets/<product>/` (snake_case product area — e.g. `error_tracking/` for `error_tracking_list`)

- [ ] Implement `Component` with `DashboardWidgetComponentProps` (`tileId`, `config`, `result`, `loading`, `error`, `onRefresh`, `onUpdateConfig`)
- [ ] Setup gating: catalog `availability` for simple team-flag checks, or private setup gate inside the widget `Component` for richer rules — do not modify product `SetupPrompt`
- [ ] **Own loading UI** — early-return with `WidgetLoadingState` (typed skeleton as `children` when helpful); prefer the **product's** skeleton component (e.g. `ErrorTrackingIssueListSkeleton`), not a generic placeholder
- [ ] **Product visual parity** — import list/card/empty/setup UI from the product scene ([composition.md § Product visual parity](composition.md#product-visual-parity)); avoid dashboard-only row markup when shared components exist
- [ ] Use `WidgetCardContent` for scrollable lists/tables; `WidgetCardBodyMessage` for empty states only when the product has no shared empty component
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
- [ ] Kea seed decorators: add helpers to `widgetCardStoryFixtures.tsx` — **do not** export decorators from `*.stories.tsx` (Storybook treats exports as stories). See [composition.md § Storybook](composition.md#storybook)
- [ ] Mock `DashboardWidgetComponentProps` via `args` — no Kea, no `run_widgets` fetch
- [ ] Export stories for each visual state the tile can show:
  - **Populated** — realistic `result` payload (shape matches `run_*` output)
  - **Loading** — `loading: true`, `result: null`
  - **Empty** — `loading: false`, empty `result` (e.g. `{ results: [] }`)
  - **Error** — when the component renders `error` (pass a string or error-shaped prop your component expects)
- [ ] Include `tileId`, `config` (defaults from catalog), and stub `onUpdateConfig` / `onRefresh` where the component needs them
- [ ] Add **`getWidgetOverviewDemoState`** case in `components/WidgetCard/widgetOverviewStoryFixtures.ts` (exhaustive switch — overview story breaks if missing)
- [ ] Optional: `Edit*WidgetModal.stories.tsx` — mirror `EditErrorTrackingWidgetModal.stories.tsx` / `EditSessionReplayWidgetModal.stories.tsx`

Run locally:

```sh
pnpm storybook
```

Repo rule: presentational widget components belong in Storybook (see `.cursor/rules/react-typescript.mdc`).

## 6. Edit modal + add-widget preview

- [ ] `EditModal` + `edit*WidgetModalLogic.ts` — Zod validate → `LemonField` errors; disable save while `saving` / invalid
- [ ] Compose `EditWidgetModalTileDetailsSection`, `EditWidgetModalFiltersSection`, and a type-specific `<section>` titled with `getDashboardWidgetGroupLabel(groupId)` — separate with `LemonDivider`; see [composition.md](composition.md)
- [ ] Spread shared kea **actions** from `editWidgetModalBuilders.ts`; **inline reducers** (typegen breaks on spread); inline typed `fieldErrors` / `activeFieldErrors` / `saveDisabledReason`
- [ ] Date-filtered widgets: date range select from `WIDGET_DATE_RANGE_SELECT_OPTIONS` in `configSchemas.ts`
- [ ] Wire per-type API error parsing: export `parse*WidgetConfigApiError` from `*WidgetConfigValidation.ts` and set **`parseConfigApiError`** on the `DASHBOARD_WIDGET_REGISTRY` entry (`parseDashboardWidgetConfigApiError` in `registry.tsx` → `updateDashboardWidgetTile`)
- [ ] Preview: component in `widgets/previews/`; register in `DASHBOARD_WIDGET_PREVIEWS` in `widget_types/catalog.ts` (reuse sample data from `widgetOverviewStoryFixtures.ts` when possible)

## 7. Frontend registry

File: `products/dashboards/frontend/widgets/registry.tsx` — entry shape in [architecture.md § Frontend registry entry shape](architecture.md#frontend-registry-entry-shape).

- [ ] Import `Component`, `EditModal`, and `parse*WidgetConfigApiError`; one keyed entry per `widget_type`
- [ ] When RBAC-gated: set `productAccess` on catalog + registry entry (must match backend `required_product_access`), extend `DashboardWidgetProductAccess` in `types.ts`, and add a matching entry in `WIDGET_PRODUCT_ACCESS_CHECKS` (`widgetProductAccess.ts`)
- [ ] Set **`sharedPlaceholder`** on the catalog entry when public/shared copy should differ from `DEFAULT_SHARED_DASHBOARD_WIDGET_PLACEHOLDER`

## 8. Tests

Run [SKILL.md § Verify](../SKILL.md#verify). Minimum for a new type:

- [ ] Assert `EXPECTED_WIDGET_TYPES == WIDGET_REGISTRY.keys()`
- [ ] `registry.test.tsx`: every catalog key registered; each entry has **`parseConfigApiError`**
- [ ] Test create/update config validation, activity logging, permission denial in `run_widgets`
- [ ] MCP: `services/mcp/tests/tools/dashboards.integration.test.ts` when catalog/OpenAPI surfaces change
- [ ] Analytics: first insert fires `dashboard tile added` and `dashboard widget added` with `widget_type` on PATCH and POST add paths (`test_dashboard_widgets.py`)
- [ ] No empty test scaffolds — every `.test.tsx` must assert real behavior

## 9. OpenAPI / generated types

Runtime validation stays in `validate_*_config`. OpenAPI/MCP schemas are separate.

### 9a. Dashboard serializers (`dashboard.py`)

After tile/widget serializer field changes:

```sh
hogli build:openapi
```

### 9b. Polymorphic widget config (`widget_openapi_serializers.py`)

When adding or changing config fields agents should see:

- [ ] Add or extend `*WidgetConfigSerializer` in `products/dashboards/backend/api/widget_openapi_serializers.py`
- [ ] Register it on `_DashboardWidgetConfigOpenApi` (`PolymorphicProxySerializer`)
- [ ] Run `hogli build:openapi` — regenerates `products/dashboards/frontend/generated/api.ts`, `api.schemas.ts` and MCP tool schemas. Do not edit generated files.

Invoke `improving-drf-endpoints` before editing serializers. Invoke `adopting-generated-api-types` when migrating manual API calls. Invoke `implementing-mcp-tools` when MCP snapshots or `tools.yaml` help text must list the new type.

## 10. Agent skill docs

Follow [skill-maintenance.md](skill-maintenance.md) when agent-facing behavior or contributor workflow changes — same PR as code.

- [ ] Update mapped reference docs from the change → doc table in `skill-maintenance.md`
- [ ] Run registry sync tests below
