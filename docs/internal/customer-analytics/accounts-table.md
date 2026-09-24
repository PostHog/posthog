# Accounts table

## Query scheduling

Account row and overview requests use a dedicated frontend queue with two concurrent slots.
This lets both requests start together while preserving cancellation, priority ordering, and queueing for additional account table queries.
Other query types keep their existing global or scene-specific concurrency limits.

## Unsaved filters and views

The Accounts list keeps unsaved filters when a user opens an account and returns to the list.
The draft includes search, tags, assignment filters, account property and relationship filters, and the selected overview tile filter.
It also keeps sorting, selected columns, column display settings, and overview tile settings.

The browser stores one draft per project and user in `sessionStorage`.
Draft restoration waits for the loaded project and user IDs before deciding whether to apply a saved view.
Automatic column updates do not replace the pending draft with default URL state.
The draft survives list remounts and page reloads in the same tab.
It does not update a saved view or store account rows.
Closing the browser tab ends the draft session.

Restoration uses this order:

1. An explicit `#view` in the URL takes priority over the draft, including an empty view.
2. Without a view hash, the list restores the draft.
3. Without a draft, the list restores the last selected saved view, if available.
4. Otherwise, the list uses its defaults and the shared My accounts preference.

On a fresh tab, restoring the My accounts preference does not create a draft or mark default columns as a restored selection.
Draft and URL writes wait while the last selected saved view loads, then store the resolved view.
Relationship definitions can load before or after saved views without replacing saved columns.

Selecting a saved view replaces the draft.
Clearing filters keeps them cleared on return, even when a saved view remains selected.
Saving or updating a view still requires an explicit action.
If browser storage is unavailable or invalid, the list uses URL state and saved views without failing.

`accountsLogic.viewState` supplies the shared snapshot for drafts and saved views.
`applyViewState` restores it without intermediate URL writes.
The parent scene preserves the view hash when changing date or test-account filters.

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
`accountsViewsLogic` stores manual widths per team and column in browser local storage, independently of saved views.
Hiding a column does not discard its saved width.
Automatic sizing uses the existing resized-table layout and does not change scroll controls.

The `ManyColumns` story in `AccountsTab.stories.tsx` covers six added custom properties alongside native and relationship columns.
Its browser assertions check content-dependent widths, the 200px cap, horizontal scrolling, and the row expansion control.
At narrow widths, it also covers custom-property inline editing: the input fits the available column width, and Save and Cancel stay together below it when needed, aligned to the right.
The row grows without widening the column.

## Relationship member pickers

Each editable single-holder relationship cell mounts a member picker.
Closed pickers render the selected label but defer the searchable option list until opened.
Opening still loads members and keeps the current user first.
Closing through a selection, the trigger, or an outside click clears the search so the next open starts fresh.
Mounting another closed cell does not clear an active picker's search.
