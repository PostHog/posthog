# Model detail scene

Model detail uses the standard object-scene header with the model type beside its name.
The top-right actions open the SQL editor or endpoint and run materialization.
Plain views expose Materialize in the same header; its cadence and incremental settings come from the Materialization tab.
Materialized models also expose schedule resumption when suspended and an overflow menu for cancellation, rebuilding, pausing refreshes, and reverting materialization.
Endpoint models keep their lifecycle controls in the endpoint scene.

The summary stays visible across tabs and distinguishes the latest run result from the last successful refresh.
A failed, canceled, or skipped run does not advance the successful refresh timestamp.
When recent history contains no completed run, the summary says so instead of claiming the model has never succeeded.
Schedule suspension and manually paused refreshes have separate descriptions.
The downstream count links to the model's lineage.

Query contains the SQL preview and columns.
Materialization contains the schedule, refresh-mode settings, and run history with expandable logs.
Data quality contains the model's checks; the existing `/tests` route and feature flag stay unchanged.
The shared materialization controls also serve the SQL editor's materialization panel.

Creation metadata uses the shared scene activity component in the information panel.
The Query tab shows the complete SQL in a bounded, scrollable CodeSnippet, with copy available without expanding the query.
Refresh schedule describes saved configuration and suspension state, not a live Temporal status read.
While materialization settings save, run actions are disabled and the frequency selector shows saving progress.
Frequency help explains upstream source and downstream consumer constraints; individual unavailable options name their blockers.
Data quality separates configured checks from an expanded check-run history section.
Materialization uses the same divider and spacing between settings and run history.
Models without lineage connections show an explanation and a link to explore the full graph.
The health summary fits its contents and uses a colored run-status tag, without a shortcut to the Materialization tab.
The project check-gating notice sits below the Checks heading and actions.

## Metadata and History

Creation metadata is right-aligned beside the health summary and wraps beneath it in a narrow scene.
It uses two columns: Created by above Created at on the right, and Updated at at the bottom left.
If materialization settings fail to load, an inline panel uses the shared doctor hedgehog and a Retry action.
Updated at uses the saved query's update timestamp, falling back to the modeling node for source-table models.
History uses the shared activity log and its existing access and retention rules.
Request-driven query updates, schedule changes, manual sync/cancel actions, and materialization enable/disable already emit saved-query activity.
Data quality check saves and soft deletions already emit check activity.
When the activity-log endpoint receives both `DataWarehouseSavedQuery` and `DataQualityCheck` scopes plus a saved-query `item_id`, it includes that model's check events, including soft-deleted checks, within the current project.
Other scope combinations retain exact item-ID filtering.
Direct ORM or worker writes that bypass these logging paths are not retroactively reconstructed.

## Run errors

Expand a materialization run to see its full stored error or skip reason above the logs.
The message has a copy button and bounded scrolling; the table only shows a first-line preview.
The regular failure activity also emits a sanitized error log, but recovery and notification entries can follow it.
The stored message remains accessible independently of log delivery and retention.

## Materialization guidance

The Materialization tab explains stored query results above its refresh settings.
Running jobs disable Sync now and cadence choices with the same reason: Materialization is currently running.
The health summary explains downstream dependencies in a tooltip and uses matching loading placeholders for unknown schedule and dependency details.
Refresh mode descriptions explain full and incremental runs without repeating them above the cadence control or below the selected full-refresh option.

## Per-run refresh mode

Incremental materialized views with run history show a separate Refresh mode column.
It reports Full refresh or Incremental for each run, and a dash when no mode was recorded.
The materialization actions menu offers Run full refresh for incremental views.
After confirmation, it uses the existing full-refresh API option to clear incremental progress and rebuild the table; incremental configuration stays enabled.

### Editing materialization settings

Refresh cadence and refresh mode are a single local draft.
Changing either shows Save and Discard changes in the scene header, or in the shared materialization modal.
Save submits both changes together; Discard changes restores the saved settings.
Polling preserves unsaved edits, and a failed save keeps the draft available to retry.
Sync now and Edit in SQL editor remain visible and are disabled until the draft is saved or discarded.

Incremental column, unique key, and Lookback window explanations appear in info tooltips next to their field labels, including the shared modal and save-as-view form.

The materialization panel and modal indent incremental settings beneath the mode selector, using compact label-and-control rows that stack in narrow containers.

### SQL editor model modal

The SQL editor's materialization modal separates Materialization, Lineage, and Data quality into LemonTabs.
Data quality follows the existing feature flag.
Run actions and Save/Discard changes sit in a persistent footer beneath the scrollable content.
Open model sits at the bottom-left of the modal footer and links to the saved query's model scene and waits until any settings draft is saved or discarded.
Tab changes keep the settings draft and check editor mounted.

The modal summarizes the latest run with the same status tag colors and last successful refresh timestamp used in the model scene.

The SQL editor Lineage tab uses the model scene’s Open the full graph icon button inside the canvas controls. It opens the Models lineage canvas in a new tab, preserving the editor and any unsaved settings.

The SQL editor modal mounts the lineage canvas when its tab becomes visible, so React Flow fits against the visible container dimensions. Returning to Lineage refits the graph; materialization and check drafts remain mounted.

The modal canvas height follows the viewport, and its initial fit caps zoom at 100% so small graphs remain readable without oversized nodes.

The SQL editor model modal and its materialization panel use the same skeleton for the status summary, refresh settings, and run history while loading.
Tabs remain available when the selected view is already known, without waiting for the saved-view list.
