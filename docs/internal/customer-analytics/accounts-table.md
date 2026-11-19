# Accounts table

## Account automations

The Automations tab and view widget show retained workflow runs for an account.
The `customer-analytics-automations-widget` feature flag controls the tab, widget picker, and saved widgets.
Each execution has its own row, including repeated runs of one workflow.
Account events and account-audience batch runs appear here.
Person-triggered product events do not.
Account events match their stable account ID, including accounts without an external ID or whose external ID has changed.
Event discovery only considers events referenced by retained runs.
ClickHouse filters, counts, and paginates runs before returning rows.
Workflow step metadata is read in one batch for the page when the ClickHouse-to-Postgres proxy is configured.
Without that proxy, the existing Workflows read facade loads each page workflow through Django's database connection.

Rows link to the workflow with an inline status chip.
Separate columns show the original trigger time, last completed step, and expected resume time for a current delay.
The last completed step shows its date and current name when the retained logs identify a step still present in the workflow.
A resume time describes when execution should continue. It does not guarantee an action.
Run records expire after 30 days and step logs after 90 days.
Only retained run records can be discovered, so older active runs may be absent too.
Expected resume times come from retained delay logs and disappear after later execution or completion.
Completed history can be incomplete, and a date appears as unavailable when retained evidence cannot establish it.
Only lifecycle log messages contribute to step evidence. Failure evidence matches known runtime messages with their expected prefixes.
Ordinary function output containing error or skip words does not invalidate step history or consume the evidence limit.
Returned messages are capped at 256 bytes.
Runs with more than 200 lifecycle log messages omit completed-step and resume details because their evidence exceeds the summary limit.

The endpoint requires account, workflow, person, and event read scopes.
It checks account access and returns only workflows the caller can read.
The widget offers no controls to change a workflow run.

## Default pinned account properties

Project admins choose an ordered set of default pinned properties under Customer analytics > Accounts settings.
The defaults can include account custom properties and relationships.
They appear in account detail sidebars and expanded Accounts rows until a user saves a personal selection.

The user configuration inherits when it has no personal selection, including historical empty lists without an override marker or legacy pinned IDs.
Reads resolve the current project defaults without copying them into the user row, so later project changes reach every user who still inherits.
A personal save stores the complete ordered list and an override marker.
A saved empty list means the user chose no pinned properties and no longer inherits project changes.

## Table columns and definitions

The first table response contains rows, ordered columns, and the metadata needed to show and edit those columns.
A default view sends `useDefaultColumns: true`. The backend selects the name, tags, note count, and all project relationships.
Saved views store their selected column expressions. Relationship expressions contain the definition ID and a stable alias:

```text
accounts.relationships.values.`<definition-id>` AS rel_<definition-id-without-hyphens>
```

Relationship sort entries use the same alias followed by `ASC` or `DESC`.
The column picker and default-column builder create this format. Saved views preserve it unchanged.
The query planner sends typed definition references to the table endpoint.
Empty results still include column metadata.

The table and overview queries start without waiting for definition catalogs.
The backend validates custom-property and relationship filters, including filters for columns outside the table.
The Accounts UI requests that missing definitions be omitted, so deleted properties do not block saved views.
The response omits their columns and values. A deleted sort column falls back to the default row order.
Saved custom-property filters with incompatible operators are omitted after a definition changes type.
Other API callers retain strict validation by default.

Saved overview metrics use their definition IDs without waiting for catalogs.
Missing or nonnumeric metric definitions produce an empty metric value.
Table metadata caches workflow-reference flags for 60 seconds per project.

Opening a column, filter, or overview editor loads each definition catalog once with `pagination=none`.
The API keeps its `results`, `count`, `next`, and `previous` envelope. Other callers keep pagination by default.
Catalog responses update picker options without changing the table request.

## Query scheduling

Account row and overview requests use a dedicated frontend queue with two concurrent slots.
This lets both requests start together while preserving cancellation, priority ordering, and queueing for additional account table queries.
Other query types keep their existing global or scene-specific concurrency limits.

## Unsaved filters and views

