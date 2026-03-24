---
name: modifying-taxonomic-filter
description: Guides safe modification of the TaxonomicFilter component — PostHog's multi-tab search/filter for selecting events, actions, properties, cohorts, and more. Covers the component hierarchy, kea logic architecture, RTL testing workflow, and common pitfalls learned from prior changes. Use when adding features, fixing bugs, or refactoring TaxonomicFilter or its sub-components.
---

# Modifying the TaxonomicFilter

The TaxonomicFilter is one of PostHog's most complex frontend components.
It powers event/action/property/cohort selection across the entire app.
Changes here have a high blast radius — always lock down behavior with tests before modifying.

## Before you change anything

1. **Read the architecture** — understand which logic and component you're touching.
   See [references/architecture.md](references/architecture.md).
2. **Write RTL tests first** — capture the current behavior before making changes.
   See [references/testing-patterns.md](references/testing-patterns.md).
3. **Check common pitfalls** — avoid mistakes that have burned prior contributors.
   See [references/common-pitfalls.md](references/common-pitfalls.md).
4. **Run the existing test suite** to establish a green baseline:

   ```bash
   pnpm --filter=@posthog/frontend jest TaxonomicFilter
   ```

## Architecture at a glance

```text
TaxonomicFilter                    <- entry point, creates logic props
├── TaxonomicFilterSearchInput     <- keyboard events, search query
└── InfiniteSelectResults          <- tab pills + per-tab lists
    └── InfiniteList               <- virtualized list per group
        └── InfiniteListRow        <- individual result row
```

Three kea logics coordinate behavior:

| Logic                         | Role                                                     | Key file                                 |
| ----------------------------- | -------------------------------------------------------- | ---------------------------------------- |
| `taxonomicFilterLogic`        | Orchestrator — tabs, search, group ordering, top matches | `taxonomicFilterLogic.tsx` (~1600 lines) |
| `infiniteListLogic`           | Per-tab list — search, pagination, property promotion    | `infiniteListLogic.ts`                   |
| `recentTaxonomicFiltersLogic` | Recent selections persisted to localStorage              | `recentTaxonomicFiltersLogic.ts`         |

Each `infiniteListLogic` instance is keyed by `listGroupType` and connected to the parent `taxonomicFilterLogic`.

## Key concepts

### Group types

`TaxonomicFilterGroupType` is an enum with 40+ members (`Events`, `Actions`, `PersonProperties`, `PageviewUrls`, `SuggestedFilters`, etc.).
Each group type maps to a `TaxonomicFilterGroup` configuration object defining its endpoint, search behavior, display name, and value extraction.

### Tab ordering

Tabs are ordered by `taxonomicGroupTypes` prop order, but some groups get dynamically reordered.
"Shortcut" groups (`PageviewUrls`, `Screens`, `EmailAddresses`, etc.) are promoted after `SuggestedFilters` when present.
The `groupAnalyticsTaxonomicGroupType` selector normalizes group type names for analytics.

### Search redistribution

`redistributeTopMatches()` distributes search results across groups:

- Each group gets `DEFAULT_SLOTS_PER_GROUP` (5) slots
- Empty groups donate their unused slots to `REDISTRIBUTION_PRIORITY_GROUPS` (`CustomEvents`, `PageviewUrls`, `Screens`)
- Maximum `MAX_TOP_MATCHES_PER_GROUP` (10) results per group

### Skeleton rows

While search results load, `SKELETON_ROWS_PER_GROUP` (3) placeholder rows appear.
Use `isSkeletonItem()` to distinguish skeletons from real results.

### Property promotion

`infiniteListLogic` promotes properties matching exact search terms to the top of results.
`PROMOTED_PROPERTIES_BY_SEARCH_TERM` maps terms like `'url'` to `'$current_url'` and `'email'` to `'$email'`.

## Testing workflow

Always write tests **before** modifying behavior. Two levels of testing:

### Component tests (RTL)

Test what users see and interact with. Located in `TaxonomicFilter.test.tsx`.

```typescript
const rendered = renderFilter({ taxonomicGroupTypes: [TaxonomicFilterGroupType.Events] })
await waitFor(() => expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument())
```

Key patterns: `renderFilter()` helper, `expectActiveTab()` helper, `userEvent` for keyboard/click simulation.
See [references/testing-patterns.md](references/testing-patterns.md) for full details.

### Logic tests (kea-test-utils)

Test state transitions and async behavior. Located in `taxonomicFilterLogic.test.ts`.

```typescript
const logic = taxonomicFilterLogic(logicProps)
logic.mount()
await expectLogic(logic, () => logic.actions.setSearchQuery('pageview')).toMatchValues({ searchQuery: 'pageview' })
```

Key patterns: `expectLogic()`, `toMatchValues`, `toDispatchActions`, manual mounting of dependent `infiniteListLogic` instances.
See [references/testing-patterns.md](references/testing-patterns.md) for full details.

## File reference

| File                                                                       | Lines | Purpose                        |
| -------------------------------------------------------------------------- | ----- | ------------------------------ |
| `frontend/src/lib/components/TaxonomicFilter/TaxonomicFilter.tsx`          | ~240  | Entry component + search input |
| `frontend/src/lib/components/TaxonomicFilter/taxonomicFilterLogic.tsx`     | ~1600 | Core orchestration logic       |
| `frontend/src/lib/components/TaxonomicFilter/infiniteListLogic.ts`         | ~500  | Per-tab list logic             |
| `frontend/src/lib/components/TaxonomicFilter/types.ts`                     | ~280  | All type definitions           |
| `frontend/src/lib/components/TaxonomicFilter/InfiniteSelectResults.tsx`    | ~200  | Tab pills + list container     |
| `frontend/src/lib/components/TaxonomicFilter/InfiniteList.tsx`             | ~300  | Virtualized list               |
| `frontend/src/lib/components/TaxonomicFilter/TaxonomicFilter.test.tsx`     | ~660  | Component-level RTL tests      |
| `frontend/src/lib/components/TaxonomicFilter/taxonomicFilterLogic.test.ts` | ~710  | Logic-level tests              |

## Checklist for changes

- [ ] Read the relevant architecture section
- [ ] Write RTL tests capturing current behavior
- [ ] Make your change
- [ ] Verify all existing tests still pass
- [ ] Add new tests for the changed behavior
- [ ] Test keyboard navigation if you touched search or selection
- [ ] Test with multiple group types if you touched tab ordering
