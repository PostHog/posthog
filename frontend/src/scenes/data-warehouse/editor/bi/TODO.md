# SQL Builder release gaps

This document tracks the work required to release the SQL editor's visual query builder beyond its current limited audience.

The working product name is **Builder**. Calling the current experience **BI** promises a semantic modeling, exploration, and reporting surface that it does not yet provide.

This is a planning document, not a committed roadmap. Each item needs product validation before implementation.

## Product promise

The Builder should let someone answer a useful data question without writing SQL, while preserving a clear path to SQL when the question outgrows the visual interface.

A successful first release should make these promises:

- A person can build and rerun a supported query without learning HogQL syntax.
- A person never loses SQL or Builder work by changing editor modes.
- A saved Builder query remains editable in Builder after reopening it.
- The interface only offers operations supported by the selected data source.
- Invalid or incomplete configuration produces a specific, actionable message.
- The generated query remains visible and trustworthy.
- Keyboard, pointer, and assistive-technology users can complete the core flow.

The first release does not need to replace a complete BI platform. It should describe its scope honestly, probably as a single-table visual query builder until joins and semantic metadata exist.

## User jobs and initial scope

A feature checklist is not enough to establish a useful Builder. The release should be evaluated against complete user jobs that start before query construction and continue after a result renders.

### Answer a new question

A user should be able to start from a product concept or data source, find relevant fields, construct a query, inspect the result, and refine the question without restarting.

- [ ] Entry points preserve the table, event, person, cohort, or other context that led to Builder.
- [ ] Schema search helps the user distinguish similar fields.
- [ ] Query history and undo make experimentation safe.
- [ ] A result exposes an obvious next analytical action.

### Create a reusable artifact

A useful exploration should become a saved query, insight, dashboard item, or notebook input without rebuilding the logic.

- [ ] Builder state survives every supported save path.
- [ ] The destination shows which parts remain editable in Builder.
- [ ] Parameters replace hard-coded values when an artifact needs viewer input.
- [ ] The artifact has a stable owner, URL, and permission model.

### Investigate a result

A surprising value should lead to more detail through filtering, drilling, row inspection, or a deeper analysis surface.

- [ ] Tables and charts expose contextual follow-up actions.
- [ ] Follow-up actions preserve the parent query and selected value.
- [ ] Users can inspect the generated filter before running it.
- [ ] Users can continue complex investigations in a notebook.

### Enable safe self-service

People who understand the business question but not the physical schema should be able to use curated definitions without changing their meaning.

- [ ] Curated fields and measures appear before raw implementation details.
- [ ] Official definitions remain distinguishable from exploratory calculations.
- [ ] Permissions apply consistently from discovery through drill-down.
- [ ] The interface reveals enough generated SQL for technical review.

### Collaborate and distribute

Recurring analysis should support review, sharing, refresh, and delivery rather than ending as one person's browser state.

- [ ] Reviewers can understand the query without reproducing the session.
- [ ] Concurrent edits cannot silently overwrite work.
- [ ] Consumers can subscribe to or embed an appropriate published artifact.
- [ ] Ownership and revision history identify the current source of truth.

### Initial audience assumptions

The first release should optimize for product teams that need answers beyond a predefined insight but do not want to begin with SQL. It should also give SQL-fluent reviewers a transparent escape hatch.

The initial release should not claim to provide:

- A complete enterprise semantic-modeling environment.
- A spreadsheet replacement for planning and scenario modeling.
- A general-purpose application builder with writeback.
- A presentation canvas for arbitrary narrative layouts.
- A replacement for Python or multi-step notebook analysis.

Those remain useful future hypotheses. They should not delay a coherent, durable query-building workflow.

## Release levels

### Limited beta

A limited beta can focus on one table, common aggregations, simple filters, grouping, sorting, and visualization.

Before that beta:

- [ ] Land the Monaco lifecycle fix for switching editors and opening tables.
- [ ] Preserve Builder configuration when a saved query or insight is reopened.
- [x] Warn before Builder replaces SQL that it cannot reconstruct.
- [x] Hide Builder for raw-query connections.
- [x] Reject incomplete fields, aggregations, and filters before execution.
- [ ] Publish a supported-source and supported-chart matrix.
- [ ] Add keyboard-accessible field selection.
- [ ] Verify the complete create, save, reopen, edit, and duplicate flow.

### Public beta

A public beta should support exploratory work without forcing users into SQL for ordinary operations.

- [ ] Add searchable field selection and click-to-add behavior.
- [ ] Add chart-aware field wells and compatibility guidance.
- [ ] Add useful date, numeric, boolean, and string filters.
- [ ] Add multiple sorts and deterministic sort priority.
- [ ] Add query preview and estimated result shape.
- [ ] Add undo and redo for Builder edits.
- [ ] Add first-run guidance and contextual examples.
- [ ] Add product-native starting points and notebook continuation.
- [ ] Make result tables useful for follow-up exploration.
- [ ] Measure successful query construction, not only mode selection.

### General availability

General availability should mean saved work is durable, shareable, governed, and sufficiently expressive for recurring analysis.

- [ ] Support joins or explicitly constrain the product to curated models.
- [ ] Support reusable dimensions and measures.
- [ ] Support drill-down and viewing underlying rows.
- [ ] Support parameters suitable for dashboards and shared reports.
- [ ] Support promotion from exploratory work to an official artifact.
- [ ] Define refresh, subscription, and embedding behavior.
- [ ] Define compatibility and migration behavior for Builder schema changes.
- [ ] Meet accessibility, performance, reliability, and observability targets.
- [ ] Publish user documentation and troubleshooting guidance.

## P0: prevent lost work and broken state

### Persist an editable Builder definition

**User expectation:** Saving means the work can be reopened and edited in the same interface.

**Current gap:** The active tab and URL can carry Builder state, but the saved query or insight primarily persists generated SQL. Reopening that artifact cannot reliably reconstruct the shelves, filters, sorting, or visualization choices.

**Why it matters:** A successful first session can become an SQL-only artifact on the next visit. That breaks the central no-code promise and makes sharing inconsistent.

**Patch direction:**

