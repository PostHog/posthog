# Accounts table

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

## Column widths

The Customer analytics Accounts list sizes new columns to their rendered header and loaded values.
Automatic widths have an 80px minimum and a 200px maximum.
Short values use less space, while long values stop the column from growing beyond 200px.

Saved widths and existing column defaults take precedence over automatic sizing:

| Column                                     | Default width                   |
| ------------------------------------------ | ------------------------------- |
| Account and tags                           | 280px                           |
| Notes                                      | 80px                            |
| Relationships                              | 220px                           |
| Custom properties and other account fields | Fit content, from 80px to 200px |

`useAccountColumnAutoSizing.ts` measures a hidden copy of the rendered table without width constraints.
It excludes expanded rows from the measurement and removes the copy before the browser paints.
Automatic widths update when loaded data changes and are not saved to browser storage.

Users can still drag column header boundaries to resize columns, including beyond 200px.
`accountsViewsLogic` stores manual widths per team and column in browser local storage, independently of saved views.
Hiding a column does not discard its saved width.
Automatic sizing uses the existing resized-table layout and does not change scroll controls.

The `ManyColumns` story in `AccountsTab.stories.tsx` covers six added custom properties alongside native and relationship columns.
Its browser assertions check content-dependent widths, the 200px cap, horizontal scrolling, and the row expansion control.
At narrow widths, it also covers custom-property inline editing: the input fits the available column width, and Save and Cancel stay together below it when needed, aligned to the right.
The row grows without widening the column.
