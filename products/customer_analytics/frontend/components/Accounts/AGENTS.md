# Accounts — agent guide

Development guide for the Accounts area of Customer analytics (`products/customer_analytics/frontend/components/Accounts/`).
Scope is the **Accounts list** only, not the rest of Customer analytics.
This file should carry the full context needed to work here — architecture, data flow, conventions, and analytics — not just events.

> **Keep this guide current.** Whenever you change the Accounts area — add or refactor a component, logic, tab, event, filter, query column, or behavior — update this file in the same change so it stays an accurate map of how the Accounts list works.

## What this is

An **Account** is a customer organization. The list is a HogQL-backed table over the `system.accounts` table, with per-row expansion into Notes / Users / Usage, inline role assignment (CSM, AE, owner), configurable columns, overview metric tiles, shareable views, and a Max (AI) contextual tool for opening accounts.

`Account.external_id` is the PostHog **group key** — it's how an account joins to its group-analytics data (usage, events, feature flags). Treat it as the account's analytics identity, not a CRM id (CRM/billing ids live in account properties). The account→group bridge lives in the backend query runner and the agent mode, not here — see [Backend touchpoints](#backend-touchpoints). Keep this mechanism out of any user-facing copy (it's a façade — see the agent mode preset).

## Architecture

The scene renders `AccountsTabContent`, which binds one `dataNodeLogic` (key `ACCOUNTS_HOGQL_DATA_NODE_KEY`, from `../../constants`) to the query built by `accountsLogic.hogqlQuery`. Everything else reads from that bound data node or from the logics below.

```text
AccountsTabContent  ── binds dataNodeLogic(ACCOUNTS_HOGQL_DATA_NODE_KEY, accountsLogic.hogqlQuery.source)
├── AccountsMaxTools          registers the `open_account` Max contextual tool → accountsLogic.openAccount
├── AccountsTabFilters        two rows: (1) search + Refresh; (2) tags / "assigned to" (incl. unassigned-only) /
│                             "my accounts" on the left, AccountsOverviewTilesButton + AccountsColumnConfigurator on the right
├── AccountsOverviewTiles     metric tiles across the filtered set
└── AccountsHogQLTable        the DataTable; per-column renderers; controlled row expansion
    └── AccountNotebooksExpansion   expanded row: Useful links + LemonTabs(Notes/Users/Usage)
        ├── (notes)  in-place LemonTable of linked notebooks  (accountNotebooksLogic, keyed by accountId)
        ├── (users)  AccountRelatedUsersExpansion             (accountRelatedUsersLogic, keyed by externalId)
        └── (usage)  AccountBillingExpansion kind="usage"     (accountBillingLogic — a saved billing-usage insight)
```

### Logics and what each owns

| Logic                        | Owns                                                                                                                                                                                                                                                                  |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `accountsLogic`              | The hub. Search (debounced), tag and assigned-to/unassigned filters, sort, inline role assignment, the `hogqlQuery` selector, shareable URL-hash view state, and `openAccount` (the Max entry point). `connect`s column-config, overview-tiles, and expansion logics. |
| `accountsViewsLogic`         | Saved-views lifecycle (list/create/update/delete/select). Connects to `accountsLogic`, `accountsColumnConfigLogic`, and `accountsOverviewTilesLogic`; is the single owner of reading and writing the `ColumnConfiguration` rows for this area.                        |
| `accountsColumnConfigLogic`  | Selected columns (`selectColumns` / `visibleColumnNames`), the column-picker groups built from the DB schema + data-warehouse joins, and the per-team saved column config (`columnConfigurations` API).                                                               |
| `accountsExpansionLogic`     | Which rows are expanded (`expandedAccountIds`) and the active tab per account (`activeTabByAccount`). Pure state — no DOM, no data fetching.                                                                                                                          |
| `accountsOverviewTilesLogic` | The overview metric tiles (saved in views via `properties.tiles`); feeds `metrics` into the query. Reads legacy per-team localStorage tiles **read-only** on mount + emits an `OverviewTilesLocalStorageRead` tombstone; never writes localStorage.                   |
| `accountNotebooksLogic`      | Notes/notebooks linked to one account (keyed by `accountId`).                                                                                                                                                                                                         |
| `accountRelatedUsersLogic`   | Group members / related users for one account (keyed by `externalId`).                                                                                                                                                                                                |
| `accountBillingLogic`        | Billing/usage data behind the Usage tab.                                                                                                                                                                                                                              |
| `accountLinksLogic`          | The "Useful links" sidebar for one account (keyed by `accountId`).                                                                                                                                                                                                    |

## Data & query model

`accountsLogic.hogqlQuery` builds a `DataTableNode` wrapping an `AccountsQuery` (`select`, plus optional `search`, `tagNames`, `allRolesUnassigned`, `assignedToUserIds`, `filterExpression`, `metrics`, `orderBy`). The backend runner (`accounts_query_runner`) returns **rows as arrays** aligned to `visibleColumnNames`. `assignedToUserIds` is the "assigned to" filter — a list of user ids the runner expands into `csm IN ids OR account_executive IN ids` (the single user-facing role filter; there are no separate per-role CSM/AE/owner filters). The `allRolesUnassigned` flag (the "Unassigned only" option, surfaced inside the "Assigned to" picker — mutually exclusive with picking people via the cascade in `accountsLogic` listeners) restricts to accounts with no csm/AE/owner. The "My accounts" checkbox is a client-side shortcut: `accountsLogic` resolves it to `[currentUserId]` (from `userLogic`) before the query is sent, so the backend only ever receives explicit ids and a shared URL resolves to the same accounts for every viewer. Two cell shapes matter:

- **`name` column** (mandatory, `ACCOUNTS_NAME_COLUMN`) — emitted as `tuple(name, external_id, id)`, read as `{ name, external_id, id }`. This is the row's identity: `id` (the account PK) drives expansion/scroll/role updates; `external_id` is the copy-able group key. `getNameCell()` in `AccountsHogQLTable.tsx` is the canonical accessor; never assume a column index.
- **role columns** (`csm`, `account_executive`, `account_owner`) — emitted as `tuple(id, email)`, rendered with `MemberSelect`. Sorting these uses `tupleElement(col, 2)` (email) so visual order matches.

Default columns (`ACCOUNTS_HOGQL_DEFAULT_SELECT`): `name`, `tag_names`, `notebook_count`, `csm`, `account_executive`, `account_owner`. The name column is force-kept (`ensureNameColumn`) — removing it breaks identity, scroll, and role edits. Extra columns come from account properties, lazy/virtual-table joins under `system.accounts`, data-warehouse joins, or freeform SQL — all assembled by `buildAccountColumnGroups`.

Sort safety: removing the sorted column drops the sort (`clearSortIfColumnRemoved`), else the backend gets an `orderBy` referencing a missing alias.

## The expanded row

`AccountsHogQLTable.useExpandable()` makes expansion **controlled** by `accountsExpansionLogic`: `isRowExpanded` reads `expandedAccountIds`, `onRowExpand`/`onRowCollapse` dispatch `toggleAccountExpanded`. The body is `AccountNotebooksExpansion`, a `LemonTabs` over `notes` / `users` / `usage` (`AccountExpansionTab`) plus the Useful links sidebar. Active tab comes from `activeTabFor(accountId)` (defaults to `notes`).

The Usage tab renders an existing saved billing-usage insight — **point users to it, don't rebuild usage as a new insight.**

## Shareable view state

`accountsLogic` mirrors the full view (search, tags, unassigned, assigned-to, sort, columns, tile filter) into the URL hash `#view=...` via `actionToUrl`/`urlToAction`, so a copied URL reproduces the exact list. Only non-default values are serialized. The "assigned to" filter persists as concrete `assignedTo` ids (not a `mine` flag), so a link shared with a colleague resolves to the **same** accounts for them as for the sharer; the legacy `mine: true` hash is still read and resolved to the current user's id for backward compatibility. A shared link's `columns` win over the per-user saved column config (`accountsColumnConfigLogic` enforces this when its async saved-config load resolves by checking the live URL).

## Saved views

A saved view is a named snapshot of the full Accounts list state (columns, sort, filters, overview tiles).
Views are persisted as `ColumnConfiguration` rows under `context_key = 'customer_analytics_accounts_columns'` (the `ACCOUNTS_COLUMN_CONFIG_KEY` constant).
`accountsViewsLogic` is the single owner of this lifecycle; components only call its actions.

`accountsViewState.ts` is a pure module that maps UI state ↔ the `ColumnConfiguration` payload:

- `columns` ← `selectColumns` (column names in order)
- `order_by` ← sort, stored as `["<column> <ASC|DESC>"]` using the logical column name
  (query-time `deriveAccountsOrderByExpr` wraps role/tuple columns at build time; the stored name stays clean)
- `filters` ← search text, tags, unassigned toggle, assigned-to filter, tile filter (JSON)
- `properties` ← `{ tiles }` — overview tile configuration (a `properties` field added to the `ColumnConfiguration` model)

**Visibility** is `private` or `shared`; only the creator can edit or delete a view (enforced by the backend viewset).

**Auto-restore:** the last-used view `id` is persisted in a team-scoped localStorage key (`currentViewId`).
A shared link's `#view=` URL hash always wins over the saved `currentViewId`.
`isDirty` is true when the live state diverges from the selected view's saved state.

**One-time tiles migration:** on first load, if the signed-in user is the creator of the existing default `ColumnConfiguration` row and its `properties.tiles` is empty while their localStorage tiles differ from `DEFAULT_TILES`, `accountsViewsLogic` patches the localStorage tiles into that row.
The operation is idempotent and skips non-creators.

**Column configurator:** `AccountsColumnConfigurator.tsx` no longer persists columns itself — its footer button is "Done" (closes only).
Column changes are saved as part of a view via `AccountsViewSelector.tsx` (the view dropdown in `AccountsTabFilters`), which offers "Save current view" (creates) and "Update '<name>'" (patches the selected view).

## Max / agent integration

The Accounts list exposes one contextual tool, `open_account`, so Max can show an account on screen.

1. Backend `OpenAccountTool` (`products/customer_analytics/backend/max_tools/open_account.py`) resolves the account by `external_id` or name and returns `{ account_id, account_name, external_id, tab }`.
2. `AccountsMaxTools.tsx` registers it with `useMaxTool({ identifier: 'open_account', callback })`; the callback calls `accountsLogic.openAccount(accountId, externalId, name, tab)`.
3. `accountsLogic.openAccount`:
   - **Reveal** — if the account isn't in the current results (checks the bound data node's rows by name-cell `id`), it clears the excluding filters and searches by `external_id`/name so the row will render. This avoids a silent no-op when Max references an account that's filtered out.
   - **Expand** — dispatches `openAccountTab(accountId, tab)` (programmatic; deliberately does **not** fire the tab-viewed event).
   - **Scroll** — polls for the row's `[data-account-id]` node (revealing triggers an async refetch, so it may not exist yet) and smooth-scrolls it into view (`block: 'center'`). Runs through `cache.disposables` keyed `scrollToAccount` (a second open cancels a pending scroll), one-shot via `pauseOnPageHidden: false`. The scroll anchor is `data-account-id={id}` on the name cell in `AccountsHogQLTable.tsx` — keep it there.