- Define a versioned `builder_config` payload owned by the saved artifact.
- Store the generated SQL beside the config as a derived representation.
- Regenerate SQL from the config when the Builder version remains compatible.
- Keep the last runnable SQL when config migration fails.
- Display a recovery message instead of silently dropping Builder state.
- Copy Builder state when duplicating an insight, query, endpoint, or metric.
- Decide whether editing generated SQL detaches the artifact from Builder.

**Acceptance criteria:**

- [ ] Saving and reopening reproduces every visible Builder control.
- [ ] Sharing a URL and opening a saved artifact produce the same configuration.
- [ ] Duplicating an artifact preserves its Builder configuration.
- [ ] Older configuration versions migrate or fail with a recoverable message.
- [ ] SQL execution never depends on a client-only state value that was not saved.

### Make mode conversion explicitly one-way

**User expectation:** A two-way toggle implies reversible conversion.

**Current gap:** Builder can generate SQL, but it cannot parse arbitrary SQL back into a Builder configuration. Returning to Builder can replace manual SQL edits with an older generated query.

**Patch direction:**

- Treat Builder-to-SQL as an explicit conversion or detachment action.
- Keep a confirmation when entering Builder would replace current SQL.
- Offer to copy the SQL into a new tab before replacement.
- Consider separate **Edit in Builder** and **View SQL** actions instead of a symmetric toggle.
- Preserve a short-lived recovery snapshot after a conversion.
- Explain which SQL changes make Builder reconstruction impossible.

**Acceptance criteria:**

- [x] A confirmation identifies that current SQL will be replaced.
- [ ] Cancel leaves the SQL and editor state untouched.
- [ ] The user can preserve both versions without copying text manually.
- [ ] Undo or recovery restores the previous SQL after accidental conversion.
- [ ] Saved artifacts clearly indicate whether Builder remains their source of truth.

### Eliminate editor lifecycle crashes

**User expectation:** Switching modes or opening a table should never destroy the editor.

**Current gap:** A disposed Monaco editor can be reused during some navigation and mode-switch sequences, leaving the editor blank until reload.

**Patch direction:**

- Land the editor-liveness fix before expanding the flag.
- Cover SQL-to-Builder, Builder-to-SQL, sidebar table opening, and tab switching.
- Test both an empty editor and an editor with unsaved SQL.
- Verify repeated switching, not only the first transition.

**Acceptance criteria:**

- [ ] No transition calls methods on a disposed editor instance.
- [ ] The editor remains visible after repeated mode changes.
- [ ] Unsaved SQL remains intact after unrelated sidebar navigation.
- [ ] A browser test covers the original failure sequence.

## P0: respect data-source capabilities

### Define a connection capability contract

**User expectation:** Every visible control works for the selected source.

**Current gap:** Builder generation uses HogQL and ClickHouse-oriented functions. Raw-query sources and external connections can have different syntax, function, type, and metadata behavior.

**Patch direction:**

- Add a capability object for each connection type.
- Include supported aggregations, date buckets, operators, joins, limits, and sorting.
- Generate expressions from capabilities instead of assuming ClickHouse syntax.
- Hide unsupported controls before configuration begins.
- Explain why Builder is unavailable for a connection.
- Add contract tests for every supported connection class.

**Acceptance criteria:**

- [x] Raw-query connections do not show Builder.
- [ ] Every visible operation has a source-specific generation test.
- [ ] Unsupported functions never reach query execution.
- [ ] Connection errors distinguish unsupported syntax from ordinary query failure.
- [ ] Documentation names the supported connection types.

### Make query-engine behavior legible

**User expectation:** The interface explains which engine will run the query and how that choice affects syntax, types, and available operations.

**Current gap:** A connection selector does not fully communicate the behavioral differences between PostHog data, warehouse tables, DuckDB-backed queries, and raw external execution.

**Patch direction:**

- Display the active engine near source selection and query execution.
- Link each engine to its supported operations and known limitations.
- Translate engine-specific failures into the responsible Builder control where possible.
- Preserve native types through metadata, generation, execution, and visualization.
- Test dates, decimals, arrays, structs, nullable values, and source-specific identifiers.
- Keep the engine visible when a query continues into a notebook or saved artifact.
- Avoid presenting internal execution choices unless they change user-visible behavior.

**Acceptance criteria:**

- [ ] A user can identify the engine before running a query.
- [ ] Unsupported types fail during configuration instead of after SQL generation.
- [ ] An engine error explains whether the query, source, or Builder operation needs to change.
- [ ] Moving the query into another analysis surface preserves its engine requirements.

### Validate chart and result compatibility

**User expectation:** Selecting a visualization should guide the query toward a result that the chart can render.

**Current gap:** The same generic Rows, Columns, Values, and Filters shelves appear for every visualization. The interface does not describe required dimensions, measures, cardinality, or data types.

Chart count should not be the release target. A smaller set of charts with complete filtering, interaction, drill, formatting, and accessibility is more useful than broad but shallow parity.

**Patch direction:**

- Define field roles for each visualization.
- Describe required and optional roles in the UI.
- Validate field counts and types before running.
- Suggest a compatible visualization from the current result shape.
- Preserve compatible fields when the visualization changes.
- Explain which fields will be dropped before clearing them.
- Define the analytical job served by every supported visualization.
- Prioritize table, trend, comparison, composition, distribution, and summary workflows before specialized chart variants.

**Acceptance criteria:**

- [ ] Each chart declares its accepted field roles and types.
- [ ] Invalid configurations show an inline explanation.
- [ ] Changing charts does not silently discard compatible configuration.
- [ ] A table remains a safe fallback for any valid tabular result.
- [ ] Every generally available chart supports the common interaction and accessibility contract.

## P1: make query construction discoverable

### Add a searchable field picker

**User expectation:** Fields can be found and added without precise drag-and-drop interaction.

**Current gap:** Schema fields are primarily added by dragging. Clicking a field does not place it, and the `+` action opens an expression editor rather than a field chooser.

**Patch direction:**

