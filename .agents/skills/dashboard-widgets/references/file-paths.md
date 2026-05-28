# Dashboard widgets file paths

Open these paths; do not guess locations.

## Naming

| Context | Convention | Example |
| ------- | ---------- | ------- |
| Product widget dirs under `widgets/` | `snake_case` | `widgets/error_tracking/` |
| Catalog keys / `widget_type` / registry keys | `snake_case` | `error_tracking_list` |
| Shared `widget_types/` modules | `snake_case` filenames | `widgetDateRangeOptions.ts` |
| React component dirs under `components/` | `PascalCase` | `WidgetCard/`, `DashboardWidgetItem/` |
| MCP tool names | `kebab-case` | `dashboard-widgets-run` |

Do not scaffold empty `hooks/`, `logic/`, or abandoned component dirs — colocate widget code in `widgets/<product>/` until a kea logic is actually needed.

| Path | Edit when |
| ---- | --------- |
| `products/dashboards/backend/widgets/<widget_type>.py` | Per-type `validate_*` + `run_*` (call standalone product query runners) |
| `products/dashboards/backend/widget_registry.py` | **Aggregator only** — `WIDGET_REGISTRY` keys, `EXPECTED_WIDGET_TYPES`, `DashboardWidgetType` / `DashboardWidgetTypeInput`, `WIDGET_TYPE_ALIASES` |
| `products/dashboards/backend/widget_access.py` | `get_widget_product_access_error`; optional `PRODUCT_ACCESS_DENIED_MESSAGES` entry per shipped gated type (fallback copy is fine until then) |
| `products/dashboards/backend/widgets/config.py` | Shared config: `filterTestAccounts`, `MAX_WIDGET_CONFIG_LIMIT`, `dateRange` validation, merge/resolve helpers |
| `products/dashboards/backend/widget_catalog.py` | Backend catalog entries + config schema hints for MCP/API |
| `products/dashboards/backend/api/dashboard.py` | Generic `run_widgets` loop, `widgets` (single add), `update_widget`, `widget_catalog`, tile CRUD — **no per-type branches** |
| `products/dashboards/backend/api/test/test_dashboard_widgets.py` | Widget CRUD, copy/duplicate, config validation, analytics tests |
| `products/dashboards/backend/api/test/test_run_widgets.py` | `run_widgets` + permission denial tests |
| `products/dashboards/backend/api/test/test_widget_access.py` | `get_widget_product_access_error` unit tests |
| `products/dashboards/mcp/tools.yaml` | MCP tool descriptions for widget endpoints (regenerate MCP after changes) |
| `products/dashboards/frontend/widget_types/configSchemas.ts` | Zod config schema (`baseWidgetConfigSchema` + per-type extend) |
| `products/dashboards/frontend/widget_types/widgetDateRangeOptions.ts` | Allowed `date_from` values + edit-modal select options (`-1h`, `-3h`, `-24h`, …) |
| `products/dashboards/frontend/widgets/WidgetSettingsModalSections.tsx` | Compound edit-modal shell: `WidgetSettingsModalSections`, `WidgetSettingsModalSection`, `WidgetSettingsModalDivider`, grid class constants |
| `products/dashboards/frontend/types.ts` | `DashboardWidgetProductAccess` union — extend when adding RBAC-gated types |
| `products/dashboards/frontend/utils.ts` | `updateDashboardWidgetTileConfig`; wire per-type API error parsing in `parseWidgetConfigApiError` |
| `products/dashboards/frontend/widgets/constants.ts` | Modal width, fetch error copy, `getDashboardWidgetFetchDisplayError` |
| `products/dashboards/frontend/widget_types/catalog.ts` | Catalog entry (`groupId`, `groupLabel`, `label`, layout, headers, defaults, optional `availability`) |
| `products/dashboards/frontend/widget_types/widgetAvailability.ts` | Requirement ids, team checks, `useWidgetAvailability` hook |
| `products/dashboards/frontend/components/WidgetRuntimeAvailabilityGuard/WidgetRuntimeAvailabilityGuard.tsx` | Catalog-driven setup gate at tile render (no-op when catalog omits `availability`) |
| `products/dashboards/frontend/components/WidgetAvailabilitySetupPrompt/WidgetAvailabilitySetupPrompt.tsx` | Default setup UI for catalog `availability` requirements |
| `products/dashboards/frontend/widget_types/widgetConfigValidation.ts` | Shared `WidgetConfigValidationError` + type guard |
| `products/dashboards/frontend/widgets/<product>/<type>WidgetConfigValidation.ts` | Per-type edit-modal Zod + API error mapping (e.g. `errorTrackingWidgetConfigValidation.ts`) |
| `products/dashboards/frontend/widgets/AddWidgetModal.tsx` | Multi-select add-widget modal; catalog grouping via `getDashboardWidgetCatalogGroups()` |
| `products/dashboards/frontend/widgets/WidgetTypePickerCard.tsx` | Catalog variant picker card in add modal |
| `products/dashboards/frontend/widgets/<product>/` | Widget `Component` (+ private subcomponents), `utils.ts`, `EditModal`, tests, stories (export shared story decorators from primary `*.stories.tsx` when needed) |
| `products/dashboards/frontend/widgets/previews/` + `widgetPreviews.tsx` | Add-widget preview |
| `products/dashboards/frontend/widgets/registry.tsx` | `DASHBOARD_WIDGET_REGISTRY`, `getDashboardWidgetDefinition`, types — import components here per `widget_type` |
| `products/dashboards/frontend/components/WidgetCard/` | Compound family: thin `WidgetCard.tsx` (chrome), `WidgetCardHeader.tsx`, `WidgetCardBody.tsx` (+ `index.ts`, exports `widgetCardShouldHideMoreButton`). Platform Storybook: `WidgetCard.stories.tsx`, `DashboardWidgetsOverview.stories.tsx`; shared mocks in `widgetCardStoryFixtures.tsx` |
| `products/dashboards/frontend/components/DashboardWidgetItem/DashboardWidgetItem.tsx` | Production tile glue — composes `WidgetCard` + header/body, ⋯ menu, RBAC lock (`userHasWidgetProductAccess`), copy/move |
| `frontend/src/scenes/dashboard/dashboardLogic.tsx` | `addWidgetTiles`, fetch, config update, copy/move |
| `frontend/src/scenes/dashboard/DashboardItems.tsx` | Renders widget tiles |
| `frontend/src/scenes/dashboard/DashboardHeaderActions.tsx` | Add widget entry; `LemonMenu` item uses `tag: 'new'` |
| `frontend/src/scenes/dashboard/EmptyDashboardComponent.tsx` | Empty-state add menu; inline `LemonTag` "NEW" on Widget item |
| `frontend/src/scenes/dashboard/DashboardModals.tsx` | `AddWidgetModal` |
| `frontend/src/scenes/dashboard/tileLayouts.ts` | **Dashboard min/max tile size** — `calculateLayouts` reads catalog `defaultLayout.minW`/`minH`; test in `tileLayouts.test.ts` |
| `frontend/src/scenes/dashboard/widgetFetchUtils.ts` | Batched `run_widgets` (15 min client TTL) |
| `frontend/src/scenes/dashboard/dashboardUtils.ts` | `getDashboardWidgetType`, helpers |
| `posthog/models/resource_transfer/visitors/dashboard_widget.py` | Cross-project dashboard copy — `DashboardWidgetVisitor` (`user_facing=True`) |
| `products/dashboards/frontend/generated/api.ts`, `api.schemas.ts` | **Generated** — run `hogli build:openapi` after serializer changes |

MCP tool reference: [mcp.md](mcp.md)