The tool is registered for the page regardless of agent mode. The Customer analytics agent mode and the account→group bridge live in the backend (see below); keep their mechanics out of user-facing copy.

### Backend touchpoints

- `products/customer_analytics/backend/models` — the `Account` model (`external_id` = group key).
- `products/customer_analytics/backend/` — `accounts_query_runner` (builds the list rows + cell tuples).
- `products/customer_analytics/backend/max_tools/` — `OpenAccountTool` and other account Max tools.
- `ee/hogai/core/agent_modes/presets/customer_analytics.py` — the Customer analytics agent mode (gated by the `customer-analytics-csp` flag).

## Conventions

- **kea, not hooks** — business logic lives in the logics above; components are thin views. The one DOM concession is the `data-account-id` anchor for scroll. Resources needing cleanup (the scroll poll) go through `cache.disposables`, never a bare `setTimeout` + `beforeUnmount`.
- **Guard network triggers against double-submission** — role assignment disables its control while saving (`isRoleSaving`); follow the same pattern for any new mutation.
- **Capture exceptions** — wrap API calls and report failures with `posthog.captureException(error, { scope: '...' })` plus a `lemonToast`.
- **Tests & stories** — logics have `*.test.ts` siblings (`accountsLogic.test.ts`, etc.); `AccountsTab.stories.tsx` covers the rendered table. Add coverage alongside new behavior.

