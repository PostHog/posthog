---
title: Working with data warehouse
sidebar: Docs
showTitle: true
---

This is an internal guide to setting up and working with the data warehouse for PostHog engineers. If you're a PostHog user, check out our [data warehouse docs](https://posthog.com/docs/data-warehouse) instead.

Projects with a connected warehouse source or warehouse table use ordinary empty insight results, even before ingesting events. They do not show sample-data placeholders or the project-wide "This project has no events yet" notice. Both onboarding messages wait until the warehouse setup check confirms no sources or tables exist; an unavailable check does not imply an empty project.

Onboarding only checks warehouse setup for non-demo projects without events. Source detection returns an existence flag without serializing schemas, and table detection omits columns. Navigation refreshes an empty result so returning after source creation opens the Sources list.

## Model namespace reservation

The shared PostHog catalog reserves `models.*` for authored data models. New warehouse tables, endpoint saved queries, and managed viewsets cannot claim that namespace. The bare name `models` is reserved for the namespace container; use a name such as `models.revenue` for a model. Names such as `models_v2` remain available. Saved queries with no origin are treated as authored models for compatibility.

Existing reserved-name rows remain queryable, editable, and deletable. Model validation enforces the reservation on creation and renaming, during saves and `full_clean()`. Authored models can use private materialization backing tables with their model names.

Direct-connection catalogs contain no authored models and are exempt from the reservation. Upstream tables and schemas named `models` remain available there, including case variants resolved by Snowflake and Trino.

This reservation does not add qualified names to existing models or require a namespace on new models.

## Model materialization usage

The Models **Usage** tab shows bytes read, CPU time, and run counts for materializations over a preset or custom range of complete UTC days.
The totals and model breakdown follow saved-query access controls. The breakdown sorts by bytes read and includes soft-deleted models while their saved queries and job history exist.
Usage includes schema checks, retries, failed runs, and canceled runs, and is attributed to the UTC day each run finished.
The date and materialized-view filters apply to the whole tab. The jobs table also has a status filter. Projects with the Trino managed warehouse enabled also get a tab-level engine filter, daily bars stacked by engine, and separate ClickHouse and managed warehouse byte totals per model. Legacy Duckgres runs are not included.

A daily partitioned Dagster job, `model_job_usage_job`, collects usage from the regional query log archive at 03:00 UTC for the previous day.
It stores totals on `DataModelingJob`, keeping usage reads independent of query-log retention and leaving the streaming materialization path unchanged.
The collector matches team, workflow ID, and workflow run ID, and leaves ambiguous or missing matches unmeasured.
Re-running a partition replaces totals rather than adding them.
Runs that start outside the supported 14-day archive backfill window remain unmeasured.
Runs that cross midnight include queries from the full run.

Unmeasured usage is null, including historical jobs with no archive data, and the tab reports how many runs have measurements.
The totals cover measured runs only; missing measurements and days without measurements are not shown as zero.
The current UTC day is excluded because usage is updated daily.
These measurements describe query work and are not billing amounts.

## SQL editor drafts

Saving a view infers its column types with LIMIT 0 on the outer SELECT branches and explicit IN subqueries.
Scalar subqueries can still read data, so column inference shares the organization's foreground query concurrency limit.
API-key requests and background jobs retain the query runner's existing exemptions from that limit.

The SQL editor keeps unrun edits in browser storage, scoped to the user, project, and saved query. Explicit logout clears these drafts.
An **Edited** label marks changes to a saved view or insight. **Discard changes** restores the saved copy already loaded in memory, then refreshes it from the server. The refresh preserves edits made after discarding.
Insights can be saved or updated before running the SQL. Updating a view still requires a successful run of the current SQL so its result types match the saved query. **Continue in a notebook** is in the update button's dropdown for saved views and insights.

The data warehouse sidebar lets you rename saved views. The dialog lists references from data model lineage. Renaming does not update SQL references in saved views, materialized views, endpoints, insights, dashboards, notebooks, or external systems.

Returning to a notebook can reuse completed query results from the last two minutes in the same browser session. Saved insights still fetch their latest definition; changed queries load their own results. Explicit **Run** and refresh actions fetch results again. This browser cache is bounded and excludes shared notebooks, errors, incomplete responses, and large results; it does not change server cache freshness.

## Choosing data in Business intelligence

Business intelligence is in beta. The product has a beta label, and the worksheet index shows a dismissible notice with a **Send feedback** button. To collect feedback, launch a survey with **Feedback button → Custom** presentation targeting `#business-intelligence-feedback-button` in the project that collects the app's analytics. No survey ID is needed in the frontend.

**Business intelligence** lists saved worksheets at `/bi` when the `sql-editor-bi-mode` feature flag is enabled. Search all worksheets or switch to those viewed in the last 30 days. **New worksheet** opens `/bi/new`; selecting a saved worksheet opens `/bi/<short_id>` in edit mode. The project tree's **New → Worksheet** entry opens the same editor. Worksheets retain their insight identities and folder placements, but use their own file subtype and no longer appear in the Product analytics insights list. Legacy `/bi?open_insight=...` links and shared worksheet URLs still open the editor. Business intelligence and SQL keep separate unsaved working copies, and existing SQL editor links with `mode=bi` open in Business intelligence.

Choose a connection in the **Data** panel, then select a table below it. Certified sources have a checkmark beside their table icon and appear in a separate **Certified sources** folder. All table folders can be expanded and collapsed, including while searching. Deprecated sources have a warning icon. Hover over either status icon for details. Deprecated and uncertified sources remain selectable; search preserves the same ordering. **Run** is the first toolbar action, before **Swap rows and columns**.

**Charts** opens chart types and series controls in the right panel. **Analysis** and the visualization settings button replace that panel with their own controls. The panel starts closed. Close it after editing to return to the chart. The Series/Display settings use the same panel and scroll independently. Row filters appear once above the chart; click a filter to edit it. **AND / OR groups** opens the grouping dialog, and **Result filters** opens a popover. The left pane contains the selected source and its dimensions and measures; **Fields** hides or restores it. The toolbar wraps as the worksheet narrows, and the right panel overlays the chart when there is not enough space to dock it. These layout changes apply only to BI worksheets; SQL and other insights retain their existing settings layout.

**Separate panes by** in the Series panel splits a bar, line, or area chart by one or more shelf dimensions. For example, put Year into panes, Quarter on the chart axis, and Region on Color. Drag the selected pane dimensions to change their heading order. Every pane uses the same color mapping and category positions. Missing combinations remain gaps unless **Show nulls as zero** is enabled.

Panes share their value scale by default; **Independent value scales** lets each pane scale separately. Charts with a secondary value axis use independent scales. Reference lines can calculate **Within each pane** or **Across the worksheet**; worksheet calculations use all returned marks, including panes beyond the display cap. Panes support up to 24 charts, 1,000 axis values, and 50 measure/color series, with explicit messages when those limits apply. Narrow worksheets stack the panes. Saved worksheets, shared views, and dashboard tiles retain the layout and apply dashboard filters before splitting the result; each pane uses the same query response. Period comparison must be turned off to use panes.