- Make a field click add it to the most likely compatible shelf.
- Open a searchable, keyboard-accessible field picker from each shelf.
- Separate **Add field** from **Add expression**.
- Show field type, source table, description, and sample value where permitted.
- Rank exact and prefix matches above fuzzy matches.
- Keep the picker open for adding several fields.
- Provide clear removal and reorder controls.

**Acceptance criteria:**

- [ ] The core query can be built without dragging.
- [ ] A keyboard user can search, select, reorder, and remove fields.
- [ ] Duplicate column names include enough table context to distinguish them.
- [ ] Field type and compatibility are available before selection.

### Use chart-aware field wells

**User expectation:** Labels such as Axis, Series, Value, Color, or Size explain how a field affects the selected chart.

**Current gap:** Database-shaped Rows and Columns labels require users to infer chart semantics.

**Patch direction:**

- Let visualization definitions provide shelf labels and requirements.
- Map the underlying query model to presentation-specific labels.
- Show a small role example in empty shelves.
- Use type-aware placement when a field is clicked.
- Make automatic placement reversible and predictable.

**Acceptance criteria:**

- [ ] Empty chart configuration explains the minimum fields required.
- [ ] Numeric and categorical fields land in sensible default roles.
- [ ] Automatic placement never moves existing fields without notice.
- [ ] The table visualization retains familiar column-oriented controls.

### Improve empty, loading, and error states

**User expectation:** The interface explains the next useful action and preserves context during failure.

**Current gap:** Empty shelves provide limited guidance, and query errors can expose generated syntax without connecting the failure to the responsible Builder control.

**Patch direction:**

- Add a first-query path with a source, field, and visualization example.
- Keep the last successful result visible while a new query runs.
- Map generation and execution errors back to the relevant control.
- Offer a SQL view for advanced diagnosis without detaching the Builder.
- Distinguish empty results from an invalid query.
- Preserve configuration after timeout or cancellation.

**Acceptance criteria:**

- [x] Empty shelves explain both drag and expression paths.
- [ ] Every blocking state gives one clear next action.
- [ ] Execution failure never clears a valid configuration.
- [ ] Empty results retain column metadata when available.

## P1: support ordinary analytical questions

### Expand filter operations

**User expectation:** Common date, numeric, boolean, null, and text questions do not require SQL.

**Current gap:** The filter model lacks several routine comparisons, relative-date workflows, and grouped logic.

**Patch direction:**

- Add greater-than, less-than, between, not-between, and not-equal operators.
- Add is-null, is-not-null, is-empty, and is-not-empty behavior.
- Add relative date presets such as today, yesterday, trailing periods, and current periods.
- Add explicit timezone behavior for relative dates and date bucketing.
- Add multi-select and search for categorical values.
- Add nested AND/OR groups with a readable summary.
- Add filters on aggregated values where the query model supports them.
- Keep custom expressions as an escape hatch, not the default path.

**Acceptance criteria:**

- [ ] Operators are restricted by field type.
- [ ] Relative dates display their resolved timezone.
- [ ] Empty strings and null values remain distinct.
- [ ] Grouped filters render with unambiguous precedence.
- [ ] Large categorical domains do not require loading every value.

### Support multiple sorts

**User expectation:** Sorting is deterministic and can express a primary and secondary order.

**Current gap:** A single sort cannot resolve ties or represent many ranked-table workflows.

**Patch direction:**

- Store an ordered list of sort definitions.
- Expose priority through numbering and drag or keyboard reordering.
- Allow sorting by grouped fields and aggregate aliases.
- Preserve sorting when a compatible field is renamed or moved.
- Warn when a selected source cannot sort by an expression.

**Acceptance criteria:**

- [ ] The generated query preserves visible sort priority.
- [ ] Removing a field removes or repairs dependent sorts explicitly.
- [ ] Sorting behaves consistently across supported sources.

### Add approachable calculations

**User expectation:** Ratios, buckets, conditional labels, and simple date arithmetic are available without writing raw SQL.

**Current gap:** Custom expressions require syntax knowledge and provide little guided construction.

**Patch direction:**

- Add a type-aware expression builder for common operations.
- Provide templates for ratios, percentages, conditional values, and bucketing.
- Validate expressions as they are authored.
- Show the output type and generated expression.
- Allow naming calculated fields before placing them on a shelf.
- Reuse saved calculations when a semantic layer becomes available.

**Acceptance criteria:**

- [ ] A user can create a conversion rate without raw SQL.
- [ ] Invalid expressions identify the failing input.
- [ ] Calculated fields participate in filtering, grouping, and sorting when valid.
- [ ] Renaming a calculation updates dependent configuration safely.

### Add joins or curated models

**User expectation:** Related business entities can be analyzed together.

**Current gap:** A single-table builder cannot answer routine questions that cross events, persons, revenue, campaigns, or warehouse entities.

**Patch direction:**

- Choose between guided joins and a curated semantic-model approach.
- Prefer declared relationships over unconstrained column matching.
- Show join direction, cardinality, and expected row multiplication.
- Suggest known relationships from metadata.
- Require explicit confirmation for many-to-many joins.
- Keep the generated join visible in SQL.
- Enforce existing table-access controls throughout discovery and execution.

**Acceptance criteria:**

- [ ] Joinable entities are discoverable without knowing physical keys.
- [ ] The UI communicates one-to-one, one-to-many, and many-to-many behavior.
- [ ] A join cannot expose a table unavailable to the current user.
- [ ] Row multiplication risks appear before query execution.
- [ ] Removing a join reports every dependent field that will be removed.

## P1: establish semantic meaning

### Introduce dimensions and measures

**User expectation:** Business concepts have stable names and definitions across reports.

**Current gap:** Raw columns and ad hoc aggregations require each user to rediscover meaning. Similar-looking queries can calculate different results.

**Patch direction:**

- Define reusable dimensions, measures, default aggregations, and descriptions.
- Include ownership, formatting, units, and deprecation metadata.
- Distinguish additive, semi-additive, and non-additive measures.
- Offer curated fields before raw physical columns.
- Link a field to its source definition and generated SQL.
- Version semantic definitions without breaking saved Builder artifacts.

**Acceptance criteria:**

