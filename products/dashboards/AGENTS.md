# Dashboards development guide

This product owns dashboards, dashboard tiles, templates, saved views, and widget tiles.
Do not treat every dashboard change as a widget change.

## Choose the change type

- For dashboard metadata, layouts, insight tiles, text cards, button tiles, templates, or saved views, use the product models and API in this directory.
- For a tile with `widget_id`, read [`CONTRIBUTING.md`](./CONTRIBUTING.md). It defines widget architecture, registry parity, generated files, and validation commands.
- For dashboard creation or updates through PostHog tools, read [`building-a-dashboard`](./skills/building-a-dashboard/SKILL.md).
- For scheduled dashboard delivery, read [`managing-subscriptions`](../subscriptions/skills/managing-subscriptions/SKILL.md).

## Widget tiles only

- Apply these rules only when you add or change a tile with `widget_id`.
- Treat `DashboardTile` as layout and `DashboardWidget` as team-scoped widget state.
- Register every widget type in the backend and frontend registries.
- Define each widget config in `backend/widget_specs/configs.py` before you change generated frontend config types.
- Run `hogli build:openapi` after you change `widget_specs/`.
- Use dashboard insight tiles for charts and trends. Do not create a widget type for them.
- Read [`manage-dashboard-widgets`](../../.agents/skills/manage-dashboard-widgets/SKILL.md) when you add a widget type or change a shipped widget.
