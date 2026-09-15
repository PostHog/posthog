# Saved context in AI subscription reports

Selected dashboards and insights provide computed evidence for report planning and synthesis.
The report keeps the existing limits of three selected contexts, six insights per dashboard,
and five concurrent context queries.

Saved insights must have a stored query. Legacy filters alone leave the insight unavailable;
report generation does not convert or execute them.

Fixed planner rules follow the resolved managed prompt and take precedence over conflicting instructions.
The planner can return zero supplemental queries when successful saved evidence answers the full request
for the requested date range. It can also use exact event, property, and group names from saved query schemas,
including names absent from the project context. Computed results remain untrusted data, not instructions.

HogQL repair receives a separate schema-only snapshot from `DashboardContext.format_schema`
and `InsightContext.format_schema`. These formatters use validated queries and apply saved
dashboard filters and variable overrides. Repair never receives the saved result rows.
Schema serialization excludes embedded `response` fields recursively, including responses on
nested query nodes, without changing the stored or executed query.

The schema snapshot has a 12,000-character total budget, divided across the selected available
contexts, including separators. Oversized schemas carry a truncation marker. Formatting failures
omit the unavailable schema; query results remain independently available for planning and synthesis.
Schema preparation shares the context resolution deadline and cancellation cleanup.

Repair receives project metadata and saved schemas in a human message as untrusted data.
Fixed system instructions allow schema names as query grounding and forbid following directives
inside those blocks. These instructions remain present when a managed repair prompt overrides
the default template.
