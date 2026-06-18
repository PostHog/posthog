# TaxonomicFilter architecture

There are two architectures living side by side: the **legacy** kea-driven
tree (below) and the **rebuild** (`menu/` + `headless/`, hooks-driven). See
the "Mirroring changes" table in `SKILL.md` for which concern lives where.
This file documents both.

## Legacy component tree

```text
TaxonomicFilter
├── TaxonomicFilterSearchInput        # debounced input + paste detection
├── CategoryDropdown                  # A/B-tested suffix picker (variant: 'pill')
└── InfiniteSelectResults
    ├── Tab buttons                   # one per visible group, hidden when empty
    ├── TaxonomicFilterEmptyState
    └── InfiniteList                  # AutoSizer + react-window virtualized list
        └── InfiniteListRow           # item / skeleton / pinned / recent
```

## Legacy logics

| File                                      | Owns                                                                                                  |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `taxonomicFilterLogic.tsx`                | Search query, active tab, group ordering, telemetry, keyboard nav. Spawns child list logics.          |
| `infiniteListLogic.ts`                    | Per-tab fetch, pagination, selection, property promotion, top-match donation, empty-result telemetry. |
| `recentTaxonomicFiltersLogic.ts`          | Recents persisted to localStorage, prefixed by team id.                                               |
| `taxonomicFilterPinnedPropertiesLogic.ts` | Pinned items persisted to localStorage, prefixed by team id.                                          |

Each `infiniteListLogic` is keyed by `taxonomicFilterLogicKey` + `listGroupType`.
Pinning/recents are shared singletons per team.

## Rebuild architecture (`menu/` + `headless/`)

Opt-in via `TAXONOMIC_FILTER_MENU_REBUILD`. Hooks-driven, not kea-driven —
it reimplements the legacy data layer rather than wrapping it.

```text
TaxonomicFilterMenu                     # menu/ — dropdown + combobox + DWH/HogQL sub-flows
└── TaxonomicFilterHeadless.Root        # headless/ — Root/Input/Categories/Panel
    └── useTaxonomicFilter              # hooks/ — orchestrator: query, active group, ordering, selectItem
        └── useGroupList (per tab)      # hooks/ — fetch + pagination + min-query-length
            └── useTaxonomicResource    # hooks/ — resolves a group's data source
                └── fetchTaxonomicListPage
```

| File                                                                              | Rebuild counterpart of                                                      |
| --------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `utils/buildTaxonomicGroups.tsx`                                                  | legacy `taxonomicGroups` selector                                           |
| `hooks/useTaxonomicFilter.ts`                                                     | legacy `taxonomicGroupTypes` selector + ordering                            |
| `hooks/useGroupList.ts` + `useTaxonomicResource.ts` + `fetchTaxonomicListPage.ts` | legacy `infiniteListLogic.ts`                                               |
| `hooks/useTaxonomicLocalOverrides.ts`                                             | feeds logic-backed group data the kea version got for free                  |
| `hooks/useTaxonomicGroupsContext.ts`                                              | the only kea-coupled layer of the rebuild (reads recents/pinned via bridge) |
| `menu/DwhFlow.tsx`                                                                | legacy DWH config inlined in `InfiniteList.tsx`                             |
| `menu/TaxonomicFilterMenu.tsx`                                                    | legacy telemetry in `taxonomicFilterLogic.tsx`                              |

`headless/UX_SPEC.md` is the rebuild's design source of truth — update it
when locking design, then build against it.

## Things that aren't where you'd guess

- **Suggested-filters aggregation lives in `infiniteListLogic`**, not
  the parent. See `topMatchesForQuery`, `isSuggestedFilters`, `results`.
  The parent only collects matches via `appendTopMatches` on
  `infiniteListResultsReceived`.
- **`PROMOTED_PROPERTIES_BY_SEARCH_TERM` is in `infiniteListLogic.ts`**,
  not in `taxonomicFilterLogic.tsx`.
- **Pinned/recent rows carry `_pinnedContext` / `_recentContext`** so
  `selectItem` records the _original_ `sourceGroupType` in telemetry,
  not "Pinned" or "Recents".

## Data flow on search

```text
user types
  -> taxonomicFilterLogic.setSearchQuery
     -> debounce -> infiniteListLogic[X].setSearchQuery (per group)
        -> API fetch -> loadRemoteItemsSuccess
           -> empty? fire 'taxonomic filter empty result'
           -> infiniteListResultsReceived(groupType, results)
              -> taxonomicFilterLogic.appendTopMatches(...)
universe of matches -> infiniteListLogic[SuggestedFilters].results
                       (via redistributeTopMatches)
```

`redistributeTopMatches` is a pure function — test in isolation.
Constants: `DEFAULT_SLOTS_PER_GROUP=5`, `MAX_TOP_MATCHES_PER_GROUP=10`,
`SKELETON_ROWS_PER_GROUP=3`. Empty groups donate slots to
`REDISTRIBUTION_PRIORITY_GROUPS` (`CustomEvents`, `PageviewUrls`, `Screens`).

## Selectors worth knowing

`taxonomicFilterLogic`: `activeTab`, `infiniteListCounts`,
`taxonomicGroups`, `topMatchItems` (aggregated via `appendTopMatches`).

`infiniteListLogic`: `topMatchesForQuery` (per-tab donated slice),
`isSuggestedFilters`, `results` (incl. skeletons, pinned, recents),
`showSuggestedFiltersEmptyState`.

Reactive prop behavior uses `propsChanged` + `afterMount`, never
kea-subscriptions — see [common-pitfalls.md](common-pitfalls.md).