## Analytics events

We track user actions on the Accounts list with `posthog.capture()`. Conventions:

- Event names: `customer analytics accounts <verb> <object>` — lowercase, spaces. Property keys are `snake_case`.
- **Reference event names via the `AccountsEvents` const in `constants.ts`** — never pass a raw string to `posthog.capture`. A typo'd literal silently forks a new event in PostHog and breaks reporting with no error. When adding an event, add it to `AccountsEvents` and to the table below.
- Fire events in the **kea logic listeners** (where the action and its values live), not in components. Only fire from a component when no action exists for the interaction (the expanded-row links/notes).
- **Filters use a dedicated `reportFilterChange` action.** The raw filter setters (`setTagsFilter`, `setAssignedToFilter`, …) are also dispatched by URL sync (shared view links) and by cross-filter cascades (checking "unassigned only" clears the assigned-to filter, and vice versa), so capturing in their listeners would log phantom events. The filter controls dispatch `reportFilterChange(filterType)` on genuine interaction only; its listener reads the post-change state and captures. Add new filters the same way.
- Use the **effective/debounced** action where one exists (e.g. capture in the `setSearchInput` listener after its debounce) so events don't fire per keystroke.
- PII: log internal team members by `user_id` only (never email); never log raw search text, link URLs, or notebook titles.

