# Surfaces and ownership

## Start from the domain model

- `Dashboard` owns project-scoped metadata, dashboard filters, variables, sharing state, restriction level, and tile relations.
- `DashboardTile` owns one tile relation and per-breakpoint layout JSON.
- A tile is exactly one insight, text card, button, or widget.
- `DashboardTemplate` stores a copyable dashboard definition. It is not a live dashboard.
- Dashboard widgets use a separate model. Read `manage-dashboard-widgets` for widget-specific work.

## Render placements

Use `DashboardPlacement` as the frontend placement contract.

| Placement                       | Required behavior                                                                                            |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `Dashboard`                     | Full authenticated dashboard. Editing may be available.                                                      |
| `ProjectHomepage` and `Builtin` | Dashboard content in another authenticated product surface. Check action visibility and available width.     |
| `Public`                        | Public share. Read-only. Do not expose authorship, folders, private configuration, or force-refresh actions. |
| `Export`                        | Export rendering. Do not add interactive controls or assume a browser user session.                          |
| `FeatureFlag` and `Group`       | Embedded dashboard contexts. Check the host page, URL state, permissions, and refresh behavior.              |

Also check product-created unlisted dashboards. `Dashboard.CreationMode.UNLISTED` hides these from normal lists but does not remove dashboard rules.

## Ownership map

| Area                | Files                                                                                            |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| Models              | `products/dashboards/backend/models/dashboard.py`, `dashboard_tile.py`, `dashboard_templates.py` |
| Dashboard endpoints | `products/dashboards/backend/api/dashboard.py`                                                   |
| Templates endpoint  | `products/dashboards/backend/api/dashboard_templates.py`                                         |
| Product routes      | `products/dashboards/backend/routes.py`                                                          |
| Scene state         | `frontend/src/scenes/dashboard/dashboardLogic.tsx`                                               |
| Main layout         | `frontend/src/scenes/dashboard/DashboardItems.tsx`, `tileLayouts.ts`                             |
| Shared/export host  | `frontend/src/exporter/scenes/ExporterDashboardScene.tsx`, `frontend/src/exporter/Exporter.tsx`  |

## API contract changes

If the change alters a serializer or viewset:

1. Add or update the request and response schema.
2. Run `hogli build:openapi`.
3. Use generated API types in frontend code.
4. Test the API endpoint and the UI contract.

Do not edit generated files directly.
