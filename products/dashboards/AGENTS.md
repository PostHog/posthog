# Dashboards development guide

This guide applies to dashboard widget tiles in `products/dashboards/`.

Read [`CONTRIBUTING.md`](./CONTRIBUTING.md) when you add or change a widget type.
It defines the widget architecture, registry parity, generated files, and validation commands.

## Widget rules

- Treat `DashboardTile` as layout and `DashboardWidget` as team-scoped widget state.
- Register every widget type in the backend and frontend registries.
- Define each widget config in `backend/widget_specs/configs.py` before you change generated frontend config types.
- Run `hogli build:openapi` after you change `widget_specs/`.
- Use dashboard insight tiles for charts and trends. Do not create a widget type for them.

## Related skills

- Read [`building-a-dashboard`](./skills/building-a-dashboard/SKILL.md) when a user wants to create or update a dashboard.
- Read [`managing-subscriptions`](../subscriptions/skills/managing-subscriptions/SKILL.md) when a user wants scheduled dashboard delivery.
- Read `manage-dashboard-widgets` when you add a widget type or change a shipped widget.

## Scope

This guide does not cover insight tiles, text cards, or button tiles.