### Tracked events

| Event                                                          | Fires from                                                                                                                            | Properties                                                                                                                                                                                  |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `customer analytics accounts list viewed`                      | `accountsLogic` `afterMount`                                                                                                          | _(none — funnel anchor; account count and saved-config aren't loaded at mount)_                                                                                                             |
| `customer analytics accounts filter changed`                   | `accountsLogic` `reportFilterChange` listener (dispatched by the filter controls)                                                     | `filter_type` (`tag` \| `unassigned_only` \| `my_accounts` \| `assigned_to`), `value`, `is_cleared`, `active_filter_count`; for `tag` also `tag_count`; for `assigned_to` also `role_count` |
| `customer analytics accounts searched`                         | `accountsLogic` `setSearchInput` listener (post-debounce)                                                                             | `query_length`, `has_query`, `active_filter_count`                                                                                                                                          |
| `customer analytics accounts refreshed`                        | `accountsLogic` `refresh`                                                                                                             | `has_search`, `active_filter_count`, `sort_column`                                                                                                                                          |
| `customer analytics accounts sorted`                           | `accountsLogic` `toggleSort`                                                                                                          | `column`, `direction` (`asc` \| `desc` \| `cleared`)                                                                                                                                        |
| ~~`customer analytics accounts columns saved`~~                | _Deprecated — no longer emitted. Column changes are now saved as part of a view (see view events below)._                             | _n/a_                                                                                                                                                                                       |
| `customer analytics accounts overview tiles edited`            | `accountsOverviewTilesLogic` editor close (diffed vs open snapshot, only when changed)                                                | `tiles_added`, `tiles_removed`, `tiles_updated`, `reordered`, `tile_count_before`, `tile_count_after`                                                                                       |
| `customer analytics accounts overview tiles localstorage read` | `accountsOverviewTilesLogic` `afterMount` (only when a legacy custom value exists)                                                    | `tile_count` — **tombstone**: a legacy localStorage tiles value was read; once this stops firing, no browser still carries one and the read path can be removed                             |
| `customer analytics accounts view saved`                       | `accountsViewsLogic` `submitNewViewForm` listener (success)                                                                           | `visibility` (`private` \| `shared`)                                                                                                                                                        |
| `customer analytics accounts view updated`                     | `accountsViewsLogic` `updateViewSuccess` listener                                                                                     | _(none)_                                                                                                                                                                                    |
| `customer analytics accounts view selected`                    | `accountsViewsLogic` `applyView` listener                                                                                             | `visibility`                                                                                                                                                                                |
| `customer analytics accounts view deleted`                     | `accountsViewsLogic` `deleteViewSuccess` listener                                                                                     | _(none)_                                                                                                                                                                                    |
| `customer analytics account role assigned`                     | `accountsLogic` `updateAccountRole`                                                                                                   | `role` (`csm` \| `account_executive` \| `account_owner`), `is_assigned`, `assigned_user_id`, `source` (always `list_row` today)                                                             |
| `customer analytics account link clicked`                      | `AccountNotebooksExpansion.tsx` useful-link `onClick`                                                                                 | `link_key`, `has_destination`                                                                                                                                                               |
| `customer analytics account note clicked`                      | `AccountNotebooksExpansion.tsx` note `<Link>` `onClick`                                                                               | `notebook_short_id`                                                                                                                                                                         |
| `customer analytics account tab viewed`                        | `accountsExpansionLogic` `setActiveTab` listener (genuine tab clicks only; programmatic `openAccountTab` navigation does not fire it) | `tab` (`notes` \| `users` \| `usage`)                                                                                                                                                       |
| `customer analytics account related user clicked`              | `AccountRelatedUsersExpansion.tsx` user `<Link>` `onClick`                                                                            | _(none — customer end-user PII kept out)_                                                                                                                                                   |

> **Keep this table up to date.** Whenever you add, rename, or remove a `posthog.capture()` event in the Accounts area — or change its properties — update this table in the same change. An agent reading this file should be able to trust it as the source of truth for what the Accounts list reports.

### Adding features and events

- **Instrument every new feature as you build it.** Any new user action on the accounts list should emit a `posthog.capture`, following this product's pattern and the wider PostHog pattern:
  - Add the event name to the `AccountsEvents` const in `constants.ts` and capture through it — never a raw string (a typo silently forks a new event in PostHog).
  - Keep the naming convention (`customer analytics accounts <verb> <object>`) and `snake_case` property keys.
  - Type discriminator property _values_ with a union (e.g. `AccountFilterType`, `AccountRoleKey`) rather than bare strings, so the value set is typo-proof and self-documenting — these are what dashboard breakdowns key off.
  - Fire from the kea logic listener where the values live; only fire from a component when no action exists. If the trigger is also dispatched by URL sync or cross-filter cascades, add a dedicated report action (see `reportFilterChange`).
  - Add a row to the table above.
- **Update the monitoring dashboard whenever events change.** New or changed events must be reflected in the "Customer analytics: Accounts list usage" dashboard in PostHog — add a new insight or extend an existing one so the metric is actually visible, don't just emit the event. For example, if you add a new tab to the expanded account row, its click event should feed the engagement-funnel insight (the "opened a link or note" step) and the feature-adoption insight — not just be captured.
