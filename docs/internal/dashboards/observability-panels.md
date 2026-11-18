# Observability panels in dashboards

Dashboards can combine metrics insights with product analytics insights, logs, error tracking and other widgets.
Each tile keeps its query type, renderer and access requirements.

When `metrics` and `metrics-insight-builder` are enabled, **New dashboard → Application observability** opens the service-dashboard form.
Choose a name, an optional service and one or more metrics.
The result is an ordinary dashboard showing the last hour with condensed spacing.
Choosing a service creates a shared `$service` metric variable used by its metrics insights.
With `metrics-dashboard-controls` enabled, the dashboard's Service picker switches those panels together.
The variable starts with the services available when the dashboard was created and can be edited through dashboard variables.
Analytics templates, blank dashboards and feature-flag dashboards keep their existing creation flows.

Metrics is also available directly in the dashboard's chart quick-create list.
Adding a metrics chart does not change the existing dashboard's filters, layout or refresh cadence.

For an editable metrics insight tile, **Edit** opens a drawer over the dashboard.
The drawer loads the saved insight before editing, and the preview applies the dashboard and tile date overrides separately.
Saving updates the insight's query and name without storing the dashboard's overrides in that query.
When the insight is used on several dashboards, the drawer explains that saving updates all of them.
Its save button names the number of affected dashboards.
Duplicate the tile before editing to make a separate insight, or open the full insight editor.

The drawer uses the existing Metrics query editor, visualization and query APIs.
It supports builder, PromQL and SQL according to the existing feature flags.
Heatmap insights continue to use the full editor.
Saving requires edit access to the insight; the server checks access on the canonical read, preview and save.

With `metrics-dashboard-controls` enabled, partial filter scope is shown beside each dashboard control.
Scope counts cover insight tiles; logs and metrics-table widgets retain their own filters.
Dashboard property filters do not become telemetry label filters.

Auto refresh retains its existing dashboard behavior.
Short telemetry-only refresh and a unified widget/insight picker are separate changes.
