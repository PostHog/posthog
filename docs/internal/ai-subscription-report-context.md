# Saved context in AI subscription reports

Selected dashboards and insights provide computed evidence for report planning and synthesis.
The report keeps the existing limits of three selected contexts, six insights per dashboard,
and five concurrent context queries.

HogQL repair receives a separate schema-only snapshot from `DashboardContext.format_schema`
and `InsightContext.format_schema`. These formatters use validated queries and apply saved
dashboard filters and variable overrides. Repair never receives the saved result rows.

The schema snapshot has a 12,000-character total budget, divided across the selected available
contexts, including separators. Oversized schemas carry a truncation marker. Formatting failures
omit the unavailable schema; query results remain independently available for planning and synthesis.
Schema preparation shares the context resolution deadline and cancellation cleanup.

Repair receives project metadata and saved schemas in a human message as untrusted data.
Fixed system instructions allow schema names as query grounding and forbid following directives
inside those blocks. These instructions remain present when a managed repair prompt overrides
the default template.