**Add filter** offers searchable table fields alongside a custom expression option. Value filters retain loaded choices while refreshing so you can select several values without waiting for the list to reload. Closing an untouched custom filter discards it.

Use **Add calculated field** beneath Measures or **+ Field** on a shelf. The editor shows SQL validation progress and infers the return type; you can override the type of a dimension. Cmd+Space (Ctrl+Space on Windows or Linux) opens field autocomplete.

The Series panel accepts custom colors for individual breakdown values. Display settings control value-label placement, background, size, and rotation, and bar spacing can be set to **None** for adjoining bars. The legend-position selector sits beside its label.

Single-value filters distinguish selecting **(empty string)** from clearing the input: the former matches an empty value, while the latter removes the condition.

Date dimensions sort oldest first by default, including in tables; explicit sorts still take precedence. Generated date dimensions retain their result-column identity, including expressions over column names containing spaces. Time charts show years at the start of each year below their date ticks, omitting labels that would overlap. Axis settings let you enter a date format such as `MMM YYYY` or `YYYY-MM-DD` and rotate tick labels. Hiding ticks preserves the axis title. Clicking a bar opens the drill-down options for that result.

**Auto update** is off by default and remembers your choice. Selecting a table leaves a blank worksheet, even with auto-update enabled. The blank worksheet offers **Start with daily row count** when a date field is available, or **Start with row count** otherwise. The suggestion adds fields only when clicked and respects auto-update. Identifier fields such as `person_id`, `distinct_id`, and `user_id` appear as measures and default to Count; their shelf menu can convert them to dimensions or change the aggregation. A worksheet with dimensions and no selected measure shows **Count of rows** on its shelf and value axis. Turning auto-update off keeps the current result; **Run** applies pending changes.

Choose **Rename** from a shelf field's menu to change its worksheet label without changing the source expression. Labels persist in saved charts and tables without changing dashboard filter bindings or custom axis titles. Click an axis on a line, area, or bar chart to edit its label and tick visibility directly; value axes also offer scale and zero-baseline controls. **Save axis** applies chart settings to the displayed result without running pending shelf or filter changes. Cancel or the close button discards the draft. The same labels remain editable in visualization settings.

**Clear sheet** clears shelves, filters, chart settings, and results while retaining the selected table, connection, date scope, and worksheet-local field definitions. Drag pills onto another pill to reorder them. **Swap rows and columns** exchanges dimensions and measure placement, preserving calculations and sort choices; bar charts switch between vertical and horizontal orientation. The **Charts** picker offers chart types suited to the selected fields.

The **Charts** picker also includes proportion bars, scatter plots, and box plots. Scatter plots initialize numeric axes and need at least two numeric columns; box plots need six numeric summary columns. With two measures, **X measure** and **Y measure** choose the axes. Dimensions on Rows and Columns define point detail, including a dimension selected for Color. Without dimensions, the measures form one aggregate point. Category colors remain stable when results reorder, and aliases do not change category identity. Missing coordinates are omitted; logarithmic axes require positive coordinates.

In the BI editor, click scatter points to toggle selection or drag a rectangle in **Select points** mode. **Keep only** adds the selected dimension tuples to worksheet filters, preserving existing AND/OR conditions; it supports up to 200 result rows. **Undo** restores the prior filters. **Zoom area** changes only the viewport; **Reset zoom** restores it. Selection controls are absent from saved/read-only and shared charts, and are unavailable while query edits are pending.

Drag the right edge of the fields pane to resize it. Docked panes each take at most a quarter of a wide worksheet, leaving at least half the width for the chart. Less frequent worksheet actions, including **Save a copy**, **Save as SQL view**, and **Discard changes**, are in the worksheet actions menu beside **Share**.

BI usage keeps the existing `sql-editor-bi-mode-selected`, `sql-editor-bi-query-run`, and `sql-editor-bi-query-saved` events. Their properties describe table calculations, Top N, comparisons, formatting, axes, totals, and related/property field counts. The `bi-worksheet-action` event's `action` property defines the funnel: `opened`, `source_selected`, `first_chart`, `saved`, `added_to_dashboard`. The first chart is the first nonempty successful result per editor visit; reruns and failures do not count again. Saved and dashboard steps include `insight_id`. Additional actions record drill-down choices, related-table expansion, property browsing/search, calculated-field saves, and changed chart-setting keys. These events exclude SQL, source names, field names, formulas, search text, filter values, and result contents.

**Undo** and **Redo** restore shelves, filters, calculations, formatting, chart settings, and worksheet names. The editor keeps the last 100 changes during a visit; opening another worksheet or discarding changes starts a new history. Use Cmd/Ctrl+Z and Cmd/Ctrl+Shift+Z outside text inputs. Undo respects **Auto update**: with it off, click **Run** to refresh results. **Save a copy** creates a separate worksheet and opens it in the editor without changing the original or copying its dashboard placements. Copy failures leave the original and your edits in place. Usage tracking adds `undo`, `redo`, and `copied` actions.

For older saves without worksheet configuration, discarding query edits preserves the current source and shelves.

Choose **View SQL** from the worksheet actions menu to inspect and copy either the current worksheet query or its last-run query. Pending changes are labeled. The SQL includes the extra result group used to detect truncated results. **Open in SQL editor** opens an unsaved SQL tab with the selected query's connection, filters, variable values, and query options intact. It does not run the query or create a warehouse view. Copying SQL copies the text only; the preview lists its query parameters separately. Relative date ranges are evaluated again on the next run.

SQL query-scan advisories are hidden in Business intelligence. Query errors and warnings about stale sources or restricted data remain visible.

Saving a worksheet preserves its connection, table, shelves, measures, filters, chart type, limit, sort order, and visualization settings in a `BIVisualizationNode`. The wrapper contains the worksheet configuration and a plain `HogQLQuery` source. Member aliases, filter labels, ungrouped member handling, and hierarchy drill paths are optional saved definitions; existing worksheets keep their defaults. Saving keeps the worksheet in the BI editor; dashboard tiles can still use the normal insight view. **Edit** reopens Business intelligence when the feature is enabled, including from a dashboard. Leaving a worksheet with unsaved edits asks for confirmation, including when returning to **Worksheets**. **Discard changes** restores the saved worksheet. **Save as SQL view** exports only the generated SQL to a warehouse view; save a worksheet to retain editable worksheet state.

Older saves containing only SQL still open in the SQL editor. Their original shelves cannot be reconstructed without the worksheet configuration from a draft or shared URL.

