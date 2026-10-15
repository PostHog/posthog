# Telemetry contract

Dashboards, experiments and replay scanners read these events. Treat
property shapes as a public API.

- **Adding** a property: fine.
- **Removing** a dead one: fine, once nothing reads it.
- **Renaming or repurposing silently** is the worst case. Dashboards keep
  working and start lying.

Most `taxonomic filter *` events carry `surface` (`legacy-pill` or
`rebuild-menu`). The legacy stamp comes from `legacyTaxonomicSurface()` in
`taxonomicFilterSurface.ts`. The rebuild stamps `rebuild-menu` from
`menu/TaxonomicFilterMenu.tsx`. These events have no `surface`:
`category selected`, `category rail toggled`, `pin toggled` and
`default pins seeded`. Older data also has `legacy-control` and empty
values. A filter such as `surface = 'legacy-pill'` drops all of those
rows.

## `groupType` vs `sourceGroupType`

On `taxonomic filter item selected`:

- `groupType` is the tab that was active when the user picked.
- `sourceGroupType` is the group the item belongs to.

A pick from Suggested has `groupType = suggested_filters` and a real
`sourceGroupType`. To judge whether a group's items are used, count
`sourceGroupType`. To judge whether a tab is used, count `groupType`.
Mixing them up makes reachable groups look unused.

## Shared events (both surfaces)

Keep these comparable across arms. Add a property to both emitters or
neither.

- `taxonomic filter closed`: `surface`, `dwellMs`, `hadSelection`,
  `categoryRailDocked`. Legacy also sends `groupType`; the rebuild omits
  it because there is no single active tab at close. Legacy sends it only
  when `hadInteraction` is true. The rebuild sends it on every close, so
  their selection rates have different denominators.
- `taxonomic filter item selected`: `surface`, `groupType`,
  `sourceGroupType`, `wasFromRecents`, `wasFromPinnedList`,
  `wasQuickFilter`, `hadSearchInput`, `position`, `query`, `wasStale`.

## Search and results

- `taxonomic_filter_search_query`: `searchQuery`, `groupType`,
  `inputMode`, `pastedFraction`. Both surfaces send it (the rebuild from
  `menu/Combobox.tsx`), so filter by `surface`.
- `taxonomic filter empty result`: `groupType`, `searchQuery`, `surface`.
  Legacy sends it only from a remote list on the active tab. Suggested is
  a local list, so its empty state sends nothing. Add coverage there
  before you measure a change to the Suggested empty state.
- `taxonomic filter search latency`: `groupType`, `searchQuery`,
  `resultCount`, `time_to_see_data_ms`, `surface`. Legacy only: the
  rebuild does not send it yet (see `hooks/useGroupList.ts`).
- `taxonomic filter fetch failed`: `groupType`, `searchQuery`, `surface`.
  It has also fired on first-load failures since 2026-09-13. Rates from
  before then are not comparable.

## Navigation and preferences

- `taxonomic filter add filter clicked`: fires only when a property
  filter row opens with no valid filter yet. Most opens do not send it,
  so do not use it to split sessions into opens. Split after each legacy
  `taxonomic filter closed` instead.
- `taxonomic filter category selected`: `groupType`.
- `taxonomic filter category dropdown opened`: legacy pill only.
- `taxonomic filter category rail toggled`: `docked`.
- `taxonomic filter pin toggled`: `groupType`, `pinned`.
- `taxonomic filter include stale toggled`.
- `taxonomic filter default pins seeded`.

## Assistive features

- `taxonomic filter search intent predicted`: `query`, `activeTab`,
  `predictedGroupType`, `confidence`, `isConfident`, `suggestsSwitch`,
  `wouldPromote`, `promptVersion`, `source`, `surface`, `variant`,
  `inTime`, `shown`. The banner funnel in
  [refreshing-product-reality](refreshing-product-reality.md) reads
  `variant` and `shown`.
- `taxonomic filter search intent switched`: `fromGroupType`,
  `toGroupType`, `surface`.
- `taxonomic filter event match answered`: emitted server side.
- `taxonomic filter event match suggested`: `suggestedEvents`, `surface`.
- `taxonomic filter event match selected`: `eventName`, `position`,
  `surface`.

Read these as funnels: answered, then suggested, then selected.

## Rebuild-only menu events

`taxonomic filter menu opened` / `drilled` / `closed` / `option clicked` /
`item selected` / `category changed` / `preference changed` /
`pin toggled`.

## Before changing telemetry

1. Search dashboards and insights for the event and property
   (`system.insights` via the PostHog MCP).
2. Check the replay scanners' prompts if they mention the behavior.
3. Update [refreshing-product-reality](refreshing-product-reality.md) if a
   query uses it.
