# Telemetry contract

Dashboards, experiments and replay scanners read these events.
Treat property shapes as a public API.
The lists below match the code on 2026-10-15.
The `posthog.capture` call is the source of truth, so read it before you remove or rename a property.

- **Adding** a property: fine.
- **Removing** a dead one: fine, once nothing reads it.
- **Renaming or repurposing silently** is the worst case.
  Dashboards keep working and start lying.

The legacy stamp `legacy-pill` comes from `legacyTaxonomicSurface()` in `taxonomicFilterSurface.ts`.
The rebuild stamps `rebuild-menu` from `TAXONOMIC_FILTER_SURFACE` in `menu/types.ts`.
Only the events marked "with `surface`" below carry it.
Older data also has `legacy-control` and empty values.
A filter such as `surface = 'legacy-pill'` drops every row without the property, so check the list before you filter.

## `groupType` vs `sourceGroupType`

On `taxonomic filter item selected`:

- `groupType` is the tab that was active when the user picked.
- `sourceGroupType` is the group the item belongs to.

A pick from Suggested has `groupType = suggested_filters` and a real `sourceGroupType`.
To judge whether a group's items are used, count `sourceGroupType`.
To judge whether a tab is used, count `groupType`.
Mixing them up makes reachable groups look unused.

This holds for legacy only.
The rebuild sends no `groupType` for its `all`, `recent` and `pinned` scopes (`telemetryGroupType` in `menu/Combobox.tsx`), so its data cannot tell those three apart.
In a query over both surfaces, label an empty `groupType` from `rebuild-menu` as an unknown meta-scope.
Do not fold it into Suggested or All, or treat it as Recent: the standalone Recent and Pinned picks are in there too.
Telling the scopes apart needs new telemetry.

## Shared events (both surfaces)

Keep these comparable across arms.
Add a property to both emitters or neither.
All carry `surface` on both surfaces, except `include stale toggled`, which carries it on the rebuild only.

- `taxonomic filter closed`: `dwellMs`, `hadSelection`, `categoryRailDocked`.
  Legacy also sends `groupType`; the rebuild omits it because there is no single active tab at close.
  Legacy sends it only when `hadInteraction` is true.
  The rebuild sends it on every close, so their selection rates have different denominators.
- `taxonomic filter item selected`: `groupType`, `sourceGroupType`, `wasFromRecents`, `wasFromPinnedList`, `wasQuickFilter`, `hadSearchInput`, `position`, `query`, `wasStale`, `wasUrlContainsShortcut`.
  Legacy sends `wasUrlContainsShortcut` only on a quick filter, with `filterName`, `propertyKey`, `operator`, `filterValue`, `propertyFilterType` and `eventName`.
  The rebuild always sends `wasUrlContainsShortcut` and none of the others.
- `taxonomic_filter_search_query`: `searchQuery`, `groupType`, `inputMode`, `pastedFraction`, `excludeStale`.
- `taxonomic filter empty result`: `groupType`, `searchQuery`.
  Legacy sends it only from a remote list on the active tab.
  Suggested is a local list, so its empty state sends nothing.
  Add coverage there before you measure a change to the Suggested empty state.
- `taxonomic filter include stale toggled`: `includeStaleEvents`, `groupType`, `searchQuery`.
  Only the rebuild sends `surface` on this one.

## Legacy only, with `surface`

- `taxonomic filter search latency`: `groupType`, `searchQuery`, `resultCount`, `time_to_see_data_ms`.
  The rebuild does not send it yet (see `hooks/useGroupList.ts`).
- `taxonomic filter fetch failed`: `groupType`, `searchQuery`.
  It has also fired on first-load failures since 2026-09-13.
  Rates from before then are not comparable.
  The rebuild does not send it.
- `taxonomic filter search intent predicted`: `query`, `activeTab`, `predictedGroupType`, `confidence`, `isConfident`, `suggestsSwitch`, `wouldPromote`, `promptVersion`, `source`, `variant`, `inTime`, `shown`.
  The banner funnel in [refreshing-product-reality](refreshing-product-reality.md) reads `variant` and `shown`.
- `taxonomic filter search intent switched`: `fromGroupType`, `toGroupType`.
- `taxonomic filter event match suggested`: `suggestedEvents`, `tab`.
- `taxonomic filter event match selected`: `eventName`, `position`, `tab`.

Read the event match events as a funnel: answered, then suggested, then selected.

## Legacy only, without `surface`

- `taxonomic filter add filter clicked`: `eventName`.
  Fires only when a property filter row opens with no valid filter yet.
  Most opens do not send it, so do not use it to split sessions into opens.
  Split after each legacy `taxonomic filter closed` instead.
- `taxonomic filter category selected`: `groupType`, `eventName`.
- `taxonomic filter category dropdown opened`: `variant`.
- `taxonomic filter category rail toggled`: `docked`.
- `taxonomic filter pin toggled`: `groupType`, `value`, `pinned`.
- `taxonomic filter default pins seeded`: `values`.
- `taxonomic filter event match answered`: `outcome`.
  Emitted server side.

## Rebuild only, without `surface`

Every event here comes from the rebuild, so no `surface` filter is needed.
Do not add `surface = 'rebuild-menu'` to a query on them: it returns no rows.

- `taxonomic filter menu opened`: `openedTo`, `hadSelection`, `triggerLabel`, `msSinceLastClose`, `reopenedQuickly`.
- `taxonomic filter menu drilled`: `fromState`, `toState`.
- `taxonomic filter menu closed`: `dwellMs`, `hadCommit`, `lastState`.
- `taxonomic filter menu option clicked`: `option`.
- `taxonomic filter menu item selected`: `groupType`, `hadSearchInput`, `query`, `hadExtras`, `fromState`, `msSinceOpen`.
- `taxonomic filter menu category changed`: `fromChip`, `toChip`, `via`, and `direction` when `via` is `tab`.
- `taxonomic filter menu pin toggled`: `groupType`, `pinned`.

`taxonomic filter menu preference changed` (`useNewMenu`, no `surface`) comes from the classic/new toggle.
It fires on either surface for users who have the rebuild flag.

## Before changing telemetry

1. Search dashboards and insights for the event and property (`system.insights` via the PostHog MCP).
2. Check the replay scanners' prompts if they mention the behavior.
3. Update [refreshing-product-reality](refreshing-product-reality.md) if a query uses it.