The worksheet date picker supports rolling windows, fixed ranges, this/last month and quarter, and year to date. **Date** selects the column that receives dashboard date ranges; **No date column** explicitly opts out. A dashboard range replaces the worksheet range. Dashboard property filters combine with worksheet conditions. Event-based tables retain standard PostHog property filtering with any date-column selection, using `{filters.native(date_expression)}` or `{filters.native(null)}` when overriding the default date column. Other tables bind dashboard property keys to worksheet fields, including the property key in a field such as `properties.plan`. Unmapped or ambiguous property keys produce a query error instead of silently applying the wrong filter. Reopen and save older BI worksheets to update their generated SQL with dashboard-aware placeholders.

The comparison picker adds the previous period or a custom offset, including one year earlier. Tables, KPI cards, bar, line, and area charts support comparisons with up to two dimensions. Previous-period dates align to the current axis, and the legend identifies each period. Tables and KPI cards show current, previous (or comparison), absolute change, and percentage change for each measure. Percentage change divides the difference by the absolute previous value; a zero or missing previous value displays an empty percentage. A missing period remains empty rather than being inferred as zero. Click current or previous values to explore that period's rows. Both periods use the effective dashboard date range and property filters. Comparisons require a bounded range and turn off when the worksheet switches to all time or an unsupported chart.

Generated comparison queries use `{filters.previous}` (or its column-bound form) for the comparison range and `{filters.compareDate(expr)}` to align date dimensions. Custom native date columns use `{filters.previous.native(expr)}`. Month, quarter, and year dimensions pass their bucket as a second argument to `compareDate`, so month lengths and leap years do not move points into the wrong bucket. `HogQLFilters.compareFilter` supplies the comparison offset; missing offsets use the previous period.

Use the table picker in the data pane to browse PostHog, warehouse, view, and system tables, with direct-connection tables grouped by schema.
The selected table is highlighted; expanding a folder does not select it.
Direct connections group tables by schema. Search matches table and folder names without changing the sidebar search.

**Related tables** exposes existing lazy joins, virtual tables, and configured warehouse joins as expandable nodes. Fields reached through a relation keep the original source and a qualified path, so adding a customer's field to a charges worksheet does not switch tables. PostHog property fields, including `person.properties` under events, expand into searchable, paginated property definitions. Numeric definitions become measures; other definitions become dimensions. Restricted and hidden properties are excluded. Warehouse relationships use the existing join configuration; the worksheet does not create joins or infer arbitrary JSON keys.

**Search fields** also searches property definitions in the selected table and expanded related tables. Search for `$browser`, `$pathname`, or a custom property name to open matching property groups, then drag or double-click a property onto a shelf. Clearing the search restores each group's previous expansion and local search. Searching for a group's name, such as `properties`, shows all its definitions.

## Calculated measures in BI mode

Choose **Edit measure expression** from a measure pill to edit its SQL and aggregation together. The editor shows the aggregation applied to each group. Choose **Custom SQL · no extra aggregation** when the expression already contains aggregate functions, such as `sum(revenue) / nullIf(count(), 0)`. This uses the expression directly without wrapping it in Count or Sum. Changes apply together when you select **Update SQL expression**; closing the editor discards the draft.

Worksheet tables offer **Conditional formatting** beside the visualization settings button. It opens the same rule editor used by SQL insights. Rules apply to the table and persist with the worksheet, so copying its query into another insight is unnecessary. This control applies to tables, not pivot tables or charts.

Chart settings offer **Reference lines** for BI line and bar charts. Add a constant target, or choose **Mean**, **Median**, **Minimum**, or **Maximum** across returned marks on the left axis. **Per series** calculates a separate reference for each color group or measure and includes its name in the label. Calculated lines update with the results, after aggregation and table calculations; they exclude missing values and respect result limits. They do not re-aggregate the underlying source rows or apply to the right axis. Calculated lines are hidden on 100% stacked charts, where constant percentage targets remain available.

The **Marks** card offers table calculations per measure: percent of total, running total, difference or percent change from the preceding point, trailing moving average, and rank. **Compute using** selects the dimension to traverse, with the date dimension chosen by default; other dimensions partition the calculation. Moving averages use a trailing window including the current point, in ascending order. Partial windows average available non-null values; **Require a full window** leaves the result empty until every point in the window has a value. Calculations run before the result limit, and zero denominators produce empty cells.

**Analysis → Missing dates** defaults to **Observed points only**. **Show gaps** creates empty buckets that occupy a point in the window but do not contribute to an average. **Fill with zero** makes those buckets contribute zero. Filling runs before calculations, separately for each series and comparison period, across the selected date range. It requires one bucketed date dimension matching the worksheet date column and a bounded range. It is available for project and warehouse tables in tables and time-series charts; direct connections do not support it. Saved worksheets and dashboard date overrides retain these semantics.

**Table** automatically uses a pivot layout when **Columns** contains dimensions, including when **Rows** contains only measures. Row members run down the table; column members run across it. Measures placed on **Rows** appear vertically, and measures placed on **Columns** appear beneath each column header. Measures split between both shelves appear as columns with guidance to place them together. Move all dimensions onto **Rows** to return to a flat table. Period comparisons keep their comparison table layout. Direct database connections keep the flat table layout. Large pivots virtualize rows and columns while retaining grouped headers and the sticky row labels. Pivots support up to 10,000 measure columns and 100,000 displayed rows, including measures on Rows. Larger results ask you to reduce dimensions or measures, or use Top N. Text-valued custom aggregates retain their values. The explicit **Pivot table** chart uses the same pivot layout. Expand or collapse a row or column header to move between hierarchy levels. Collapsed values are reaggregated from source rows, including averages and distinct counts. **Subtotals** also shows the intermediate aggregates while expanded. Row and column grand totals retain their separate controls, and total cells keep drill-down scoped to the visible dimensions. Expansion is local to the view; the worksheet's shelves and settings remain unchanged. Tracking records hierarchy expansion with axis and depth, and adds missing-date and full-window settings to the existing worksheet events.

**Hierarchies** in the data pane names an ordered set of dimensions, such as Country → State → City. Create a hierarchy with 2–10 levels, then start it on rows or columns. The level list marks the current field and shows the next levels. Selecting a result offers **Drill to** the next level in the current editor worksheet, retaining parent filters, date range, measures, variables, and formatting. The path above the result offers **Drill up**, removing only filters introduced by that drill. Navigation participates in undo/redo and respects Auto update. Changed or removed hierarchy levels disable an incompatible return path. Outside the editor, the action explicitly opens a new worksheet. Leaf values and levels already on a shelf do not offer another drill action; nested pivot expansion remains available for those shelves. Definitions stay with the saved worksheet and survive **Clear sheet**. **Import from worksheet** copies a hierarchy from an accessible saved worksheet using the same table and connection. The copy is independent: edits do not change the source worksheet or create global fields. Deleting a local calculated field removes its uses from hierarchy levels, dropping definitions with fewer than two remaining levels.

