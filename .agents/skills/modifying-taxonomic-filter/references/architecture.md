# TaxonomicFilter architecture

## Component hierarchy

```text
TaxonomicFilter
├── TaxonomicFilterSearchInput        # search box with debounced input
└── InfiniteSelectResults             # tab bar + virtualized list container
    ├── Tab buttons                   # one per visible TaxonomicFilterGroupType
    └── InfiniteList                  # virtualized list for the active tab
        └── InfiniteListRow           # individual item row (or skeleton)
```

### File locations

| File                             | Role                                                                       |
| -------------------------------- | -------------------------------------------------------------------------- |
| `TaxonomicFilter.tsx`            | Entry component, keyboard event handler (ArrowUp/Down, Tab, Enter, Escape) |
| `TaxonomicFilterSearchInput.tsx` | Search input with debounce                                                 |
| `InfiniteSelectResults.tsx`      | Tab bar rendering, delegates to InfiniteList                               |
| `InfiniteList.tsx`               | Virtualized list using AutoSizer + react-window                            |
| `InfiniteListRow.tsx`            | Renders a single item or skeleton row                                      |
| `types.ts`                       | All TypeScript types and the `TaxonomicFilterGroupType` enum               |

## Kea logic hierarchy

Three logics cooperate to manage state:

| Logic                         | File                                     | Responsibility                                                                                                                                                                           |
| ----------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `taxonomicFilterLogic`        | `taxonomicFilterLogic.tsx` (~1600 lines) | Orchestrator. Manages search query, active tab, group ordering, top matches redistribution, keyboard navigation between tabs. Creates child `infiniteListLogic` per group type.          |
| `infiniteListLogic`           | `infiniteListLogic.ts` (~500 lines)      | Per-tab list management. Handles fetching remote items, local filtering, pagination, item selection, and keyboard navigation within a list. One instance per `TaxonomicFilterGroupType`. |
| `recentTaxonomicFiltersLogic` | `recentTaxonomicFiltersLogic.ts`         | Persists recently selected items to localStorage. Shared across filter instances.                                                                                                        |

### Logic instantiation

`taxonomicFilterLogic` is keyed by `taxonomicFilterLogicKey` (a string prop).
Each child `infiniteListLogic` is keyed by the same key plus the `listGroupType`.

```text
taxonomicFilterLogic({ taxonomicFilterLogicKey: 'my-filter', ... })
  ├── infiniteListLogic({ ..., listGroupType: Events })
  ├── infiniteListLogic({ ..., listGroupType: Actions })
  ├── infiniteListLogic({ ..., listGroupType: PersonProperties })
  └── ...one per group type in taxonomicGroupTypes prop
```

## Key concepts

### TaxonomicFilterGroupType

An enum with 40+ members defining every category the filter can display.
Each group type maps to a data source (API endpoint or local data) and has
its own rendering logic.

Common group types:

- `Events`, `Actions`, `PersonProperties`, `EventProperties`
- `PageviewUrls`, `Screens`, `EmailAddresses` (shortcut property types)
- `SuggestedFilters` (cross-group search results)
- `Cohorts`, `CohortsWithAllUsers`
- `HogQLExpression`, `SessionProperties`

### Group ordering and tab visibility

The `taxonomicGroupTypes` prop controls which tabs appear and their order.
Some groups are dynamically reordered based on search:

- **Shortcut groups** (`PageviewUrls`, `Screens`, `EmailAddresses`, etc.)
  are promoted after `SuggestedFilters` when a search matches them
- Empty groups are hidden from the tab bar
- `tabRight()` and `tabLeft()` actions skip empty groups

### Search flow

1. User types → `setSearchQuery` action on `taxonomicFilterLogic`
2. Logic debounces and dispatches to each child `infiniteListLogic`
3. Each list logic fetches remote items from its API endpoint
4. Results populate `remoteItems` in each list logic
5. `taxonomicFilterLogic` aggregates counts via `infiniteListCounts` selector
6. If `SuggestedFilters` group exists, `appendTopMatches` collects top results
   from all groups and `redistributeTopMatches` distributes them evenly

### `redistributeTopMatches`

A pure function that distributes suggested filter results across groups:

- `DEFAULT_SLOTS_PER_GROUP`: 5 items per group initially
- `MAX_TOP_MATCHES_PER_GROUP`: 10 items maximum per group
- Groups with fewer results give their unused slots to groups with more

### Skeleton rows

While data is loading, `SKELETON_ROWS_PER_GROUP` (3) placeholder rows
are shown. These are `SkeletonItem` objects (with `is_skeleton: true`)
that render as animated loading placeholders.

### Property promotion

`PROMOTED_PROPERTIES_BY_SEARCH_TERM` maps common search terms to specific
properties. For example, searching "url" promotes `$current_url` to the top
of results. This is handled inside `taxonomicFilterLogic`.

### Shortcut group types

`SHORTCUT_TO_PROPERTY_FILTER_GROUP_TYPES` defines group types that are
"shortcuts" to specific property filter types:

- `PageviewUrls`, `PageviewEvents`
- `Screens`, `ScreenEvents`
- `EmailAddresses`, `AutocaptureEvents`

These groups search the same underlying data as property filters but
present a more focused UI for common use cases.

## Data flow diagram

```text
User input
    │
    ▼
TaxonomicFilter (keyboard handler)
    │
    ▼
taxonomicFilterLogic
    ├── setSearchQuery ──► infiniteListLogic[Events].setSearchQuery
    ├──────────────────► infiniteListLogic[Actions].setSearchQuery
    ├──────────────────► infiniteListLogic[PersonProperties].setSearchQuery
    │                        │
    │                        ▼
    │                   API fetch (event_definitions, property_definitions, etc.)
    │                        │
    │                        ▼
    │                   loadRemoteItemsSuccess
    │                        │
    ▼                        ▼
appendTopMatches ◄──── results from all list logics
    │
    ▼
redistributeTopMatches (pure function)
    │
    ▼
SuggestedFilters tab populated
```

## Important selectors

| Logic                  | Selector                     | Returns                                      |
| ---------------------- | ---------------------------- | -------------------------------------------- |
| `taxonomicFilterLogic` | `activeTab`                  | Current `TaxonomicFilterGroupType`           |
| `taxonomicFilterLogic` | `searchQuery`                | Current search string                        |
| `taxonomicFilterLogic` | `infiniteListCounts`         | `Record<GroupType, number>` of result counts |
| `taxonomicFilterLogic` | `taxonomicGroups`            | Ordered array of group configs               |
| `taxonomicFilterLogic` | `topMatchItems`              | Raw top match items before redistribution    |
| `taxonomicFilterLogic` | `redistributedTopMatchItems` | Items after slot redistribution              |
| `infiniteListLogic`    | `results`                    | Items for this group                         |
| `infiniteListLogic`    | `totalResultCount`           | Total count including remote                 |
| `infiniteListLogic`    | `isLoading`                  | Whether fetch is in progress                 |