- [ ] A measure produces the same definition across Builder queries.
- [ ] Field descriptions appear during search and selection.
- [ ] Deprecated fields direct users toward replacements.
- [ ] Units and formats flow into compatible visualizations.
- [ ] Permission checks apply to both semantic fields and their physical sources.

### Clarify aggregation behavior

**User expectation:** Counts, distinct counts, averages, totals, and percentages state exactly what they calculate.

**Current gap:** Blank or incomplete aggregation configuration can otherwise degrade into a different valid query, such as a row count.

**Patch direction:**

- Require a complete aggregation before execution.
- Name `count(*)`, count of values, and distinct count separately.
- Explain null handling for each aggregation.
- Restrict aggregations based on field type and source capability.
- Add percentage-of-total and running calculations only with explicit ordering semantics.

**Acceptance criteria:**

- [x] Incomplete custom aggregations block execution.
- [ ] Aggregation labels describe null and distinct behavior.
- [ ] The Builder never substitutes a different aggregation silently.
- [ ] Generated aliases remain stable enough for sorting and visualization.

## P1: complete the exploration loop

### Add preview before full execution

**User expectation:** Query shape and likely mistakes can be checked cheaply before running an expensive query.

**Current gap:** The interface moves directly from configuration to full query execution.

**Patch direction:**

- Preview generated SQL continuously without executing it.
- Offer a limited-row data preview with clear sampling semantics.
- Show the expected output columns and types.
- Surface obvious high-cardinality groupings before a chart attempts to render them.
- Reuse cached metadata and previews where safe.
- Never represent a sample as a complete result.

**Acceptance criteria:**

- [ ] The preview identifies output columns before a full run.
- [ ] Sampled or limited results display a persistent qualifier.
- [ ] Preview cancellation does not cancel an unrelated saved query run.
- [ ] Preview requests respect permissions and query limits.

### Support drill-down and underlying rows

**User expectation:** A surprising chart point can be investigated without starting over.

**Current gap:** Rendered results are mostly an endpoint. There is no structured path from a mark or cell to filtered detail.

**Patch direction:**

- Let a chart interaction add a visible filter to a copied Builder state.
- Offer underlying rows when the aggregation and permissions allow it.
- Show the exact filter produced by a drill action.
- Keep breadcrumbs for drill depth and support returning to the parent view.
- Preserve the original artifact unless the user explicitly saves the drilled state.
- Define safe limits for detail queries.

**Acceptance criteria:**

- [ ] Clicking a supported mark offers relevant drill actions.
- [ ] Every drill produces inspectable Builder configuration.
- [ ] A user can return to the original result without rerunning it.
- [ ] Underlying rows cannot bypass field or table permissions.

### Add parameters and reusable controls

**User expectation:** A saved analysis can accept a date range or category without editing its definition.

**Current gap:** Filters are part of authoring rather than a stable input contract for viewers and dashboards.

**Patch direction:**

- Distinguish author filters from exposed parameters.
- Give parameters stable identifiers, types, defaults, and allowed values.
- Map dashboard filters to compatible Builder parameters.
- Validate required parameters before execution.
- Make URL parameter behavior explicit and safe.

**Acceptance criteria:**

- [ ] A dashboard filter can bind to a declared Builder parameter.
- [ ] Viewer-supplied values cannot change query structure.
- [ ] Missing required values produce a clear empty state.
- [ ] Shared URLs do not expose sensitive parameter values unexpectedly.

## P1: connect Builder to the analysis workflow

### Start from product-native context

**User expectation:** Starting from a product question should retain the event, person, cohort, experiment, feature flag, or replay context that prompted it.

**Current gap:** A generic table-first Builder makes PostHog data feel like an arbitrary warehouse schema and asks the user to reconstruct relationships the product already understands.

**Patch direction:**

- Add **Explore in Builder** actions to appropriate product-data surfaces.
- Preselect the relevant source, fields, and safe filters from the originating context.
- Offer product-oriented starting points such as behavior over time, conversion breakdowns, and affected-user inspection.
- Preserve a link back to the source insight, experiment, flag, or replay search.
- Suggest known PostHog relationships before generic physical joins.
- Use the same definitions as existing product analytics when representing the same metric.
- Make differences from an existing insight definition explicit.

**Acceptance criteria:**

- [ ] A contextual entry point opens a valid, inspectable Builder configuration.
- [ ] Generated queries reproduce the meaning shown at the source surface.
- [ ] Users can remove inherited context without hidden constraints remaining.
- [ ] Returning to the source surface preserves its original state.
- [ ] Product-native suggestions respect the same permissions as direct navigation.

### Continue into a notebook

**User expectation:** A visual query can become one step in a deeper analysis without copying SQL, results, or context manually.

**Current gap:** Builder can produce a result, but the handoff does not yet define how editable configuration, generated SQL, parameters, engine requirements, and result references should travel together.

**Patch direction:**

- Make **Continue in a notebook** a first-class action after a successful run.
- Create a notebook node that references the saved query or carries a durable Builder definition.
- Preserve source, connection, parameters, visualization, and result context.
- Let notebook authors reopen the originating Builder configuration.
- Avoid embedding large result payloads when a query reference is sufficient.
- Define whether notebook edits update, fork, or detach from the original artifact.
- Support a clear return path from the notebook to the Builder artifact.

**Acceptance criteria:**

- [ ] Continuation requires no manual SQL copy.
- [ ] The notebook reruns the same query under the same engine and permissions.
- [ ] Builder edits made from a notebook follow an explicit update or fork action.
- [ ] Parameters remain bound after continuation.
- [ ] The handoff does not duplicate unbounded query results in client state.

### Make result tables interactive

**User expectation:** A result table is an exploration surface, not only a static rendering of the last query.

**Current gap:** Follow-up filtering, sorting, record inspection, and column operations are weaker than the corresponding construction controls.

**Patch direction:**

- Add a cell or column value as a visible Builder filter.
- Add or change sorting from a column header.
- Open a record detail view when a stable entity identifier exists.
- Copy a cell, row, column name, or filtered-link value predictably.
- Pin, resize, reorder, and format columns without changing query semantics unnecessarily.
- Distinguish presentation-only table state from query-changing state.
- Offer underlying rows for aggregate results when permissions and cost allow it.
- Preserve table interaction when saving or continuing into another artifact where appropriate.