The **Analysis** card ranks **Top N** categories by a selected measure across the full current date range. **Include "Other"** combines the remaining source rows and re-aggregates them, including averages and distinct counts. Removing the ranking measure turns Top N off. Previous-period comparisons use the current period's category selection. Tables offer a grand total; pivot tables offer row and column grand totals. Both support hierarchy subtotals when an axis has multiple dimensions. Totals re-aggregate source rows; table-calculation cells remain blank on total rows. Summary rows can occupy at most half the result limit, reserving room for detail cells. The BI visualization requests an extra row to determine whether more results exist, then removes it before building tables and charts. Saved SQL and exports retain the worksheet's configured limit. A notice identifies confirmed extra groups. New worksheets default to 50,000 aggregated rows. At the 50,000-row execution cap, it instead says more groups may exist because the extra-row probe cannot complete. The **Aggregated rows** limit applies after aggregation, not to scanned source rows. Limited results can make totals, rankings, running totals, and comparisons incomplete; narrow filters or increase the limit where possible.

Each measure's **Format and display** dialog sets its label, currency, decimal precision, abbreviation, percentage format, and suffix. Percentage formatting expects fractional values (0.25 displays as 25%); percent-of-total and percent-change calculations produce that scale automatically. Formats persist in saved insights and apply to charts, tables, and pivot cells. The **Charts** panel exposes series style and left/right axis selectors for each measure. Bar, line, and area charts support these mixed styles and axes. **Combine line + bar** assigns two measures to separate axes with bar and line styles.

In the worksheet editor, click a bar, line point, table cell, or pivot cell to explore its source rows. **Filter in new worksheet** preserves the original insight and adds the selected dimensions to a new worksheet. **View underlying rows** loads up to 1,000 matching source rows before aggregation; **Open in SQL editor** carries the same conditions, connection, and effective dashboard filters. When adding a drill-down condition would exceed the filter-group nesting limit, use **View underlying rows** or **Open in SQL editor**. Total cells omit rolled-up dimensions, and **Other** selects the categories outside the current Top N. Comparison-period points open rows from their original dates; their filtered-worksheet action is disabled to avoid combining current dates with prior-period conditions. These actions are unavailable on public shared insights.

On authenticated dashboards in view mode, right-clicking a chart result opens a context menu beside the pointer. A left click keeps its usual action, such as opening the people modal, pinning a multi-series tooltip, or opening the BI drill-down dialog. Right-clicking a link or an input keeps the browser menu. Chart tooltips stay hidden until the menu closes. BI worksheets offer **View underlying rows**, then **Open in SQL editor**. Product analytics datapoints offer **View people**, **View recordings** when the existing drilldown selects matched recordings, then **Open in SQL editor**. Lifecycle results offer people and SQL only: their actor query identifies bucket members without projecting matched events. The people and SQL actions preserve the selected date, breakdown, and aggregation. SQL and recording links become available after the selected actor rows load. Selecting another result or closing the menu cancels any pending query. Recordings use matched session IDs; when no sessions match, the recordings action stays disabled. A left click, Escape, or a click outside closes the menu. Right-clicking another result moves the menu to it. Native links support opening actions in another tab. Exploration actions do not change dashboard filters or create saved insights. Public shares, embeds, exports, and layout editing retain their existing behavior.

BI worksheet menus and the left-click **Explore this result** dialog offer **Filter dashboard by this result** for current-period dimension values. The dialog offers **Remove filter** when that result is already selected, and disables filtering for unsupported results. The selection filters other BI worksheets using the same table and connection, combining with their existing conditions before aggregation. The source worksheet retains its full results. Each insight card header shows its filter status beside the title, before the menu; the status stays visible when the title is truncated. Cards unaffected by the active BI filter dim to 30% opacity; the source and matching worksheets remain fully visible. Clearing the filter restores all cards. The BI selection appears beside the existing dashboard filters and unsaved-filter controls. Click it to see the source worksheet and affected count, or use **Clear BI filters** or **Remove filter** to restore the saved results. Selections persist in the dashboard URL without changing saved insights, including when dashboard dates or variables change. Changing the source worksheet's table, dimensions, comparison period, or Top N configuration clears the selection. Product analytics, raw SQL visualizations, query snapshots, public shares, embeds, exports, and layout editing do not participate. Grand totals, previous-period results, and Top N **Other** remain available for exploration only.

**Compare previous period** turns date comparison on or off in one click. The adjacent comparison picker still supports custom offsets. Select a bounded date range before enabling comparison.

With `SQL_EDITOR_BI_MODE` enabled, choose **Add calculated field** in the data pane or the plus button on Rows or Columns. Nothing is added until **Add field** is clicked; Cancel or the close button discards the draft. A shelf's plus button places the saved field on that shelf. Select a row-level dimension or an aggregate measure, then enter a name and a plain HogQL expression using fields from the selected table. Dimensions can use expressions such as `coalesce(properties.plan, 'Unknown')`; measures can use `sum(revenue) / nullIf(count(DISTINCT user_id), 0)`.

Calculated fields appear in Dimensions or Measures with a ƒ indicator. Drag or double-click them to reuse the definition. Editing a definition updates its name and expression on every shelf, including duplicated uses; date granularities and measure display settings remain independent. A field's role cannot change after creation. **Delete field and all uses** removes the local definition and its shelf/filter uses; Undo restores them. Clear sheet retains the definitions. Save, reload, and Save a copy preserve them inside the worksheet, without creating source-table or project-wide fields.

The result footer reports distinct dimension groups and non-empty measure values, rather than source-row counts. It excludes total rows and marks truncated results as limited. Grouping labels and the expandable **Applied filters** summary describe the executed query while edits await Run. The summary includes source property filters carried by the executed query, retains nested AND/OR groups, separates source-row filters from post-aggregation conditions, and omits disabled or empty conditions. Missing dimension columns produce an unavailable group count and a visible warning instead of a misleading single group.

Date and timestamp drops start with daily buckets. A date pill offers **Timeline (keeps the year)** buckets and **Date part (combines years)** choices: month of year, quarter of year, and day of week. **Duplicate** creates an independently configurable shelf field, so the same date can appear at two granularities. Hold **Alt** (**Option** on Mac) while dragging a dimension or measure to copy it to another shelf or position. Copies retain calculations and settings; dropping with the modifier outside a shelf leaves the original in place.

**Charts → Series → Color** separates series coloring from shelf grouping. **Single color** preserves every group and series while using one color; switching back restores automatic or customized colors. With two categorical dimensions, select either field to define the colored series and use the other on the axis. Date dimensions remain on the timeline. Automatic uses lines for dates, grouped bars for one or two categorical dimensions, and a number for a single total. Explicit chart choices remain selected. **New worksheet** is available directly in the worksheet header.

**View source data** in the data pane opens a raw sample even before fields are added. Choose all source rows or rows matching worksheet row/date filters. Samples start at 1,000 rows and can grow to 10,000; result filters and table calculations do not apply. Repeated identifiers remain separate records, and a sample does not establish uniqueness. Closing the preview leaves the worksheet unchanged.

