# Accounts — agent guide

Guidance for agents working on the Accounts area of Customer analytics (`products/customer_analytics/frontend/components/Accounts/`). Scope is the **Accounts list** only, not the rest of Customer analytics.

## Analytics events

We track user actions on the Accounts list with `posthog.capture()`. Conventions:

- Event names: `customer analytics accounts <verb> <object>` — lowercase, spaces. Property keys are `snake_case`.
- Fire events in the **kea logic listeners** (where the action and its values live), not in components. Only fire from a component when no action exists for the interaction (the expanded-row links/notes).
- **Filters use a dedicated `reportFilterChange` action.** The raw filter setters (`setTagsFilter`, `setCsmFilter`, …) are also dispatched by URL sync (shared view links) and by cross-filter cascades (checking "unassigned only" clears the role filters), so capturing in their listeners would log phantom events. The filter controls dispatch `reportFilterChange(filterType)` on genuine interaction only; its listener reads the post-change state and captures. Add new filters the same way.
- Use the **effective/debounced** action where one exists (e.g. capture in the `setSearchInput` listener after its debounce) so events don't fire per keystroke.
- PII: log internal team members by `user_id` only (never email); never log raw search text, link URLs, or notebook titles.

### Tracked events

| Event                                               | Fires from                                                                             | Properties                                                                                                                                                              |
| --------------------------------------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `customer analytics accounts list viewed`           | `accountsLogic` `afterMount`                                                           | _(none — funnel anchor; account count and saved-config aren't loaded at mount)_                                                                                         |
| `customer analytics accounts filter changed`        | `accountsLogic` `reportFilterChange` listener (dispatched by the filter controls)      | `filter_type` (`tag` \| `csm` \| `account_executive` \| `account_owner` \| `unassigned_only`), `value`, `is_cleared`, `active_filter_count`; for `tag` also `tag_count` |
| `customer analytics accounts searched`              | `accountsLogic` `setSearchInput` listener (post-debounce)                              | `query_length`, `has_query`, `active_filter_count`                                                                                                                      |
| `customer analytics accounts refreshed`             | `accountsLogic` `refresh`                                                              | `has_search`, `active_filter_count`, `sort_column`                                                                                                                      |
| `customer analytics accounts sorted`                | `accountsLogic` `toggleSort`                                                           | `column`, `direction` (`asc` \| `desc` \| `cleared`)                                                                                                                    |
| `customer analytics accounts columns saved`         | `accountsColumnConfigLogic` `saveColumns` (success, only when changed)                 | `column_count`, `columns`, `added_count`, `removed_count`, `reordered`                                                                                                  |
| `customer analytics accounts overview tiles edited` | `accountsOverviewTilesLogic` editor close (diffed vs open snapshot, only when changed) | `tiles_added`, `tiles_removed`, `tiles_updated`, `reordered`, `tile_count_before`, `tile_count_after`                                                                   |
| `customer analytics account role assigned`          | `accountsLogic` `updateAccountRole`                                                    | `role` (`csm` \| `account_executive` \| `account_owner`), `is_assigned`, `assigned_user_id`                                                                             |
| `customer analytics account link clicked`           | `AccountNotebooksExpansion.tsx` useful-link `onClick`                                  | `link_key`, `has_destination`                                                                                                                                           |
| `customer analytics account note clicked`           | `AccountNotebooksExpansion.tsx` note `<Link>` `onClick`                                | `notebook_short_id`                                                                                                                                                     |

> **Keep this table up to date.** Whenever you add, rename, or remove a `posthog.capture()` event in the Accounts area — or change its properties — update this table in the same change. An agent reading this file should be able to trust it as the source of truth for what the Accounts list reports.
