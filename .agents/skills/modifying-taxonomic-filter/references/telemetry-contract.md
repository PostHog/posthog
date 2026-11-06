# Telemetry contract

Dashboards, experiments and replay scanners read these events.
Treat property shapes as a public API.
`frontend/src/lib/components/TaxonomicFilter/telemetryContract.test.ts` reads every `taxonomic filter` capture call and fails when an event or property is missing here, or when an event listed here is no longer sent.
When it fails, update this file in the same PR.

- **Adding** a property: fine.
- **Removing** a dead one: fine, once nothing reads it.
- **Renaming or repurposing silently** is the worst case.
  Dashboards keep working and start lying.

Every event here carries `surface = 'legacy-pill'`, stamped by `legacyTaxonomicSurface()` in `taxonomicFilterSurface.ts`.
Only the events marked "with `surface`" below carry the property at all.
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

## Events, with `surface`

- `taxonomic filter closed`: `dwellMs`, `hadSelection`, `categoryRailDocked`, `groupType`.
  Sent only when `hadInteraction` is true.
- `taxonomic filter item selected`: `groupType`, `sourceGroupType`, `wasFromRecents`, `wasFromPinnedList`, `wasQuickFilter`, `hadSearchInput`, `position`, `query`, `wasStale`, `wasUrlContainsShortcut`.
  `wasUrlContainsShortcut` is sent only on a quick filter, with `filterName`, `propertyKey`, `operator`, `filterValue`, `propertyFilterType` and `eventName`.
- `taxonomic_filter_search_query`: `searchQuery`, `groupType`, `inputMode`, `pastedFraction`, `excludeStale`.
- `taxonomic filter empty result`: `groupType`, `searchQuery`, `scope`.
  `scope` is `all` for the aggregate All view and `category` for a content category.
  Sent for the All view when its visible empty state renders after contributing lists settle without a fetch failure.
  Its `groupType` remains `suggested_filters` for the All view.
  Empty or whitespace-only searches do not count.
  Repeated renders of the same trimmed query do not send another event.
  Content categories send it from successful remote searches on the active tab.
  Older data has no All-tab empty events, and older events have no `scope`.
  Compare periods with the same coverage.
- `taxonomic filter fetch failed`: `groupType`, `searchQuery`, `forbidden` (true when the request was refused with a 403).
  Sent once per group and query while the request keeps failing.
  Sent on first-load failures since 2026-09-13, so rates from before then are not comparable.
- `taxonomic filter include stale toggled`: `includeStaleEvents`, `groupType`, `searchQuery`.
- `taxonomic filter search latency`: `groupType`, `searchQuery`, `resultCount`, `time_to_see_data_ms`, `revealedBy`, `pendingGroupTypes`.
  A category tab sends it when its own fetch lands, and `time_to_see_data_ms` is the fetch time.
  The All tab sends it when its rows reveal, with `groupType: suggested_filters`, `revealedBy` and `pendingGroupTypes`.
  There `time_to_see_data_ms` runs from the last keystroke, so it includes the input debounce.
  Compare the two only by `groupType`.
- `taxonomic filter search intent predicted`: `query`, `activeTab`, `predictedGroupType`, `confidence`, `isConfident`, `suggestsSwitch`, `wouldPromote`, `promptVersion`, `source`, `variant`, `inTime`, `shown`.
  The banner funnel in [refreshing-product-reality](refreshing-product-reality.md) reads `variant` and `shown`.
- `taxonomic filter search intent switched`: `fromGroupType`, `toGroupType`.

## Events, without `surface`

- `taxonomic filter add filter clicked`: `eventName`.
  Fires only when a property filter row opens with no valid filter yet.
  Most opens do not send it, so do not use it to split sessions into opens.
  Split after each `taxonomic filter closed` instead.
- `taxonomic filter category selected`: `groupType`, `eventName`.
- `taxonomic filter category dropdown opened`: `variant`.
- `taxonomic filter category rail toggled`: `docked`.
- `taxonomic filter pin toggled`: `groupType`, `value`, `pinned`.
  Sent from the shared `taxonomicFilterPinnedPropertiesLogic.ts`.
- `taxonomic filter default pins seeded`: `values`.

## Before changing telemetry

1. Search dashboards and insights for the event and property (`system.insights` via the PostHog MCP).
2. Check the replay scanners' prompts if they mention the behavior.
3. Update [refreshing-product-reality](refreshing-product-reality.md) if a query uses it.