Choose **Edit display aliases** from a field's menu to map individual raw values to worksheet-local labels. Search and load more values, then Save aliases or Cancel. The editor shows 50 members per page; search covers all saved aliases, and paging retains unsaved edits. Closing the editor or replacing its search cancels the outstanding value query. Clearing a label restores the raw value. Null and empty strings have separate entries; duplicate aliases retain separate groups. Aliases apply to table cells, chart labels, legends, tooltips, and equality or membership filter descriptions. Substring conditions and range bounds display their raw operands. Queries, sorting, selection, and data exports retain raw values. Aliases survive save/reopen, copies, and Clear sheet.

## Filters in BI mode

Row and result filter editors have an independent **Filter name** with **Reset name**. A custom title changes neither the source field nor its conditions, and persists with the worksheet and undo history.

Drop a field onto **Row filters** above the chart. Click its pill to edit values and settings. String fields start with
**Is any of**: select several values, or type a value and press Enter. **Is none of** excludes the
selected values. An empty selection leaves all values included. Suggestions load when the picker
opens, respect the other applied filters, and show up to 100 distinct values; additional values can
always be entered manually. Single-value conditions, including **Equals**, offer the same searchable suggestions for text and numeric fields. Date conditions retain their calendar picker, and ranges retain separate bounds.

Use **Between** for numeric or date fields. Both bounds are inclusive, and either can be left empty
for an open-ended range. Date-time fields include the time. Uncheck **Apply filter** in the editor to temporarily
ignore a filter without losing its settings. Click the field pill to edit the field expression, date
part, or custom SQL condition, or to remove the filter. Filter changes respect the worksheet's
auto-update setting and are preserved with its saved configuration.
Numeric filters preserve the precision of entered values. Invalid numbers show an error and prevent the worksheet from running until corrected or disabled.

**Row filters** apply before aggregation. **Result filters** apply to aggregated measures, calculated measures, and table calculations after they run, before sorting and the final row limit. For example, add result filters for revenue greater than 1,000 and purchase count at least five. Each filter can be disabled without removing it. Removing a measure removes its result filters; the remaining filters keep their measure assignments. If a filter or Top N uses the default Count, adding another measure keeps Count on the worksheet so that condition keeps its target.

Both cards have **AND / OR groups**. Choose **AND (match all)** or **OR (match any)**, add nested groups, and move existing filters into them. Empty groups have no effect. Ungroup moves its conditions and nested groups into the immediate parent group. Existing worksheets retain their flat AND conditions. Date ranges and dashboard filters always combine with worksheet row conditions using AND; drill-down selections do too.

Top N selects categories before result filters run. Comparison periods apply the same result conditions independently. Result filters hide detail groups; totals still aggregate all data matching the row filters. Table calculations use the full aggregated result before result filtering. Query usage events include result-filter and group counts without their values.

## Marketing analytics cost charts

The `marketing-analytics-costs-precomputation` flag controls whether the cost trend can use precomputed costs.
The backend checks materialization jobs for every displayed source over the requested date range and comparison period.
It uses precomputed costs only when all windows are ready and unexpired.
An in-progress refresh can temporarily route the chart to the original sources until coverage is ready.
Opening the chart as an editable insight uses its original source series without the automatic precompute selection.
Completed windows with zero rows count as covered.
Missing, expired, inaccessible, or unmaterializable sources use the original live warehouse series for the whole chart.
Coverage check errors also fall back to the live query.
This read-only check does not start or wait for materialization jobs.

## Apple Ads in Marketing analytics

Marketing analytics support is controlled by the boolean organization flag `marketing-analytics-apple-ads` and is off by default.
Enable the flag for an organization to show the integration and include its data in live and precomputed marketing queries.
Disable it to stop using the integration in Marketing analytics without deleting the connection or its imported data.
Data warehouse syncs continue independently of this flag.

Sync `campaigns` and `campaign_report` to include Apple Ads in Marketing analytics.
Sync `ad_groups` and `ad_group_report` to enable the ad group breakdown.
Apple Ads does not provide an ad-level report through this connector.
Taps appear as clicks, and installs appear as reported conversions.
The adapter accepts both Campaign Management API 5 `installs` and Ads Platform API `totalInstalls`, including tables that contain rows from both versions.
Spend uses the currency in Apple's `localSpend` object and the reporting date to convert into the project's currency.
Apple does not report conversion revenue through these reports, so reported conversion value is zero.

## OpenAI Ads in Marketing analytics

Marketing analytics support is controlled by the boolean organization flag `marketing-analytics-openai-ads` and is off by default.
Enable the flag for an organization to show the integration and include its data in live and precomputed marketing queries.
Disable it to stop using the integration in Marketing analytics without deleting the connection or its imported data.
Data warehouse syncs continue independently of this flag.

Sync `campaigns` and `campaign_insights` to include OpenAI Ads campaign delivery in Marketing analytics.
Spend is already in major currency units; the importer adds `currency_code` from the account metadata so reports can convert spend at each bucket date.
Existing connections need a full resync of `campaign_insights` to populate currency on historical rows.
Without the currency column, cost tiles are unavailable and the campaign table excludes the source.
The dashboard and source settings show a warning with a link to the affected warehouse source and instructions to fully resync `campaign_insights`.
Queries with empty historical currency values stop with a resync message.
Reported conversions and revenue are zero because the importer currently requests delivery metrics only.
Ad groups and individual ads are not included in the native integration.

## Source warnings in Marketing analytics

The dashboard and source settings show validation errors for connected native and mapped external sources.
They use the same adapter validators as campaign queries, so warnings follow each integration's supported checks without a separate frontend list of required columns.
Warnings identify the affected connection and link to its settings.
Mapped sources with missing required column mappings remain visible in these warnings until corrected.
The dashboard also shows missing or disabled required tables and running, failed, paused, or cancelled syncs.
Reload the dashboard after correcting the configuration or resyncing a table to refresh validation.
This check uses table metadata and configuration; it does not scan imported rows for data quality issues.
Query execution errors still appear on the affected dashboard tile or table.

## Amazon Ads in Marketing analytics

Marketing analytics support is controlled by the boolean organization flag `marketing-analytics-amazon-ads` and is off by default.
Enable the flag for an organization to show the integration and include its data in live and precomputed marketing queries.
Disable it to stop using the integration in Marketing analytics without deleting the connection or its imported data.
Data warehouse syncs continue independently of this flag.

Sync `sp_campaigns` and `sp_campaign_reports` to include Sponsored Products campaigns in Marketing analytics.
Spend uses `cost`, with currency conversion at each report date using `campaign_budget_currency_code`.
Reported conversions and revenue use the 14-day purchase and sales metrics; the other attribution windows are not added to these totals.
Sponsored Brands, Sponsored Display, ad groups, and individual ads are not included because the importer does not provide their performance reports.

