# TaxonomicFilter architecture

## Component tree

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

## Logics

| File                                      | Owns                                                                                                  |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `taxonomicFilterLogic.tsx`                | Search query, active tab, group ordering, telemetry, keyboard nav. Spawns child list logics.          |
| `infiniteListLogic.ts`                    | Per-tab fetch, pagination, selection, property promotion, top-match donation, empty-result telemetry. |
| `recentTaxonomicFiltersLogic.ts`          | Recents persisted to localStorage, prefixed by team id.                                               |
| `taxonomicFilterPinnedPropertiesLogic.ts` | Pinned items persisted to localStorage, prefixed by team id.                                          |

Each `infiniteListLogic` is keyed by `taxonomicFilterLogicKey` + `listGroupType`.
Pinning/recents are shared singletons per team.

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
