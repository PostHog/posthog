# Accounts table column widths

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
