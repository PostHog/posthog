# Checklist: new dashboard widget type

**Audience:** PostHog engineers shipping a type that does not exist yet.

1. Complete [widget-intake.md](widget-intake.md) — infer, batched questions, **spec confirmation** (mandatory).
2. Work **§1 → §8 below in order**. Do not skip step 2 (permissions).
3. **§5b** (dedicated stories — required before the PR, not a follow-up) once MVP tests are green; **skill docs** per [skill-maintenance.md](skill-maintenance.md) if workflow changed.

Copy spine: [widget-intake.md § Defaults](widget-intake.md#defaults-and-inference).

## 1. Backend config contract + registry

Files: `products/dashboards/backend/widget_specs/` + `widgets/<widget_type>.py`

- [ ] **`widget_specs/configs.py`** — new `*WidgetConfig` Pydantic model + `*_WIDGET_TYPE` constant; extend shared fields via `common.py` when appropriate
- [ ] **`widgets/<widget_type>.py`** — `run_<type>_widget` calling `validate_widget_config(TYPE, config)` then the **same** product query runner (no parallel query path); pass `resolve_filter_test_accounts(config, team)` when supported
- [ ] **`widget_specs/registry.py`** — add one `WidgetSpec` to `_load_widget_specs()` (lazy-import `run_*`): `config_model`, scopes, `group_id`/`group_label`/`label`/`description`, `required_product_access`, `product_access_denied_message`, `availability_requirements`
- [ ] `EXPECTED_WIDGET_TYPES`, OpenAPI polymorphic serializers, and Zod codegen inputs update automatically from `WIDGET_SPECS` + `configs.py` — enforced in `test_run_widgets.py`
- [ ] Use `DEFAULT_WIDGET_LIST_LIMIT` from `backend/constants.py` unless this type needs a different default
- [ ] List widgets with `orderDirection`: use `WidgetOrderDirection` literal in Pydantic (`ASC` / `DESC`)
- [ ] Throttles: `get_dashboard_widget_query_throttle_error` in `run_widgets` (`widget_query_throttle.py`); plus product listing throttles when applicable (replay)

See [architecture.md](architecture.md) for registry entry shape.

## 2. Backend `run_widgets` permissions — critical

Follow [permissions-and-sharing.md § Product RBAC](permissions-and-sharing.md#product-rbac). Checklist:

- [ ] Set `required_product_access` on the `WidgetSpec` in `registry.py` when RBAC-gated (must match FE catalog `productAccess`)
- [ ] Optional friendly denial in `PRODUCT_ACCESS_DENIED_MESSAGES` / catalog `product_access_denied_message`
- [ ] Return per-tile `{ tile_id, error }` — do not fail the whole request for one bad tile
- [ ] Catch query exceptions → per-tile error in response (see existing `dashboard_run_widgets_failed` logging)

## 3. Backend catalog (agents + REST)

Derived from `WIDGET_SPECS` — no hand-maintained `WIDGET_CATALOG` dict.

- [ ] `WidgetSpec` catalog fields in **`registry.py`** are enough for BE catalog — `widget_catalog.py` exposes `config_schema` via `config_model.model_json_schema()`
- [ ] **`availability_requirements`** on `WidgetSpec` — string ids for agent catalog (e.g. `session_replay_enabled`). Set even when FE omits catalog `availability` and uses inline setup gating in the widget `Component`
- [ ] **`product_access_denied_message`** on `WidgetSpec` when generic fallback is not enough
- [ ] Agents read **`config_schema`** (typed OpenAPI per `widget_type`) via `dashboard-widget-catalog-list` / `GET .../widget_catalog/`

## 4. Frontend catalog + config schema + codegen

Apply locked values from intake [defaults](widget-intake.md#defaults-and-inference) and [spec recap](widget-intake.md#spec-fields-to-lock) — do not re-infer `groupId`, layout, RBAC, or list UX here.

Runtime validation = Pydantic in `widget_specs/`. OpenAPI components derive from `model_json_schema()` via `pydantic_openapi.py` — do not hand-write parallel DRF config serializers or FE Zod.

- [ ] Name the Pydantic config model `*ListWidgetConfig` (or `*WidgetConfig`) so `generate-widget-config-zod.mjs` auto-derives friendly Zod re-exports
- [ ] Run **`hogli build:openapi`** after §1 and **commit** `products/dashboards/frontend/generated/*` (CI `check-openapi-types` — [config-and-codegen.md § Codegen & CI](config-and-codegen.md#codegen--ci)). Regenerates (do not edit by hand):
  - `frontend/generated/api.schemas.ts` — TS types incl. polymorphic `DashboardWidgetConfigApi`
  - `products/dashboards/frontend/generated/widget-config-schemas/*.zod.ts` — per-component Orval Zod (`generateReusableSchemas`)
  - `products/dashboards/frontend/generated/widget-configs.zod.ts` — friendly re-exports, inferred types, form `.pick()` schemas (**import this**, not raw Orval component names)
  - `products/dashboards/frontend/generated/widget-config-property-keys.json` — per-type config property keys (`generate-widget-config-zod.mjs`)
  - `products/dashboards/frontend/generated/widget-date-from-options.json` — date preset values + labels (`build-dashboard-widget-types.py`)
  - `products/dashboards/frontend/generated/widget-form-fields.json` — modal field manifest from `WidgetSpec.form_fields`
  - MCP tool schemas (`services/mcp/...`)
- [ ] If `build:openapi-schema` warns on `widget_type` enum collision: `python manage.py find_enum_collisions` → add `{YourWidgetTypeEnum: ["your_widget_type"]}` to `ENUM_NAME_OVERRIDES` in `posthog/settings/web.py` (see [config-and-codegen.md § Codegen & CI](config-and-codegen.md#codegen--ci))
- [ ] Add `form_fields` on the `WidgetSpec` row in `registry.py` (drives generated `*WidgetFormSchema`)
- [ ] `widgets/<product>/<type>WidgetConfigValidation.ts` — import generated form schema; export `parse*WidgetConfigApiError` for registry `parseConfigApiError`
- [ ] `widget_types/catalog.ts` — add entry to `DASHBOARD_WIDGET_CATALOG` (catalog key = `widget_type`):
  - **`groupId`** — required; product area for add-modal grouping. Add label to `DASHBOARD_WIDGET_GROUP_LABELS` when introducing a new group
  - **`label`, `description`** — required; variant name within the group (e.g. "Top issues", "Recent recordings")
  - `defaultLayout` (`w`, `h`, `minW`, `minH`)
  - Do **not** set `headerLayout` / `headerMeta` unless overriding defaults — `getDashboardWidgetCatalogEntry()` resolves `dashboard_tile` + default meta
  - Optional: `headerTitle`, `titleHref`, `productAccess`, **`sharedPlaceholder`** (public/shared dashboard body copy when `run_widgets` is not loaded)
  - Optional: `availability` — simple team-flag prerequisite for `WidgetRuntimeAvailabilityGuard` (omit when the widget handles richer setup gating inline). Gate at **tile render** only (never in add modal). See [availability-and-gating.md](availability-and-gating.md).

Invoke `improving-drf-endpoints` before editing dashboard `@extend_schema`. Invoke `implementing-mcp-tools` when MCP snapshots or `tools.yaml` help text must list the new type.

No change to `AddWidgetModal` grouping for normal adds — `getDashboardWidgetCatalogGroups()` derives groups from catalog entries automatically.

### 4b. Adding a variant to an existing group

Use when the product area already has a widget and you need another visualization (e.g. a chart alongside a list widget in the same group).

- [ ] New **unique** catalog key / `widget_type` (e.g. `error_tracking_trends`) — not a config fork of the existing type
- [ ] Reuse sibling **`groupId`** exactly; label comes from `DASHBOARD_WIDGET_GROUP_LABELS[groupId]`
- [ ] Distinct **`label`**, **`description`**, **`defaultConfig`**, **`defaultLayout`** (and usually `headerTitle`)
- [ ] Full backend stack: new `widget_specs/configs.py` model, `widgets/<widget_type>.py`, `registry.py` `WidgetSpec` entry
- [ ] Full frontend stack: new component (same `widgets/<product>/` dir), edit modal + kea logic, preview in `widgets/previews/` + `DASHBOARD_WIDGET_PREVIEWS` in `catalog.ts`, registry entry in `registry.tsx`, extend `DashboardWidgetProductAccess` + `WIDGET_PRODUCT_ACCESS_CHECKS` in `widgetProductAccess.ts` when RBAC-gated
- [ ] Tests: assert shared `groupId` in `registry.test.tsx` like existing ET variants

### 4c. First widget in a new product area

Use when introducing a new **`groupId`**, not just another variant in an existing group.

- [ ] Add **`groupId`** to `DASHBOARD_WIDGET_GROUP_LABELS` in `catalog.ts`; matching `group_id`/`group_label` on BE **`WidgetSpec`**
- [ ] Add the product's icon to **`DASHBOARD_WIDGET_GROUP_ICONS`** in `catalog.ts` (use the canonical product icon from `defaultTree.tsx` `iconTypes`) — shown next to the group heading in the Add widget picker
- [ ] Storybook title path: `'Dashboards/Dashboard Widgets/Widget types/<groupLabel>/<label>'`
- [ ] **UI + query reuse** — pick one pattern (do not fork query paths):

| Pattern                 | Backend `run_*`                                           | Frontend UI                                             | Shipped example       |
| ----------------------- | --------------------------------------------------------- | ------------------------------------------------------- | --------------------- |
| Product module          | Import query runner from `products/<product>/backend/…`   | Import list/UI from `products/<product>/frontend/…`     | `error_tracking_list` |
| Scenes / posthog helper | Import shared helper (e.g. `posthog.session_recordings…`) | Import from `scenes/<area>/…` when UI still lives there | `session_replay_list` |

- [ ] If importing **`products/<product>/frontend/…`**: add **`products.<product>`** to `tach.toml` → `products.dashboards` `depends_on`
- [ ] RBAC: extend `DashboardWidgetProductAccess`, `WIDGET_PRODUCT_ACCESS_CHECKS`, BE `WidgetSpec.required_product_access` (+ optional `product_access_denied_message`)
- [ ] Availability: new `WidgetAvailabilityRequirementId` in `widgetAvailability.ts` + BE `WidgetSpec.availability_requirements` when catalog uses `availability`; optional branch in `WidgetAvailabilitySetupPrompt`
- [ ] Optional **`titleHref`** on catalog — product scene route for header "View" link (`urls.*` or scene path)
- [ ] Optional **`DASHBOARD_WIDGET_GROUP_PRODUCT_INTRO`** entry in `catalog.ts` (`{ productKey, requirement, valueProp, ctaLabel, docsHref }`) — surfaces a group-level nudge in the Add widget picker (value-prop one-liner + explore CTA). The `requirement` (a `WidgetAvailabilityRequirementId`) gates it directly: shown only while that requirement is unmet, so it's only meaningful for products that gate on a project setting (skip for areas with no requirement, e.g. `experiments`, `activity`)
- [ ] Net-new product: see [`products/README.md`](../../../products/README.md) for product bootstrap before wiring the widget

## 5. Frontend widget component

Directory: `products/dashboards/frontend/widgets/<product>/` (snake_case product area — e.g. `error_tracking/` for `error_tracking_list`)

- [ ] Implement `Component` with `DashboardWidgetComponentProps` (`tileId`, `config`, `result`, `loading`, `error`, `onRefresh`, `onUpdateConfig`)
- [ ] Setup gating: catalog `availability` for simple team-flag checks, or private setup gate inside the widget `Component` for richer rules — do not modify product `SetupPrompt`
- [ ] **Own loading UI** — early-return with `WidgetLoadingState` (typed skeleton as `children` when helpful)
- [ ] Use `WidgetCardContent` for scrollable lists/tables; `WidgetCardBodyMessage` for empty states
- [ ] **List widgets:** follow [list-widget-patterns.md](list-widget-patterns.md) — `hasMore`, footer, tile filter bar, `titleHref`
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

**Required, not optional.** Every new `widget_type` ships a dedicated `<YourWidget>.stories.tsx` — plus an `Edit*WidgetModal.stories.tsx` when it has an edit modal — matching the sibling pattern (error tracking, session replay, activity each have both). The catalog overview story (`getWidgetOverviewDemoState`) is **not** a substitute: it renders a single demo state per type and covers none of the per-widget states, tile-filter read-only, loading, empty, or the edit modal. A PR that adds a widget without dedicated stories is incomplete.

File: `products/dashboards/frontend/widgets/<product>/<YourWidget>.stories.tsx`

Reference: `products/dashboards/frontend/widgets/error_tracking/ErrorTrackingWidget.stories.tsx`

- [ ] Storybook meta: **string literal** `title: 'Dashboards/Dashboard Widgets/Widget types/<groupLabel>/<label>'` (must match catalog — CSF rejects function calls), `layout: 'padded'`, spread `widgetStorybookParameters` (frozen `mockDate` for VR snapshots), `WidgetTileFrame` decorator (see `ErrorTrackingWidget.stories.tsx`; platform primitives in `WidgetCard.stories.tsx`)
- [ ] Compose stories with `WidgetCard` + `WidgetCardHeader` + `WidgetCardBody` + catalog header metadata — not the bare widget component
- [ ] Kea seed decorators: add helpers to `widgetCardStoryFixtures.tsx` — **do not** export decorators from `*.stories.tsx` (Storybook treats exports as stories). See [composition.md § Storybook](composition.md#storybook)
- [ ] Mock `DashboardWidgetComponentProps` via `args` — no Kea, no `run_widgets` fetch
- [ ] Export stories for each visual state the tile can show:
  - **Populated** — realistic `result` payload (shape matches `run_*` output); include `totalCount` / `totalCountCapped` when `hasMore: true`
  - **TileFiltersReadOnly** (when type has tile filters) — `tileFiltersReadOnly` story arg; mirrors ET/SR stories
  - **Loading** — `loading: true`, `result: null`
  - **Empty** — `loading: false`, empty `result` (e.g. `{ results: [] }`)
  - **Error** — when the component renders `error` (pass a string or error-shaped prop your component expects)
- [ ] Include `tileId`, `config` (defaults from catalog), and stub `onUpdateConfig` / `onRefresh` where the component needs them
- [ ] Add **`getWidgetOverviewDemoState`** case in `components/WidgetCard/widgetOverviewStoryFixtures.ts` (exhaustive switch — overview story breaks if missing)
- [ ] **`Edit*WidgetModal.stories.tsx`** when the type has an edit modal — required, mirror `EditErrorTrackingWidgetModal.stories.tsx` / `EditSessionReplayWidgetModal.stories.tsx`. If the modal (or a tile filter) hits an API (e.g. an experiment picker), mock it with `mswDecorator` from `~/mocks/browser`

Run locally:

```sh
pnpm storybook
```

Repo rule: presentational widget components belong in Storybook (see `.cursor/rules/react-typescript.mdc`).

## 6. Edit modal + add-widget preview

- [ ] `EditModal` + `edit*WidgetModalLogic.ts` — Zod validate → `LemonField` errors; disable save while `saving` / invalid
- [ ] Compose `EditWidgetModalTileDetailsSection`, then a product `<section>` (`getDashboardWidgetGroupLabel`) with `EditWidgetModalFiltersSubsection` (test accounts) + sorting — **do not** put date/status/property filters in the modal if they belong on the tile bar — see [composition.md](composition.md)
- [ ] Spread shared kea **actions** from `editWidgetModalBuilders.ts`; **inline reducers** (typegen breaks on spread); inline typed `fieldErrors` / `activeFieldErrors` / `saveDisabledReason`
- [ ] Date-filtered widgets: date range select from `WIDGET_DATE_RANGE_SELECT_OPTIONS` in `widgetConfigShared.ts`
- [ ] Wire per-type API error parsing: export `parse*WidgetConfigApiError` from `*WidgetConfigValidation.ts` and set **`parseConfigApiError`** on the `DASHBOARD_WIDGET_REGISTRY` entry (`parseDashboardWidgetConfigApiError` in `registry.tsx` → `updateDashboardWidgetTile`)
- [ ] Preview: component in `widgets/previews/`; register in `DASHBOARD_WIDGET_PREVIEWS` in `widget_types/catalog.ts` (reuse sample data from `widgetOverviewStoryFixtures.ts` when possible)

## 7. Frontend registry

File: `products/dashboards/frontend/widgets/registry.tsx` — entry shape in [architecture.md § Frontend registry entry shape](architecture.md#frontend-registry-entry-shape).

- [ ] Import `Component`, `EditModal`, and `parse*WidgetConfigApiError`; one keyed entry per `widget_type`
- [ ] When RBAC-gated: set `productAccess` on catalog + registry entry (must match backend `required_product_access`), extend `DashboardWidgetProductAccess` in `types.ts`, and add a matching entry in `WIDGET_PRODUCT_ACCESS_CHECKS` (`widgetProductAccess.ts`)
- [ ] Set **`sharedPlaceholder`** on the catalog entry when public/shared copy should differ from `DEFAULT_SHARED_DASHBOARD_WIDGET_PLACEHOLDER`

## 8. Tests

Run [SKILL.md §6 Verify](../SKILL.md#6-verify). Minimum for a new type:

- [ ] Assert `EXPECTED_WIDGET_TYPES == WIDGET_REGISTRY.keys()`
- [ ] `registry.test.tsx`: every catalog key registered; each entry has **`parseConfigApiError`**
- [ ] `test_widget_config_schema_parity.py` + `widgetConfigSchemaParity.test.ts` when config fields change
- [ ] `test_widget_openapi_enums.py` when adding a `widget_type` (ENUM_NAME_OVERRIDES)
- [ ] Test create/update config validation, activity logging, permission denial in `run_widgets`
- [ ] MCP: `services/mcp/tests/tools/dashboards.integration.test.ts` when catalog/OpenAPI surfaces change
- [ ] Analytics: first insert fires `dashboard tile added` and `dashboard widget added` with `widget_type` on PATCH and POST add paths (`test_dashboard_widgets.py`)
- [ ] No empty test scaffolds — every `.test.tsx` must assert real behavior
