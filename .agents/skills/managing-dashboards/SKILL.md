---
name: managing-dashboards
description: >
  Guides PostHog engineers through dashboard platform and scene changes. Use when changing
  Dashboard, DashboardTile, dashboardLogic, dashboard layouts, dashboard sharing or embeds,
  public dashboards, templates, filters, variables, refresh behavior, tile loading, dashboard
  lists, or dashboard permissions. Covers normal, shared, embedded, export, product-embedded,
  and template surfaces; RBAC; cache and query behavior; responsive layouts; and large or small
  dashboards. Use manage-dashboard-widgets instead for a widget_type or WidgetCard change.
---

# Managing dashboards

Use this skill for a dashboard change that affects the dashboard platform, dashboard scene, or an existing non-widget tile type.

Use [`manage-dashboard-widgets`](../manage-dashboard-widgets/SKILL.md) for a new `widget_type` or a `WidgetCard` change.

## 1. Route the request

| Request                                                                          | Primary path               |
| -------------------------------------------------------------------------------- | -------------------------- |
| Dashboard metadata, tile lifecycle, filters, variables, refresh, list, or layout | This skill                 |
| Public links, sharing settings, embeds, exports, or product-embedded dashboards  | This skill                 |
| Dashboard template creation, editing, scope, or copying                          | This skill                 |
| New or changed `widget_type`, widget config, widget query, or WidgetCard         | `manage-dashboard-widgets` |

Before coding, decide the effect on each surface. Record `affected`, `unaffected`, or `not applicable`.

- Authenticated dashboard
- Public shared dashboard
- Embedded dashboard
- Exported dashboard
- Product-embedded dashboard
- Dashboard template
- Dashboard list and project homepage, if the change changes metadata or visibility

Read [surfaces and ownership](references/surfaces-and-ownership.md) before you select files.

## 2. Define feature intake and acceptance criteria

Do this before implementation for a new dashboard feature. Skip it for a narrow bug fix with an existing contract.

1. State the user problem, intended actor, and explicit non-goals.
2. State the feature action and its default behavior.
3. State where the feature stores its state: dashboard, tile, request, user, URL, or a separate team-scoped resource.
4. State the availability, read permission, and mutation permission.
5. State behavior for new rows, existing rows, and invalid or absent state.
6. State the acceptance criteria for allowed, denied, shared, and failure paths.
7. State the expected query, cache, and database-write effect.
8. State the metric or event that shows adoption, failure, or regression.
9. If the feature adds persisted state or relations, define migration, cleanup, and concurrent-edit behavior.
10. Check whether the user-facing API, setting, or workflow needs a documentation update.

Read [feature lifecycle and rollout](references/feature-lifecycle-and-rollout.md) before you choose a persisted feature contract.

## 3. Define the change contract

State these decisions before implementation.

1. Name the user action and the persisted data that changes.
2. Name every placement that renders the affected UI.
3. Define view, edit, and mutation permissions for each actor.
4. Define shared and embedded behavior. Never assume the authenticated behavior is safe there.
5. Define the result when the dashboard has zero, one, and hundreds of tiles.
6. Define the result at narrow and wide widths.
7. Define filter, variable, quick-filter, and tile-override precedence.
8. Define cache, refresh, query, and failure behavior.
9. If templates apply, define scope, portability, copy semantics, and later edits.
10. Define lifecycle, API, streaming, quota, audit, and project-tree effects.
11. For a new API, add MCP tools for its supported operations. Exclude an operation only with a documented reason. Record required scopes.

Use this checklist as a design gate. Read the linked reference when an item applies.

| Area                   | Check                                                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------- |
| Access                 | [RBAC, sharing, and embeds](references/access-sharing-and-embeds.md)                        |
| Filter state           | [Filters, variables, and tile overrides](references/filters-variables-and-overrides.md)     |
| Data and scale         | [Querying, caching, and scale](references/querying-caching-and-scale.md)                    |
| Layout and templates   | [Layout, responsive behavior, and templates](references/layout-responsive-and-templates.md) |
| Backend and operations | [Backend contracts and operations](references/backend-contracts-and-operations.md)          |
| Feature lifecycle      | [Feature lifecycle and rollout](references/feature-lifecycle-and-rollout.md)                |
| New state or relation  | [Data models and collaboration](references/data-models-and-collaboration.md)                |