The Accounts list keeps unsaved changes in memory while the user edits the list.
Only the Back link on an account details page can restore those changes after navigation.
Other navigation, including tabs, the sidebar, browser Back, and page reloads, discards them and loads the current saved view.
Save or update a view to keep its filters, sorting, columns, column display settings, and overview tiles.
Neither browser storage nor the URL stores an unsaved view snapshot.
Column widths remain a separate browser preference.

Account property, relationship, and custom-property filters can be placed in OR groups.
Filters within each group use AND, while search, tags, assignment status, and selected overview tile filters apply to every group.
Saved views keep the groups. Older views without groups retain their AND behavior.
A group that filters on churned or ignored accounts includes them only in that group. Other groups still exclude them by default.
When a saved condition refers to a deleted property, the list keeps the valid conditions in that group.

The toolbar keeps a Filters button with a spaced, theme-aware accent count. The button highlights while the compact groups are open in a bordered area below it.
Restored filters start collapsed. Relationship pills show member names using the same member list as the value picker. Adding the first condition opens the groups, and removing the last group restores the Filter button.
Empty OR groups do not affect results. Search, tags, and assignment controls remain outside the editor.

### Saved-view links and restoration

The Accounts URL identifies a saved view with `?view=<id>`.
A copied link loads that view's current saved configuration, not the sender's unsaved changes.
Renaming a view does not change its link.
The browser remembers only the last selected saved-view ID and name for each project and user.
The picker shows that name immediately and keeps the same button while the current saved definition loads.
Filters, columns, sorting, and tiles still come from the server, never from the name cache.
A missing saved view clears the cached selection.

On a fresh load, restoration uses this order:

1. An explicit `?view=<id>` selects the saved view.
2. Without an explicit selection, the list restores the remembered saved view.
3. Without an available saved view, the list uses its defaults.

Accounts and Notes have independent My accounts filters.
Changing one does not change the other, including when switching tabs.
Notes saved views retain the selected assignee IDs when shared. Their summaries show those members' names, not the current viewer's accounts.
Removing My accounts on the Accounts list restores all assignment statuses.
Fresh Accounts loads do not restore unsaved filters or the Notes preference.
Saved-view restoration waits for the project, user, and saved configuration to resolve before issuing list and overview queries.
Relationship definitions can load before or after saved views without replacing saved columns.
A missing or inaccessible view clears the stale selection and uses defaults.
A failed view request offers a retry and does not make the default configuration appear modified.

Selecting another saved view replaces the working configuration.
Opening an account from the list prepares a one-use return link for its Back button.
The link contains the saved view ID, existing scene parameters, and an opaque `restore_view` token. It never contains filters or a view snapshot.
The token only restores an in-memory return in the same app context and is removed from the URL after use.
Copied links, reloads, and reused tokens load the current saved definition instead.
A pristine view also reloads its current saved definition on Back, so a teammate's updates do not appear as unsaved edits.
Other navigation keeps the selected view but discards unsaved changes. An explicit different view ID changes the selection.
Later background view loads do not replace unsaved changes.
Saving or updating a view requires an explicit action.

Existing `#view` snapshot links remain readable for compatibility, but the list no longer creates them.
An explicit query-string view ID takes precedence over a legacy snapshot.
Browser storage failures do not prevent URL-based selection.
`accountsLogic.viewState` supplies the snapshot for working state and explicit saves.
The parent scene preserves the selected view ID when changing date or test-account filters.

### Notes saved views

Accounts and Notes use the same saved-view picker and management dialogs.
The Notes toolbar starts with search. View tooltips describe the saved filters and sorting.
Edit and Delete remain in each view's Manage menu.
Select "All notes" to clear the selected view and restore that Notes list's default filters and sorting.

A Notes tile saves search, tags, authors, sorting, and the selected view ID in its configuration.
Switching account tabs keeps the selected Notes view with its filters.
A view's account and assignment filters apply only on the team Notes list.
Sorting by account also applies only there. Within one account, the table uses creation-date sorting while preserving the saved account sort.
Changing other filters and updating that view does not replace its team-only sort.