**Acceptance criteria:**

- [ ] A table filter always appears in the Builder configuration.
- [ ] Presentation-only changes do not trigger a query rerun.
- [ ] Query-changing actions remain undoable.
- [ ] Record inspection has a safe fallback when no stable identifier exists.
- [ ] Large results retain virtualization and cancellation behavior.

### Make the next useful action obvious

**User expectation:** Each stage offers a natural next step instead of leaving the user to navigate between disconnected tools.

**Current gap:** Source selection, Builder, SQL, results, notebooks, insights, and dashboards expose overlapping actions without a single coherent progression.

**Patch direction:**

- Define the primary action for empty, configured, successful, failed, and saved states.
- Keep secondary destinations available without giving them equal visual weight.
- Preserve context across Builder, SQL, notebook, insight, and dashboard transitions.
- Avoid creating duplicate artifacts when the user intends to update the current one.
- Explain whether each action saves, copies, converts, or only navigates.
- Test the flow from an initial question through a rerunnable shared result.

**Acceptance criteria:**

- [ ] Every state has one identifiable primary action.
- [ ] Destination actions state whether they mutate or create an artifact.
- [ ] Back navigation never depends on browser history to restore unsaved analysis.
- [ ] A first-time user can reach a saved result without understanding PostHog artifact types first.

## P1: editing confidence

### Add undo, redo, and recovery

**User expectation:** Exploratory changes can be reversed without reconstructing a query.

**Current gap:** Removing a shelf item, changing a visualization, or switching modes can have broad effects without a durable recovery path.

**Patch direction:**

- Record Builder actions in a bounded local history.
- Group related automatic updates into one undo step.
- Keep recovery snapshots for destructive mode transitions.
- Reset history at intentional save boundaries without discarding recovery.
- Define behavior across tabs and browser reloads.

**Acceptance criteria:**

- [ ] Add, remove, move, filter, sort, and visualization changes can be undone.
- [ ] Automatic compatibility cleanup appears as one reversible action.
- [ ] Undo never restores fields the current user can no longer access.
- [ ] The UI communicates when recovery history is unavailable.

### Make dependencies visible

**User expectation:** Removing a field explains the filters, sorts, calculations, or chart roles that depend on it.

**Current gap:** Builder configuration is presented as independent shelves even when generated expressions depend on one another.

**Patch direction:**

- Track stable identifiers instead of relying only on display text.
- Show dependent configuration before destructive removal.
- Update aliases and references through a single dependency graph.
- Prevent cyclic calculated-field references.
- Surface broken references inline after schema changes.

**Acceptance criteria:**

- [ ] Renaming a field does not break its dependent sort.
- [ ] Removing a field lists affected controls before confirmation.
- [ ] Schema changes produce repairable states rather than malformed SQL.

## P2: collaboration and governance

### Support sharing and ownership

**User expectation:** Shared Builder work has an owner, a stable URL, and predictable edit permissions.

**Current gap:** Client-carried state is easy to share transiently but does not provide a durable collaboration contract.

**Patch direction:**

- Make Builder configuration part of the saved artifact revision.
- Display owner, last editor, and last successful run.
- Respect view, edit, duplicate, and share permissions.
- Define concurrent-edit behavior.
- Preserve an inspectable revision when Builder generation changes.

**Acceptance criteria:**

- [ ] A viewer sees the same Builder definition as the author.
- [ ] A read-only user cannot mutate the saved artifact.
- [ ] Concurrent edits cannot silently overwrite newer work.
- [ ] Revision history identifies configuration and generated-SQL changes.

### Support review and edit awareness

**User expectation:** Teammates can discuss, review, and safely change recurring analysis without coordinating in a separate tool.

**Current gap:** Ownership and revision history do not provide comments, edit presence, field-level discussion, or a deliberate review state.

**Patch direction:**

- Show when another authorized user is actively editing the artifact.
- Prevent silent last-write-wins behavior.
- Allow comments on the artifact and, where stable, on a Builder control or result.
- Preserve comment anchors through compatible configuration changes.
- Provide a reviewable diff for query meaning, not only serialized JSON.
- Notify owners without exposing query contents through unsafe channels.
- Define lightweight review without making exploratory work bureaucratic.

**Acceptance criteria:**

- [ ] Concurrent writers receive a conflict or merge path before save.
- [ ] A reviewer can identify changes to sources, filters, measures, and joins.
- [ ] Comments retain author, timestamp, resolution state, and permission checks.
- [ ] Exploratory work remains editable without mandatory approval.

### Promote exploratory work to trusted content

**User expectation:** Consumers can distinguish a personal exploration from a reviewed definition used for recurring decisions.

**Current gap:** A saved artifact can be reusable without communicating whether its logic is official, reviewed, deprecated, or experimental.

**Patch direction:**

- Define a small lifecycle such as exploratory, reviewed, official, and deprecated.
- Require ownership and a durable Builder or SQL definition before promotion.
- Record the reviewer and revision that received trusted status.
- Display trust state in search, dashboards, notebooks, and the Builder.
- Warn when a trusted artifact depends on exploratory or deprecated definitions.
- Revoke or request renewed review after meaningfully changing query logic.
- Keep trust labels separate from access permissions.

**Acceptance criteria:**

- [ ] Every trust state has clear requirements and consequences.
- [ ] Promotion attaches to an immutable artifact revision.
- [ ] Editing trusted logic cannot retain its status silently.
- [ ] Search can prefer trusted content without hiding exploratory work.
- [ ] Users can inspect why an artifact is considered trusted.

### Keep generated SQL trustworthy

**User expectation:** SQL generated by a visual tool remains inspectable and explains the result.

**Current gap:** Generated SQL is available, but the boundary between editable source, derived output, and detached manual SQL is not explicit.

**Patch direction:**

