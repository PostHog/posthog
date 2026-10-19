# Telemetry contract

Dashboards, experiments and replay scanners read these events.
Treat property shapes as a public API.
`frontend/src/lib/components/TaxonomicFilter/telemetryContract.test.ts` reads every `taxonomic filter` capture call and fails when an event or property is missing here, or when an event listed here is no longer sent.
When it fails, update this file in the same PR.

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
HogQL and data warehouse commits (`menu/HogQLEditor.tsx`, `menu/DwhFlow.tsx`) also send no `groupType`, because they commit without a selection context.
They still send `sourceGroupType`, so split those rows out by `sourceGroupType` before you label the rest as a meta-scope.

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
- `taxonomic filter empty result`: `groupType`, `searchQuery`, `scope`.
  `scope` is `all` for the aggregate All view and `category` for a content category.
  The rebuild also uses `recent` and `pinned` for those scopes.
  Legacy All sends it when its visible empty state renders after contributing lists settle without a fetch failure.
  Its `groupType` remains `suggested_filters`; rebuild All keeps `groupType` unset.
  Empty or whitespace-only searches do not count.
  Repeated renders of the same trimmed query do not send another event.
  Legacy content categories send it from successful remote searches on the active tab.
  Older legacy data has no All-tab empty events, and older events have no `scope`.
  Compare periods with the same coverage.
- `taxonomic filter fetch failed`: `groupType`, `searchQuery`, and on legacy `forbidden` (true when the request was refused with a 403).
  Each surface sends it once per group or scope and query while the request keeps failing.
  Legacy has also sent it on first-load failures since 2026-09-13, so legacy rates from before then are not comparable.
  The rebuild sends no `groupType` on its `all`, `recent` and `pinned` scopes.
- `taxonomic filter include stale toggled`: `includeStaleEvents`, `groupType`, `searchQuery`.
  Only the rebuild sends `surface` on this one.

## Legacy only, with `surface`

- `taxonomic filter search latency`: `groupType`, `searchQuery`, `resultCount`, `time_to_see_data_ms`, `revealedBy`, `pendingGroupTypes`.
  A category tab sends it when its own fetch lands, and `time_to_see_data_ms` is the fetch time.
  The All tab sends it when its rows reveal, with `groupType: suggested_filters`, `revealedBy` and `pendingGroupTypes`.
  There `time_to_see_data_ms` runs from the last keystroke, so it includes the input debounce. Compare the two only by `groupType`.
  The rebuild does not send it yet (see `hooks/useGroupList.ts`).
- `taxonomic filter search intent predicted`: `query`, `activeTab`, `predictedGroupType`, `confidence`, `isConfident`, `suggestsSwitch`, `wouldPromote`, `promptVersion`, `source`, `variant`, `inTime`, `shown`.
  The banner funnel in [refreshing-product-reality](refreshing-product-reality.md) reads `variant` and `shown`.
- `taxonomic filter search intent switched`: `fromGroupType`, `toGroupType`.
- `taxonomic filter event match eligible`: `tab`, `variant`.
  Sent once per project and query when the search qualifies for event match. The experiment's exposure reads it.
- `taxonomic filter event match hint shown`: `tab`, `hint`, and `unsentEvents` when `hint` is `unsent`.
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
- `taxonomic filter event match answered`: `outcome`.
  Emitted server side.

## Both surfaces, without `surface`

These come from the shared `taxonomicFilterPinnedPropertiesLogic.ts`, which both surfaces call.
Nothing on them says which surface sent them.

- `taxonomic filter pin toggled`: `groupType`, `value`, `pinned`.
  A rebuild pin click sends `taxonomic filter menu pin toggled` and then this one too, so do not add the two together.
- `taxonomic filter default pins seeded`: `values`.

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

## Toggle, either surface, without `surface`

- `taxonomic filter menu preference changed`: `useNewMenu`.
  It comes from the classic/new toggle and fires on either surface for users who have the rebuild flag.

## Before changing telemetry

1. Search dashboards and insights for the event and property (`system.insights` via the PostHog MCP).
2. Check the replay scanners' prompts if they mention the behavior.
3. Update [refreshing-product-reality](refreshing-product-reality.md) if a query uses it.