Monetary tiles require the report date and currency columns; reports without currency can still supply impressions and clicks.

## Rokt Ads in Marketing analytics

Marketing analytics support is controlled by the boolean organization flag `marketing-analytics-rokt-ads` and is off by default.
Enable the flag for an organization to show the integration and include its data in live and precomputed marketing queries.
Disable it to stop using the integration in Marketing analytics without deleting the connection or its imported data.
Data warehouse syncs continue independently of this flag.

Sync `CampaignPerformance` to include Rokt Ads in Marketing analytics.
The report provides campaign identity and daily metrics in one table, so the integration aggregates it without joining the report to itself.
Spend uses `gross_cost`, clicks use `referrals`, and reported conversions and revenue use `conversions` and `conversion_value`.
Missing optional conversion metrics show zero.
The importer stores the requested cost currency on each row, defaulting to USD.
Rokt reports `conversion_value` in USD regardless of the requested cost currency.
Marketing analytics converts spend from the stored cost currency and conversion value from USD at each report date.
Changing the source currency affects newly synced rows; historical rows retain their own currency.
Existing connections need a full resync of `CampaignPerformance` to backfill currency before using monetary metrics.
Missing currency columns prevent monetary tiles, and empty historical currency values stop queries with a resync message.
Creative, audience, demographic, and publisher reports are excluded to avoid counting overlapping breakdowns twice.

## Adding a new source