- Label generated SQL as read-only while Builder is the source of truth.
- Offer copy and detach actions.
- Format generated SQL deterministically.
- Include stable aliases that reflect visible field names.
- Expose which Builder control produced a selected SQL fragment where practical.
- Avoid hidden transformations that cannot be represented in the Builder.
- Keep source-aware autocomplete, schema navigation, and engine documentation available after detaching.
- Map execution errors to the generated or edited SQL range and the originating Builder control when possible.
- Preserve query history with enough origin metadata to recover the Builder version.

**Acceptance criteria:**

- [ ] The same configuration produces stable SQL formatting and aliases.
- [ ] Editing SQL requires an explicit detach action.
- [ ] Returning to Builder never treats detached SQL as Builder-authored.
- [ ] The generated SQL can be copied without changing editor state.
- [ ] A detached query retains its connection and receives source-aware SQL assistance.
- [ ] Query history distinguishes generated SQL from manually edited SQL.

### Honor permissions throughout discovery

**User expectation:** Field discovery, previews, generated SQL, and drill actions reveal only authorized data.

**Current gap:** Expanding metadata and preview features increases the number of paths that must enforce table and field access.

**Patch direction:**

- Apply existing access controls to schema search and field suggestions.
- Avoid sample values where metadata visibility does not imply value visibility.
- Revalidate saved configurations when permissions change.
- Keep denied fields identifiable enough to repair without leaking their values.
- Audit generated queries through the same path as hand-written queries.

**Acceptance criteria:**

- [ ] Search results exclude inaccessible fields and tables.
- [ ] Preview and value suggestions use the same authorization boundary as execution.
- [ ] A revoked field produces a safe, actionable saved-query state.
- [ ] Builder does not create a second query authorization path.

### Deliver recurring results

**User expectation:** A recurring analysis can refresh and reach its audience without someone reopening the Builder manually.

**Current gap:** Saving the query does not by itself define scheduling, freshness, subscriptions, alerts, embedding, or failure ownership.

**Patch direction:**

- Separate query definition from delivery configuration.
- Reuse existing dashboard, subscription, alert, export, and embedding primitives where possible.
- Show last success, freshness, next run, and failure state on recurring artifacts.
- Let recipients understand the applied parameters and result timestamp.
- Route delivery failures to an owner without including sensitive query results.
- Keep embeds read-only unless an explicit parameter contract allows interaction.
- Define whether a changed Builder revision requires delivery review.

**Acceptance criteria:**

- [ ] A recurring artifact has an accountable owner.
- [ ] Every delivered result includes its data freshness and active parameters.
- [ ] Delivery failure does not present stale data as current.
- [ ] Embedded artifacts enforce the same data permissions or an explicit sharing policy.
- [ ] Query edits and delivery edits have separate audit history.

### Keep operational actions out of the initial promise

**User expectation:** A button that changes data or triggers a workflow has stronger safety guarantees than a query control.

**Current gap:** Interactive BI products can blur filtering, input, writeback, and operational actions even though those operations have different authorization and recovery needs.

**Patch direction:**

- Treat writeback and external actions as a later, separately reviewed capability.
- Require explicit action schemas, authorization, confirmation, and audit logging.
- Never infer write access from permission to run a query.
- Separate scenario inputs from writes to source data.
- Make retry and partial-failure behavior visible.

**Acceptance criteria:**

- [ ] The initial Builder release cannot mutate source data.
- [ ] Future actions use a dedicated permission boundary.
- [ ] Every mutation identifies its target and expected effect before confirmation.
- [ ] A failed multi-step action cannot appear fully successful.

## P2: make AI useful inside the workflow

### Ground assistance in visible definitions

**User expectation:** AI suggestions use available schema, semantic definitions, product context, and permissions instead of guessing from field names alone.

**Current gap:** A one-shot generated answer can look complete while remaining detached from trusted measures, saved artifacts, and the controls needed to verify it.

**Patch direction:**

- Give assistance the same authorized schema and semantic context shown in Builder.
- Prefer trusted definitions when several fields appear to represent the same concept.
- Explain the selected source, fields, filters, and aggregation before execution.
- Apply suggestions as a reviewable Builder configuration change.
- Keep generated changes undoable.
- Let users inspect generated SQL and cited definitions.
- Ask for clarification when a business term maps to several plausible concepts.
- Turn useful answers into durable Builder, notebook, insight, or dashboard artifacts.

**Acceptance criteria:**

- [ ] AI cannot select fields hidden from the current user.
- [ ] Every proposed query is editable before or after execution.
- [ ] Trusted definitions are identifiable in the proposal.
- [ ] Applying a proposal creates one undoable Builder action.
- [ ] An answer can become a saved artifact without regenerating it from chat text.

### Help with errors and next steps

**User expectation:** Assistance explains a failure or suggests a useful refinement while preserving control over the analysis.

**Current gap:** Generic error repair and open-ended chat can lose the exact Builder state, engine constraints, or result selection that prompted the question.

**Patch direction:**

- Attach help to the current Builder configuration and structured error.
- Propose the smallest valid configuration change that addresses the failure.
- Explain unsupported engine capabilities without inventing syntax.
- Suggest follow-up filters, breakdowns, drills, or notebook continuation from the current result.
- Preview the effect before applying destructive changes.
- Avoid sending result rows or sensitive filter values unless the existing policy permits it.

**Acceptance criteria:**

- [ ] Error assistance references the responsible control.
- [ ] A rejected suggestion leaves configuration unchanged.
- [ ] Suggested next steps retain the current query context.
- [ ] Assistance records product telemetry without query contents or result values.

## P2: accessibility and layout

### Make every action keyboard accessible

**User expectation:** Building a query does not require a pointer or drag gesture.

**Current gap:** Dragging is the main field-placement interaction, and shelf reordering lacks a complete keyboard model.

**Patch direction:**

- Provide button and picker alternatives for every drag action.
- Define focus order across source, shelves, controls, visualization, and results.
- Add keyboard move-up and move-down actions.
- Announce additions, removals, errors, and execution state.
- Keep visible focus after rerendering a shelf.

**Acceptance criteria:**

- [ ] The complete supported flow works with a keyboard only.
- [ ] Screen readers receive names, roles, and state for shelf items.
- [ ] Drag-and-drop remains an enhancement rather than a requirement.
- [ ] Focus does not jump to the page root after configuration changes.