## 4. Implement across layers

1. Change the product model, serializer, API action, and generated types together when the persisted contract changes.
2. Keep dashboard and tile data team-scoped. Use the dashboard’s project context for every lookup and mutation.
3. Update each placement deliberately. Do not hide a feature only in the frontend when the API still permits it.
4. Preserve old rows and old layouts. Treat existing layout JSON and template payloads as versioned input.
5. Keep query work bounded. Do not turn dashboard load into unbounded tile queries or concurrent requests.
6. Keep grid updates stable during drag, resize, and tile refresh. Avoid a full grid relayout for each tile result.
7. Add observability when a change creates a new loading, query, cache, access, or refresh path.
8. For list-only state, render controls only where that state applies.

## 5. Test the boundary, not only the happy path

Cover each affected boundary.

- View versus edit access.
- Authenticated, shared, embedded, and export rendering.
- Public output contains no private metadata or live data that public viewers cannot access.
- Cache hit, cache miss, stale result, forced refresh, query error, and request cancellation.
- Empty dashboard, a single tile, and a dense dashboard.
- Narrow layout, wide layout, drag, resize, insertion, duplication, and persisted layout reload.
- Template scope, permissions, variable substitution, and project-specific references.
- API schema and generated types after serializer changes.
- Paginated list ordering, each page, and client continuation when the UI loads every result.
- Filter and variable precedence, shared-token behavior, and quick-filter validation.
- Soft-delete, restore, move, copy, and project-transfer behavior.
- Streaming completion, disconnect, and individual tile failure behavior.
- Resource limits, audit events, and subscription behavior.
- Schema rollout, relation cleanup, concurrent edits, accessibility, and public content safety.

Run the focused tests for each edited layer. Then run the relevant checks from [the verification guide](references/querying-caching-and-scale.md#verification).

## 6. Code map

| Concern                                                                 | Start here                                                                                           |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Dashboard API, serializers, tile operations, insight and widget runners | `products/dashboards/backend/api/dashboard.py`                                                       |
| Dashboard model and tile model                                          | `products/dashboards/backend/models/dashboard.py`, `models/dashboard_tile.py`                        |
| Sharing and collaborator routes                                         | `products/dashboards/backend/routes.py`                                                              |
| Templates                                                               | `products/dashboards/backend/api/dashboard_templates.py`, `models/dashboard_templates.py`            |
| Main scene, state, refresh, and layout persistence                      | `frontend/src/scenes/dashboard/Dashboard.tsx`, `dashboardLogic.tsx`, `DashboardItems.tsx`            |
| Layout geometry and tile size constraints                               | `frontend/src/scenes/dashboard/tileLayouts.ts`, `dashboardUtils.ts`                                  |
| Shared and export rendering                                             | `frontend/src/exporter/scenes/ExporterDashboardScene.tsx`, `frontend/src/exporter/Exporter.tsx`      |
| Refresh defaults and shared safety clamp                                | `posthog/hogql_queries/refresh_policy.py`                                                            |
| Resource transfer                                                       | `posthog/models/resource_transfer/visitors/dashboard.py`, `dashboard_tile.py`, `dashboard_widget.py` |
| MCP tool definitions                                                    | `products/dashboards/mcp/tools.yaml`                                                                 |

## Companion skills

| Skill                          | Use when                                                            |
| ------------------------------ | ------------------------------------------------------------------- |
| `manage-dashboard-widgets`     | Change a `widget_type`, its config, query, catalog, or `WidgetCard` |
| `django-migrations`            | Change dashboard, tile, template, or widget schema                  |
| `improving-drf-endpoints`      | Change viewsets, serializer contracts, or OpenAPI output            |
| `adopting-generated-api-types` | Consume changed generated dashboard API types                       |
| `writing-kea-logics`           | Change `dashboardLogic` or another Kea logic                        |
| `writing-tests`                | Decide the lowest-cost regression test                              |