Note tag edits appear immediately and save in order for each note.
An earlier response cannot replace a later pending edit. A failed write restores the last saved tags unless another edit is pending.

## Sorting

The Accounts list uses server sorting until it knows that the full matching set fits on one page.
This makes the first page globally correct when more pages are available, including when a sort comes from a saved view or shared URL.

The list tracks result completeness per filter set as unknown, complete, or paginated.
An unknown set includes the selected sort in its first request.
If the response is complete, the list keeps that request's query identity and applies later sort changes to the loaded rows in the browser.
If the response has more rows, later sort changes stay on the server and apply across every page.
Loading the final page does not switch a paginated set to browser sorting or reset the accumulated rows.
Changing filters starts the completeness decision again, and stale responses cannot update the current filter set.
An explicit refresh uses the known mode for its request, then lets the response update completeness in either direction.

## Column widths

The Customer analytics Accounts list sizes new columns to their rendered header and a bounded sample of loaded values.
Automatic widths have an 80px minimum and a 200px maximum.
Short values use less space, while long values stop the column from growing beyond 200px.

Saved widths and existing column defaults take precedence over automatic sizing:

| Column                                     | Default width                   |
| ------------------------------------------ | ------------------------------- |
| Account and tags                           | 280px                           |
| Notes                                      | 80px                            |
| Relationships                              | 220px                           |
| Custom properties and other account fields | Fit content, from 80px to 200px |

`useAccountColumnAutoSizing.ts` builds a hidden measurement table from each automatic column's header and at most six body cells, rather than cloning the rendered table.
It ranks a fixed candidate window from the first and last loaded values, then favors the longest text and the most structurally complex renderers.
The measurement table preserves each column's rendered position, so boundary padding stays accurate.
This covers appended pages and common cells such as links, dates, numeric values, avatars, buttons, and multiline content while keeping measurement work bounded.
A value outside the sample can be wider than the selected candidates, so the 200px cap and manual resize control remain the fallback for unusual renderers.
Expanded rows are excluded.
Measurements run after render, reuse widths while the sampled markup is unchanged, update when changed or newly loaded content enters the sample, and remove the temporary table immediately.
Automatic widths stay local to the mounted table and are not saved to browser storage.

Users can still drag column header boundaries to resize columns, including beyond 200px.
The tag editor fits the current tag column width, even after a resize.
Long tags truncate inside the editor instead of spilling into the next cell.
`accountsViewsLogic` stores manual widths per team and column in browser local storage, independently of saved views.
Hiding a column does not discard its saved width.
Automatic sizing uses the existing resized-table layout and does not change scroll controls.

The `ManyColumns` story in `AccountsTab.stories.tsx` covers six added custom properties alongside native and relationship columns.
Its browser assertions check content-dependent widths, the 200px cap, horizontal scrolling, and the row expansion control.
At narrow widths, it also covers custom-property inline editing: the input and Clear value action fit the available column width, and Save and Cancel stay together below it when needed, aligned to the right.
Wrapped editor controls have an 8px gap between rows.
The row grows without widening the column.

## Clearing custom properties

Every editable custom-property cell offers Clear value, including select, boolean, numeric, date, and datetime properties.
The action asks for confirmation before saving `null` through the existing custom-property-values endpoint.
Canceling the confirmation keeps the value unchanged.
A cleared cell shows an unset value while the table refreshes, rather than falling back to its stale value.
A failed write restores the previous value and lets the user try again.
Canonical and warehouse-backed properties remain read-only.
Workflow-backed properties remain editable, with the existing warning that a future workflow run can overwrite a manual change.

The `ClearCustomProperties` story checks clearing every display type and canceling the confirmation.
It includes zero and false values, which must stay distinct from an unset value.

## Relationship member pickers

Each editable single-holder relationship cell mounts a member picker.
Closed pickers render the selected label but defer the searchable option list until opened.
Opening still loads members and keeps the current user first.
Closing through a selection, the trigger, or an outside click clears the search so the next open starts fresh.
Mounting another closed cell does not clear an active picker's search.
