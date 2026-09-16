# Managing models

The Models overview shows ten rows per page in each section: models needing attention, models behind schedule, and failing data quality checks.
Each section has independent previous and next controls when it has more than ten rows.
Screen readers identify these controls as Previous page and Next page.
Paginated tables keep the height of a full page, including on a partial last page, so other sections stay in place.
Skipped runs describe upstream models stopped after repeated failures as suspended.

Open a saved view from Models to inspect its query, refresh schedule, and run history.
The Models breadcrumb on a model detail page returns to the models list tab.
The actions menu offers **Delete view** for a saved view and **Delete materialized view** for a materialized view.
Deletion asks for confirmation, removes the saved view and its materialized data, and returns to Models after success.
Queries that depend on the deleted view will stop working.
**Revert materialization** removes the materialized data and stops scheduled refreshes while keeping the saved view.
Endpoint-backed models use the endpoint page to manage their lifecycle.

Run history shows ten runs per page with previous and next controls.
Refreshing the history reloads the current page.
The latest run continues to update independently while you browse older pages, so the model status and run controls reflect the current run.
**Last synced** reports the newest completed run, even when it is older than the ten runs on the first page.

When suspension enforcement is enabled, a model suspended on the serving engine shows **Suspended** in both the attention list and its detail summary.
The summary includes the reason and the stopped schedule; past runs retain their recorded outcomes.
A marker on a shadow engine, or a marker while enforcement is disabled, does not mean scheduled refreshes have stopped.

Model list action menus use full-width buttons.
Deleting a view shows one success notification after the deletion request succeeds.