### Make the workspace responsive to its container

**User expectation:** The Builder remains usable beside database, query, and scene panels.

**Current gap:** Viewport breakpoints do not reflect the actual width available to an embedded or split editor.

**Patch direction:**

- Base layout changes on the Builder container.
- Collapse to one column before shelf controls become cramped.
- Keep Run and validation feedback reachable at narrow widths.
- Test common combinations of navigation and side panels.
- Avoid horizontal scrolling for core controls.

**Acceptance criteria:**

- [x] The main Builder grid responds to its local container width.
- [ ] Every control remains usable at the minimum supported editor width.
- [ ] A narrow Builder does not compress the results into an unreadable chart.
- [ ] Embedded and full-scene layouts share the same behavior.

## P2: performance and reliability

### Keep metadata interaction fast

**User expectation:** Opening a table and searching fields feels immediate on wide schemas.

**Current gap:** Rich field metadata, value suggestions, and relationship discovery can turn the Builder into a metadata-loading bottleneck.

**Patch direction:**

- Load schema metadata incrementally.
- Virtualize long field lists.
- Cache stable metadata with explicit invalidation.
- Debounce remote search and cancel stale requests.
- Fetch sample values only after deliberate interaction.
- Set budgets for initial Builder render and field search.

**Acceptance criteria:**

- [ ] The Builder can open before all schema metadata finishes loading.
- [ ] Field search remains responsive on very wide tables.
- [ ] Stale search responses cannot replace newer results.
- [ ] Metadata failures do not erase the current query.

### Bound expensive queries

**User expectation:** Visual construction does not make unexpectedly expensive execution easier than understanding its cost.

**Current gap:** High-cardinality groupings, broad date ranges, joins, and previews can create costly queries with little feedback.

**Patch direction:**

- Reuse platform query limits, timeouts, and cancellation.
- Detect obviously unbounded configurations before execution.
- Warn on high-cardinality dimensions when metadata supports it.
- Make row limits and truncation visible in results.
- Preserve configuration after cancellation or timeout.
- Record generation and execution failure categories separately.

**Acceptance criteria:**

- [ ] A user can cancel a running Builder query.
- [ ] Truncated results never look complete.
- [ ] Timeout and cancellation preserve the previous successful result.
- [ ] Builder execution does not bypass existing query safeguards.

## P2: onboarding and documentation

### Explain the Builder's scope

**User expectation:** The product name and onboarding explain what questions the Builder can answer.

**Current gap:** The label **BI** suggests a complete business-intelligence environment, including modeling, exploration, dashboards, and governance.

**Patch direction:**

- Use **Builder** until the broader BI promises are supported.
- Describe it as a visual way to build supported SQL queries.
- Provide examples for trends, breakdowns, ranked tables, and summaries.
- Explain when switching to SQL is appropriate.
- Document the one-way conversion and save behavior.
- Link unsupported workflows to existing PostHog alternatives.

**Acceptance criteria:**

- [x] The visible mode label says **Builder**.
- [ ] Product documentation defines supported sources and operations.
- [ ] Onboarding includes at least one complete useful query.
- [ ] Conversion and persistence behavior are explained before they surprise users.

### Provide contextual help

**User expectation:** Help appears next to unfamiliar concepts without requiring a separate documentation search.

**Current gap:** Terms such as aggregation, breakdown, row, column, value, and custom expression can be ambiguous across chart types.

**Patch direction:**

- Add concise descriptions to field roles and aggregations.
- Show generated examples using public, invented data.
- Link advanced topics to durable documentation.
- Keep terminology consistent between Builder, SQL, insights, and dashboards.
- Test copy with both SQL-fluent and SQL-new users.

**Acceptance criteria:**

- [ ] Every specialized term has a nearby explanation or documentation link.
- [ ] Help text states consequences instead of restating labels.
- [ ] Examples use obviously invented, non-customer data.

## Validation and release measurement

Mode selection alone does not demonstrate that Builder solves a useful problem. Release measurement should follow the analytical task from intent to a durable result.

### Funnel

- [ ] Builder became available for an eligible user.
- [ ] Builder opened from an identifiable entry point.
- [ ] A source was selected.
- [ ] A valid configuration was completed.
- [ ] A query ran successfully.
- [ ] A result changed after an intentional configuration edit.
- [ ] The query or insight was saved.
- [ ] The saved artifact reopened in Builder.
- [ ] The result continued into a notebook or another appropriate artifact.
- [ ] A result interaction produced a successful follow-up query.
- [ ] The artifact ran again on a later day.
- [ ] The artifact was viewed or duplicated by another authorized user.

### Failure signals

- [ ] Record validation failures by control category without field values.
- [ ] Record generation failures separately from execution failures.
- [ ] Record unsupported-source and unsupported-chart encounters.
- [ ] Record mode-switch cancellation and recovery usage.
- [ ] Record abandoned configurations without capturing query contents.
- [ ] Record continuation destinations and whether their first run succeeds.
- [ ] Record drill and table interactions that lead to a successful query.
- [ ] Record engine-specific unsupported operations without source identifiers.
- [ ] Monitor editor crashes and blank-editor recovery.

### Research questions

- [ ] Which questions do SQL-new users try first?
- [ ] Which questions force successful users into SQL?
- [ ] Do users understand Rows, Columns, Values, and Filters?
- [ ] Do users expect Builder edits to survive save and reopen?
- [ ] Which field-discovery path feels fastest: click, search, or drag?
- [ ] Which missing filter operations block real work?
- [ ] Do users trust generated SQL and calculated results?
- [ ] Is a single-table builder valuable without joins?
- [ ] Should Builder live in the SQL editor or start from a table or chart workflow?
- [ ] Which product-native entry points produce useful saved work?
- [ ] When do users continue into a notebook instead of saving an insight?
- [ ] Which result-table interactions answer the next question fastest?
- [ ] Can users explain which engine ran their query and why that matters?
- [ ] What evidence makes users trust a reusable definition?
- [ ] Which recurring results need subscriptions, alerts, or embedding?
- [ ] Does AI assistance reduce time to a verified artifact rather than only time to a first query?