Looking to add a new source to data warehouse? [We have a detailed guide in the codebase](https://github.com/PostHog/posthog/blob/master/products/warehouse_sources/backend/temporal/data_imports/sources/README.md).

> If you're a customer of PostHog Cloud and are looking to import data into your project, then you're likely looking for [this section of the docs instead](https://posthog.com/docs/cdp/sources)

Selecting a source in the `Advertising` category records Marketing analytics product intent as well as Data warehouse intent.
This happens when the user selects the connector, before credentials are validated or data syncs.
The category covers new advertising connectors automatically; it does not mean Marketing analytics supports their data natively.
Selecting a source outside this category, such as BigQuery, records only Data warehouse intent.
Supported self-managed providers keep their separate Marketing analytics intent tracking.

## Marketing source suggestions

Marketing analytics suggests connecting an ad platform only when a matching `utm_source` has events with paid attribution signals.
A source match, referral, fuzzy alias, or `utm_campaign` alone does not establish paid traffic.
For example, [ChatGPT adds `utm_source=chatgpt.com` to referral links](https://help.openai.com/en/articles/12627856-publishers-and-developers-faq), and [campaign tags also describe non-ad marketing](https://support.google.com/analytics/answer/10917952).

An explicit paid medium (`cpc`, `cpm`, `cpv`, `cpa`, `ppc`, `retargeting`, or a `paid` prefix) qualifies for any matched platform.
The following platform-specific signals also qualify, in event properties or the query string of the same event's `$current_url`:

| Platform              | Additional paid signal                                                                                                                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Google Ads            | [`gclid`, `gbraid`, `wbraid`](https://developers.google.com/google-ads/api/docs/conversions/legacy_oci_guide), [`gad_source`, `gad_campaignid`](https://support.google.com/google-ads/answer/16193746) |
| OpenAI Ads            | [`oppref`](https://developers.openai.com/ads/conversion-tracking)                                                                                                                                      |
| Microsoft Advertising | [`msclkid`](https://learn.microsoft.com/en-us/advertising/guides/uet-conversion-api-integration?view=bingads-13)                                                                                       |
| LinkedIn Ads          | [`li_fat_id`](https://learn.microsoft.com/en-us/linkedin/marketing/conversions/enabling-first-party-cookies?view=li-lms-2026-03)                                                                       |
| Reddit Ads            | [`rdt_cid`](https://ads-api.reddit.com/docs/v3/capi-click-id-persistence)                                                                                                                              |
| Snapchat Ads          | [`ScCid`](https://developers.snap.com/marketing-api/Conversions-API/UsingTheAPI#sending-click-id) or `sccid`, not the `_scid` cookie                                                                   |
| TikTok Ads            | [`ttclid`](https://ads.tiktok.com/resources/help/article/tiktok-click-id?lang=en)                                                                                                                      |
| Rokt Ads              | [`rtid`](https://docs.rokt.com/developers/integration-guides/web/advanced/rokt-id-tag/)                                                                                                                |
| Pinterest Ads         | [`pp=0`](https://help.pinterest.com/en/business/article/the-pp-query-string-parameter); `pp=1` excludes earned clicks even when paid campaign tags remain                                              |

Meta, Amazon, and Apple rely on an explicit paid medium in this detector.
`fbclid` and `epik` alone do not qualify.
Apple app attribution requires [AdServices attribution records](https://developer.apple.com/documentation/AdServices/AAAttribution/attributionToken%28%29); an App Store campaign link does not establish an Apple Ads interaction.

Each event counts at most once for its matched platform, even if it has both a paid medium and an ad identifier.
Custom source mappings select which platform's signals apply; another platform's identifier cannot make that source paid.
This check retains the UTM source catalogue's time window and top-500 limit, so it does not discover untagged sources or verify billable clicks.
Missing signals mean insufficient evidence to recommend a connection, not proof that traffic is organic.
The medium count describes only matched events in the lookback window; zero can also mean no events matched that integration.
This changes setup recommendations and diagnostic actions, not report attribution or connected-source sync checks.

## Importing your local Postgres instance

1. Head to the [new source flow](http://localhost:8010/project/pipeline/new/source) in your local app, hit the link button next to Postgres
2. Use the following settings:
   1. host = 127.0.0.1
   2. port = 5432
   3. database = posthog
   4. user = posthog
   5. password = posthog
   6. schema = public
3. Hit next, then select which tables you'd like to import. [More info on the sync types can be found here](https://posthog.com/docs/cdp/sources#incremental-vs-append-only-vs-full-table). For the Postgres-specific `xmin` (cursorless incremental) sync type and its limitations, see the [Postgres source README](https://github.com/PostHog/posthog/blob/master/products/warehouse_sources/backend/temporal/data_imports/sources/postgres/README.md)
4. Hit next and finish the import - `temporal-worker-data-warehouse` will then import the data into your local object storage

## Validating ad source metric imports

Meta Ads requests `video_play_actions` and `video_thruplay_watched_actions` on its campaign, ad set, ad, and supported breakdown statistics tables.
Hourly statistics and `ad_stats_by_link_url` exclude both fields because these breakdowns do not support them.
See [hourly restrictions](https://fivetran.com/docs/connectors/applications/facebook-ads/custom-reports#breakdowns) and [creative-asset metric restrictions](https://docs.streamkap.com/facebook-ads-source#custom-insights).
Custom conversion counts and values remain in the `actions` and `action_values` arrays returned by Meta.

Google Ads exposes daily Search and Display impression share through the optional `campaign_impression_share_stats` table.
This table omits the click-type segmentation used by `campaign_stats` because impression share does not support that combination.
The `campaign.labels` resource names in campaign metadata can be matched to `label.resource_name` in label metadata.

TikTok Ads requests `total_landing_page_view`, `engaged_view_15s`, `cta_conversion`, and `cta_purchase` in its campaign, ad group, and ad BASIC reports.
The CTA fields describe app conversions and purchases attributed to clicks; they do not establish a click-only website purchase metric.
The optional `advertiser_report` table requests daily `spend` and `cash_spend` at advertiser level.
Cash spend can arrive later than other performance metrics.

Reddit Ads requests purchase click and view counts, sign-up click counts, average purchase value, fully viewable video impressions, and viewable video impressions in its campaign, ad group, ad, and breakdown reports.
The conversion window still follows the account's attribution settings.

When validating these changes locally, enable the optional tables and inspect the requested fields in a completed sync.
Existing historical rows do not acquire newly requested fields until their date range is synced again.
Unit tests cover request construction and response handling; a live sync is needed to check that the provider accepts each metric combination and returns data for the connected account.

## Accessing object storage

All your data warehouse data is stored in your local object storage (SeaweedFS, S3-compatible, running at `http://localhost:19000`). Unlike MinIO, SeaweedFS has no web console, so inspect it with any S3 client. For example, with the AWS CLI:

```bash
AWS_ACCESS_KEY_ID=object_storage_root_user AWS_SECRET_ACCESS_KEY=object_storage_root_password \
  aws --endpoint-url http://localhost:19000 s3 ls s3://data-warehouse/ --recursive
```

There's a separate folder under the `data-warehouse` bucket for each table you sync.

## Setting up a MySQL source

If you want to set up a local MySQL database as a source for the data warehouse, there are a few extra set up steps you'll need to complete:

First, install MySQL:

```bash
brew install mysql
brew services start mysql
```

Once MySQL is installed, create a database and table, insert a row, and create a user who can connect to it:

```bash
mysql -u root
```

```sql runInPostHog=false
CREATE DATABASE posthog_dw_test;
CREATE TABLE IF NOT EXISTS payments (id INT AUTO_INCREMENT PRIMARY KEY, timestamp DATETIME, distinct_id VARCHAR(255), amount DECIMAL(10,2));

INSERT INTO payments (timestamp, distinct_id, amount) VALUES (NOW(), 'testuser@example.com', 99.99);

CREATE USER 'posthog'@'%' IDENTIFIED BY 'posthog';
GRANT ALL PRIVILEGES ON posthog_dw_test.* TO 'posthog'@'%';
FLUSH PRIVILEGES;
```

To verify everything is working as expected:

1. Navigate to "Data pipeline" in the PostHog application.
2. Create a new MySQL source using the settings above (username and password both being `posthog`)
3. Once the source is created, click on the "MySQL" item. In the schemas table, click on the triple dot menu and select the "Reload" option.

After the job runs, clicking on the synced table name should take you to your data.

## Working with a MS SQL source

You'll need to install MS SQL drivers for the PostHog app to connect to a MS SQL database. Learn the entire process in [posthog/warehouse/README.md](https://github.com/PostHog/posthog/blob/master/posthog/warehouse/README.md). Without the drivers, you'll get the following error when connecting a SQL database to data warehouse:

```text
symbol not found in flat namespace '_bcp_batch'
```

Scatter area selection follows legend visibility. Changing axes resets zoom, and numeric detail dimensions are available in the axis pickers. Charts with more than 100 color series, or more than one million point/series combinations, show a message asking you to reduce color cardinality or narrow filters. Pending worksheet edits must be run before drilling, and newly added scatter axes take effect after Run. Closing source preview cancels its query.

When groups preserve ungrouped values, named groups and original members retain distinct identities. An ungrouped member whose label matches a group is shown with “(ungrouped)”. Null member aliases also survive saves through MCP. Optional worksheet definitions restore as unset when omitted or null. Saved numeric scatter dimensions remain available as axes even when measure defaults are preferred. Scatter selections require every detail dimension to be representable as a filter; unsupported values cannot broaden a “Keep only” selection.

Repeated dimension pills use distinct result columns so their chart and table bindings stay unambiguous. Generated dimension aliases avoid source identifiers used by measures and filters. Expressions containing percent signs or matching reserved names use supported generated aliases while keeping their original calculation.

BI chart settings preserve custom scatter axes and implicit count formatting. Numeric date parts can be used as scatter axes and remain numeric in **Keep only** and drill-down filters. Scatter selection shows a highlighted count with **Keep only** and **Clear selection** buttons. Switching between chart types reuses results when only their presentation changes, including with auto-update off; pending data changes still require a run. Switching to a box plot initializes statistic mappings from matching result column names. Generated axis labels follow field renames, while custom axis labels remain unchanged.

## Catalog metrics in BI mode

Catalog SQL metrics can open as BI query snapshots. Opening a metric shows a loading state until its definition is ready, or an error if it cannot load. Press **Run** to query the snapshot. Their dates, grouping, and bound values come from the metric definition; shelf edits, worksheet date filters, pivots, and result drilling are unavailable. For snapshots with bound string, number, or boolean values, **Edit parameters** changes those values for the worksheet without changing the SQL or catalog definition. Number parameters require a finite number. Other parameter types remain unchanged. Apply follows the worksheet auto-update setting; with auto-update off, press **Run**. Changing the chart changes the presentation of those results. Saved snapshots do not follow later catalog edits.

After running a worksheet, **Propose as catalog metric** sends its resolved SQL and date window through catalog review. A pending or failed query cannot be proposed. When the name exists, confirm **Overwrite** to replace its definition for review. Cancel keeps the entered values so you can choose a different name. An overwritten metric remains proposed. Direct-connection worksheets cannot be proposed as catalog metrics.

The worksheet library offers editable question starters for daily events, daily distinct people, events ranked by distinct people, and page views by referring domain. Each uses the last seven days of event data and opens as an unsaved worksheet; press **Run** to query it. The page-view starter requires captured `$pageview` events with `$referring_domain` for a useful breakdown. The worksheet library also suggests up to three certified sources. Metric suggestions were removed in [#120111](https://github.com/PostHog/posthog/pull/120111); SQL metrics remain accessible through **Explore in BI** in the catalog. Source context keeps certification visible and groups descriptions and relationship review status under **Catalog details**, collapsed by default to leave room for fields. Neutral catalog buttons show an external-link icon to indicate that they leave the worksheet. Relationship proposals open the catalog with the source prefilled; they become usable joins only after approval. Optional catalog suggestions do not prevent opening the worksheet library when the catalog is unavailable. Browser Back returns from a starter to the worksheet library; confirming discarded edits does not replace that history entry with an empty worksheet.

The BI assistant receives the current worksheet draft, including its unsaved name, and shared catalog capabilities. Worksheet and catalog content remain untrusted context. Dismissing the saved worksheet attachment also removes its hidden draft and metric reference. Completed foreground insight tools refresh the worksheet library. Updates to the open worksheet refresh its saved version while preserving local edits. If both changed the query or name differently, saving over the worksheet is blocked until the local draft is discarded or saved as a copy. This conflict protection survives reloading a worksheet link. A failed refresh can be retried before saving.

## BI and data catalog TODO

Implementation audit, October 28, 2026. These are proposed integration contracts, not commitments from the owning teams. Business intelligence belongs to Data tools; Data catalog belongs to Data modeling. Catalog should own shared definitions and governance, the query platform should compile and execute them consistently, and BI should own interactive authoring and presentation.

### Implemented foundations

- [x] Worksheet-local calculated fields, groups, bins, member aliases, reusable hierarchy copies, comparisons, pivots, source previews, and SQL handoffs.
- [x] Catalog SQL snapshots, worksheet-to-metric proposals, certified-source discovery, and relationship review handoffs.
- [x] Dashboard cross-filtering for compatible BI worksheets on the same table and connection ([#123561](https://github.com/PostHog/posthog/pull/123561)).
- [x] Pivot conditional formatting ([#124717](https://github.com/PostHog/posthog/pull/124717)), editable question starters ([#124730](https://github.com/PostHog/posthog/pull/124730)), and join-key investigation ([#124729](https://github.com/PostHog/posthog/pull/124729)).
- [x] Bound string, number, and boolean parameter editing for metric snapshots ([#124721](https://github.com/PostHog/posthog/pull/124721)). This does not make grouping editable or create live catalog linkage.

### BI-owned integration work

- [x] Adopt the catalog overwrite-confirmation flow for worksheet metric proposals. Preserve entered values on cancel, allow retry, and keep overwritten metrics proposed.
- [x] Show catalog trust context when exploring a metric: approval and drift status, unit, owner, and stable identity. Saved copies retain metadata from copy time, labeled **Catalog status when copied (unverified)** without positive approval styling. Only Proposed and Approved statuses are recorded. Older copies explicitly say no status was recorded. The metadata is editable worksheet content, not verified provenance or a live approval; authors are directed to the current catalog entry. Live version checks remain shared-layer work.
- [x] Add deliberate, searchable metric discovery in BI using the existing catalog search API. The picker handles loading, failure, no matches, pagination, and unsupported definition kinds explicitly.
- [x] Surface existing table and view field descriptions in the data pane, including related tables. Show recorded data-quality check health separately from certification, with explicit unavailable, unchecked, and error states. Raw field identities remain unchanged.

### Shared-layer requests

| Priority | Request                                   | Acceptance boundary                                                                                                                                                                                                                                               |
| -------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P0       | Composable metrics                        | A structured metric declares supported dimensions, date range, time grain, filters, output schema, and capabilities. BI can change these without rewriting SQL. Arbitrary SQL can remain snapshot-only.                                                           |
| P0       | Aggregation semantics and dataset grain   | Declare measure aggregation, unit/scale, entity keys, base grain, valid dimensions, and time behavior. Ratios, distinct counts, and balances have explicit rollup rules.                                                                                          |
| P0       | Governed relationship cardinality         | Persist expected cardinality, uniqueness and match-coverage evidence, validation time, and status. Query planning rejects, warns about, or correctly handles joins that would multiply measures. A configured join or one-off SQL check is insufficient evidence. |
| P1       | Publish reusable semantic fields          | Publish/review/reference business calculations, groups, bins, aliases, and hierarchies while retaining worksheet-local experimentation and overrides. Use existing saved warehouse expressions where appropriate.                                                 |
| P1       | Stable references and dependency tracking | Reference immutable metric IDs and definition versions/hashes. Offer explicit pin/refresh behavior, downstream worksheet/dashboard dependencies, and changed/deleted/unapproved warnings. Names alone are insufficient because they can be reused.                |
| P1       | Shared metadata and health contract       | Expose permission-aware source/field descriptions, semantic defaults, owner, certification, freshness, quality results, and lineage links. A trust mark and passing checks communicate different facts.                                                           |
| P1/P2    | Source coverage                           | Define capabilities and connection-scoped identity for direct connections, native tables, saved views, and managed views. Direct-connection metric proposals and managed-view certification remain gaps. Prioritize according to the supported BI audience.       |
| P2       | Shared dimensions across datasets         | Give dimensions such as Customer, Country, and Date stable identities and explicit mappings so dashboard filtering can cross compatible datasets safely. Depends on grain and relationship contracts.                                                             |

Reuse the existing data-quality checks (uniqueness, non-null, relationships, freshness, and custom SQL), metric lineage, insight drift detection, warehouse column annotations, saved expressions, and server-side catalog search. Extend these contracts rather than creating parallel BI stores. BI proposals currently submit resolved SQL without the source-insight linkage used by insight drift detection.

Keep chart colors, shelf placement, pane layout, current drill position, and ad hoc table calculations local to BI. Publishing a reusable business definition should be explicit.

First joint acceptance scenario: define Revenue once, add it to a worksheet, break it down by customer country, switch monthly/quarterly grain, and apply dates. BI and AI use the same definition. A join that duplicates revenue is detected. Saving preserves the definition version, and subsequent definition changes are visible to the worksheet author.

## Connected fields in BI mode

**Check key uniqueness** opens an editable SQL check for repeated or null keys in a configured relationship's joined table. Press **Run** in the SQL editor to execute it. The check scans the full joined table, ignores worksheet filters, and returns at most 100 key groups. It does not check missing matches or prove that a join is safe for every aggregation. Expression-based keys require a custom SQL check.

Below Dimensions and Measures, **Connections** lists the selected table's linked tables and views.
Expand a connection to load its dimensions, measures, and nested connections. Inside connections,
fields and further links appear without section headings.

Drag connected fields onto a shelf, double-click them, or press Enter or Space to add dimensions to Rows and measures to Values.
Measures are aggregated automatically. The worksheet keeps its original source table and uses the full
connection path in queries and shelf labels, such as `person.company.name`.
Connections expand on demand, including repeated links to the same table. Search filters the fields
inside expanded connections, and a failed field load has a Retry button.
Aliases load any intermediate tables automatically. Loading and failed connections stay visible during search.
Virtual connections expose the field names provided by the existing schema as dimensions. The schema does
not include their field types or nested link definitions, so these connections do not infer measures or further links.

### Pivot conditional formatting

BI pivot tables use the same saved conditional formatting rules as ordinary tables. Open **Conditional formatting** to select a measure and a rule. The rule applies to that measure across column groups, including displayed subtotals, grand totals, and collapsed groups. Rules evaluate raw aggregate values before display formatting. Empty intersections and hidden parent values remain uncolored.
