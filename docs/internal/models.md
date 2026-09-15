# Managing models

Open a saved view from Models to inspect its query, refresh schedule, and run history.
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