Research notes and telemetry examples must not include customer data in this public repository.

## Test matrix

### State transitions

- [ ] Empty SQL to Builder.
- [ ] Generated SQL to Builder.
- [ ] Manually edited generated SQL to Builder.
- [ ] Arbitrary SQL to Builder with cancel.
- [ ] Arbitrary SQL to Builder with confirmation.
- [ ] Builder to SQL without changing the Builder configuration.
- [ ] Repeated SQL and Builder switching.
- [ ] Browser back, forward, refresh, and copied URL.
- [ ] Tab duplication, closure, and restoration.

### Artifact lifecycle

- [ ] Create, save, reopen, edit, and resave a query.
- [ ] Create, save, reopen, edit, and resave an insight.
- [ ] Add an insight to a dashboard and reopen it in Builder.
- [ ] Duplicate each supported artifact type.
- [ ] Open an artifact after its source schema changes.
- [ ] Open an artifact after access to one field is removed.
- [ ] Open an artifact created by an older Builder config version.

### Query behavior

- [ ] One dimension without an aggregation.
- [ ] One dimension with one aggregation.
- [ ] Several dimensions and aggregations.
- [ ] Each supported aggregation and field type.
- [ ] Each supported filter operator and field type.
- [ ] Null, empty, zero, negative, and high-cardinality values.
- [ ] Date buckets across timezone and daylight-saving boundaries.
- [ ] Multiple sorts and stable tie ordering.
- [ ] Limits, empty results, truncation, timeout, cancellation, and query failure.

### Visualization behavior

- [ ] Valid minimum configuration for every visualization.
- [ ] Too few, too many, and incompatible fields.
- [ ] Switching between compatible visualizations.
- [ ] Switching between incompatible visualizations with confirmation.
- [ ] Long labels, null series, large values, and empty results.
- [ ] Narrow editor, wide editor, side panels, and embedded layouts.

### Accessibility

- [ ] Keyboard-only construction and execution.
- [ ] Screen-reader field selection and shelf navigation.
- [ ] Visible focus during asynchronous updates.
- [ ] Error announcements and result-loading announcements.
- [ ] Reduced-motion behavior for drag and chart transitions.
- [ ] Contrast and zoom at supported levels.

### Data sources

- [ ] PostHog event and person data through HogQL.
- [ ] Supported warehouse tables through HogQL.
- [ ] Every external connection explicitly offered the Builder.
- [ ] Raw-query connections confirm that Builder remains unavailable.
- [ ] Capability changes degrade gracefully for saved artifacts.

### Workflow continuity

- [ ] Open Builder from a supported product-data context.
- [ ] Remove or change inherited context without hidden filters remaining.
- [ ] Continue a successful result into a notebook.
- [ ] Reopen the originating Builder artifact from the notebook.
- [ ] Save the same exploration as an insight and dashboard item.
- [ ] Add a filter and sort through result-table interactions.
- [ ] Drill from an aggregate result to permitted underlying rows.
- [ ] Return to the parent result without reconstructing the query.
- [ ] Preserve engine, connection, parameter, and permission requirements across transitions.

### Trust and collaboration

- [ ] Save concurrent edits from two browser sessions.
- [ ] Review a meaningful diff of filters, measures, joins, and sources.
- [ ] Promote an eligible revision from exploratory to trusted.
- [ ] Change trusted logic and require renewed review.
- [ ] Deprecate a definition used by existing Builder artifacts.
- [ ] Resolve a comment attached to a stable Builder control.
- [ ] Remove access while another user has the artifact open.

### Delivery and assistance

- [ ] Schedule a recurring result with visible freshness.
- [ ] Deliver a parameterized result without exposing hidden values.
- [ ] Fail a recurring query and notify its owner safely.
- [ ] Render an embed under its intended sharing policy.
- [ ] Generate a Builder proposal from authorized semantic context.
- [ ] Reject, apply, and undo an assisted configuration change.
- [ ] Repair an engine-specific error without changing query meaning unexpectedly.
- [ ] Save an assisted answer as a durable artifact.

## Reference patterns

These products are references for interaction patterns, not requirements to reproduce every feature:

- [Metabase query builder](https://www.metabase.com/docs/latest/questions/query-builder/editor) uses staged data, join, expression, filter, summarize, sort, and visualization steps.
- [Metabase joins](https://www.metabase.com/docs/latest/questions/query-builder/join) expose related data and join conditions within the visual flow.
- [Metabase drill-through](https://www.metabase.com/docs/latest/questions/visualizations/drill-through) connects a rendered result to filtered and underlying data.
- [Looker Explore](https://docs.cloud.google.com/looker/docs/creating-and-editing-explores) centers reusable dimensions, measures, pivots, filters, and modeled relationships.
- [Power BI report editor](https://learn.microsoft.com/en-us/power-bi/create-reports/service-the-report-editor-take-a-tour) supports field search, click or drag placement, and visualization-specific field wells.
- [Power BI filters](https://learn.microsoft.com/en-us/power-bi/create-reports/power-bi-report-add-filter) distinguish visual, page, report, drill-through, and URL filter workflows.
- [Power BI interactions](https://learn.microsoft.com/en-us/power-bi/explore-reports/end-user-interactions) connect chart selection, cross-filtering, drilling, sorting, and detail exploration.

## Suggested implementation order

1. Land editor lifecycle safety and durable Builder persistence.
2. Define mode-conversion semantics and retain recovery snapshots.
3. Publish the source and visualization capability matrix.
4. Make engine behavior and unsupported operations clear.
5. Add a searchable field picker and chart-aware field wells.
6. Complete common filters, calculations, and multiple sorting.
7. Add product-native starting points and a durable notebook handoff.
8. Add interactive tables, preview, drill-down, and underlying-row exploration.
9. Choose joins, curated semantic models, or a deliberate combination.
10. Add reusable measures, parameters, governance, and revision behavior.
11. Add collaboration, delivery, and semantic-grounded assistance after the artifact contract is stable.
12. Validate accessibility, performance, workflow continuity, and artifact compatibility.
13. Expand the flag only when verified artifacts and return use demonstrate value.
