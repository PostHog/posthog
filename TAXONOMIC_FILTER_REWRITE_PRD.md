# TaxonomicFilter Rewrite PRD

**Status:** Living document. Will keep writing as discovery continues.
**Goal:** Replace the kea-based `TaxonomicFilter` with a headless `useTaxonomicFilter` hook + base-ui/quill-primitive view layer, without behavioral loss across ~100 callsites.
**Owner:** @adam
**Date opened:** 2026-04-27
**Last updated:** 2026-04-27 (Phase 5 complete — flag-gated rollout wired; quill move deferred until parity is proven)

## Changelog

- **2026-04-27 (decision: keep v1 in `frontend/` until parity-confirmed):** Briefly explored moving the headless component into `packages/quill/packages/components/src/filters/taxonomic/v1/` so it could ship via the existing quill storybook (the local PostHog storybook hits a Node-25 / wiped-Nix-store issue). Reverted before completing — the right ordering is **parity-validate in-place first, then move**:
  - The legacy and headless paths must be proven to match 1:1 across the consumer set before the API freezes against a quill-package boundary.
  - PostHog can iterate the headless implementation freely while it's in `frontend/` (no version bump or dep cycle).
  - Generic types in quill (string-based group types) only become useful once the PostHog-specific shape has stabilised.
  - Storybook visual review still works locally under Node 24 — the prior failure was a stale flox env (Nix store garbage-collected); switching to `nvm use 24` (which I confirmed via `node v24.15.0`) lets the local storybook compile through the previously-broken `@posthog/tailwind:build` step.
  - Phase 6 added: build a parameterised RTL parity test that runs the existing `TaxonomicFilter` test suite under both flag values to keep the legacy and headless paths interchangeable.
  - Phase 7 (renumbered): move the proven primitive into `packages/quill/packages/components/src/filters/taxonomic/v1/` once parity is signed off.

- **2026-04-27 (Phase 5 complete):** Flag-gated rollout in place.
  - `TaxonomicFilterAdapter.tsx` — translation layer that maps the legacy `TaxonomicFilterProps` API onto the headless component tree. `onClose` is forwarded by intercepting Escape at the adapter level (the headless API doesn't ship a dedicated onClose option). Adapter omits the search input when `hideSearchInput`, omits the Categories tab strip for single-tab variants. Documented limitations: legacy `definitionPopoverRenderer`, DataWarehouse pinned-row, and SuggestedFilters cross-tab top-match aggregation are not yet wired (deferred from earlier phases). Anything in those buckets falls back to the kea path until completed.
  - `TaxonomicFilter.tsx` — entry component now reads `featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_HEADLESS]`. When **on** → `<TaxonomicFilterAdapter {...props} />` (new headless path). When **off** → `<TaxonomicFilterLegacy {...props} />` (existing kea body, unchanged). Single source of truth for every consumer; no call-site changes needed for the flip.
  - `headless/TaxonomicFilterHeadless.stories.tsx` — Storybook stories for visual review of the headless component in isolation: Events+Actions, Properties, SuggestedFilters with custom label.
  - **Full TaxonomicFilter suite still green: 299/299 across 14 suites** with both paths coexisting.
  - Rollout plan: ship flag at 0% → enable in dev → 1% → 10% → 100%, watching for `eventUsageLogic` regressions and any regressions specific to the deferred buckets above.

- **2026-04-27 (Phase 4 complete):** Headless component layer shipped, on top of Quill primitives.
  - Pulled master after merging quill into the repo proper (`@posthog/quill` is npm-importable; in-tree alias `lib/ui/quill` re-exports it).
  - `headless/context.ts` — `TaxonomicFilterContext` + `useTaxonomicFilterContext()` for sharing the orchestrator api.
  - `headless/Root.tsx` — wraps `useTaxonomicFilter` and provides context. Spreads `rootProps.onKeyDown` onto the wrapping div by default.
  - `headless/Input.tsx` — Quill `<InputGroup>` + `<InputGroupInput>` (Base UI Input under the hood). Accepts `prefix` / `suffix` slots for icon and clear button.
  - `headless/Categories.tsx` — Quill `<Button variant="primary"|"outline" size="sm">` per tab. Calls `useGroupList` per tab to get the count + loading flag. Accepts `renderTab` for full override.
  - `headless/Panel.tsx` — Renders the active group via `useGroupList`, registers its api with the orchestrator for keyboard nav. Uses Quill `<ItemMenuItem>` for rows, `<Empty>` + `<EmptyHeader>` + `<EmptyTitle>` for empty / loading states. Accepts `renderRow`, `emptyState`, `loadingState` overrides.
  - `headless/index.ts` — `TaxonomicFilterHeadless = { Root, Input, Categories, Panel }` compound API.
  - `headless/headless.test.tsx` — 7 RTL integration tests covering mount, render, search filtering, click select, tab switch, Enter select, empty state.
  - **Full TaxonomicFilter suite green: 299/299 across 14 suites.**

  Notes for Phase 5:
  - The Quill `<Combobox>` primitive (Base UI Combobox + InputGroupInput render path) is a tempting fit for the search input, but its semantics assume a single popup-list of items. TaxonomicFilter has separate Categories + Panel surfaces, so we kept `<InputGroup>` + plain input rather than wrapping in a Combobox. If we ever collapse to a single popup list (for a smaller-footprint variant of the filter), we should switch to `<Combobox>`.
  - Keyboard nav: `Enter` reads `activeListRef.current.itemAtIndex()` which closes over `useState` index. In tests, `userEvent.keyboard('{ArrowDown}{Enter}')` doesn't reliably let React flush the index update between keys. We worked around this in the integration test with `userEvent.hover` to set the index via `mouseenter`. In production this is a non-issue because real arrow-down events let React flush before the next key press; only userEvent's synthetic key sequences race the renderer.
  - **No plural `classNames` slots** anywhere in the headless API — only single `className` per primitive (consistent with Quill conventions and the user's recorded preference).

- **2026-04-27 (Phase 3 complete):** Full hook stack shipped, all green.
  - `hooks/useTaxonomicGroupsContext.ts` — kea bridge that calls `useValues` on `teamLogic`, `projectLogic`, `groupsModel`, `dataWarehouseSettingsSceneLogic`, `joinsLogic`, `propertyDefinitionsModel`, `featureFlagLogic`, calls `buildGroupAnalyticsTaxonomicGroups{,Names}` and assembles a memoised `BuildTaxonomicGroupsContext`. 4 tests.
  - `utils/buildGroupAnalyticsGroups.ts` — pure builders for the `${GroupsPrefix}_N` and `${GroupNamesPrefix}_N` dynamic groups.
  - `hooks/fetchTaxonomicListPage.ts` — pure fetcher composing search/page params, handling scoped+full Promise.all when `scopedEndpoint && !isExpanded`. Used by `useGroupList` via `useTaxonomicResource`'s queryFn.
  - `hooks/useGroupList.ts` — per-tab list hook (replaces `infiniteListLogic` for v1 scope). Owns `index`, `isExpanded`, `items` (local Fuse + remote + keyword shortcuts), `rowCount`, loading/empty derivations, `moveUp/moveDown`, `expand`. Skips for v1: DataWarehouse pinned-row, perf instrumentation, GroupNamesPrefix clickhouse fast path. Uses `useTaxonomicResource` for remote data with `staleTime: 60_000`, `keepPreviousData: true`. 18 tests.
  - `hooks/useTaxonomicFilter.ts` — orchestrator. Owns search query (controlled or uncontrolled), active group type, `groups[]` resolved + ordered against `taxonomicGroupTypes` prop. Provides `tabLeft/tabRight`, `selectItem`, `selectSelected`, `setSearchQuery`, plus `rootProps`/`inputProps` bags ready to spread on a `<div>` and `<input>`. Per-tab list components register their `useGroupList` api via `registerActiveList(api)` so the orchestrator's keyboard handler can forward Enter/ArrowUp/ArrowDown into the active list. 15 tests.
  - **Full TaxonomicFilter suite green: 280/280 across 13 suites.**

  Architecture decision banked:
  - **Hooks-must-be-called-in-same-order forces the per-tab pattern.** Calling `useGroupList` in a loop over `taxonomicGroupTypes` would violate React's hook rules whenever the array length shifts (e.g. shortcut group promotion). Resolution: each tab pill / tab list area is its own component that calls `useGroupList(getGroupListInput(group))` for itself, and registers its api back to the orchestrator via a ref-callback. Mirrors today's kea `BindLogic`-per-tab pattern.

- **2026-04-27 (Phase 3 prep):** Built `useTaxonomicResource(key, fn, opts)` micro-cache hook in `hooks/useTaxonomicResource.ts` shaped after react-query's `useQuery` so the future swap is a one-line import change. Behaviours: dedup of in-flight identical requests, `staleTime` cache, `keepPreviousData` on key change, `AbortController` propagation, errors halt auto-fetch (refetch() retries), abort-on-last-unsubscribe. Implementation uses `useSyncExternalStore` over a module-scoped `Map<hash, entry>` cache plus a per-instance `lastFiredHashRef` to prevent re-fire loops under `staleTime: 0`. 15 parameterised tests in `useTaxonomicResource.test.ts` cover: basic fetch, cache hit, stale refetch, `enabled=false`, `keepPreviousData` true/false, dedup, error handling, manual `refetch()`, abort on unsubscribe, signal freshness, JSON-stable cache keys, `invalidateTaxonomicResource()`, `peekTaxonomicResource()`, fn-identity stability. **15/15 passing**, full TaxonomicFilter suite **243/243 across 10 suites** with the new hook included.

  Two implementation lessons banked for the rest of Phase 3:
  - **Don't mutate the cache during render under `useSyncExternalStore`.** First attempt kicked off `execute()` directly in render to get accurate `isLoading` on the very first frame. The mutation tripped React's snapshot-tearing detector → infinite render loop → OOM. Fix: kick off in `useEffect`, derive `isLoading` from a `willFetch` predicate that returns `true` when the effect _will_ fire next commit. Same UX, no tearing.
  - **`staleTime: 0` plus an effect re-firing on `entry.ts` changes loops forever.** The effect is correctly invalidated when ts changes after a resolve, but with `staleTime: 0` it immediately re-considers itself stale and re-fires. Guard with a per-instance `lastFiredHashRef` so each (hook instance, hash) only auto-fires once. `refetch()` and `invalidateTaxonomicResource()` reset this implicitly by going through `execute()` directly or by clearing `entry.ts` plus `entry.error`.

- **2026-04-27 (Phase 2):** Extracted the ~900-line `taxonomicGroups` selector body into a pure `buildTaxonomicGroups(ctx)` function in `utils/buildTaxonomicGroups.tsx`. Moved `eventTaxonomicGroupProps`, `propertyTaxonomicGroupProps`, `defaultDataWarehousePopoverFields`, `COHORTS_WITH_ALL_USERS_OPTIONS`, and `TRAFFIC_TYPE_VIRTUAL_PROPERTIES` along with it. The selector in `taxonomicFilterLogic.tsx` is now a thin wrapper that destructures inputs and forwards them as a context object. Cleaned 30+ now-unused imports. Result: `taxonomicFilterLogic.tsx` shrunk **1684 → 737 lines** (-56%). 228/228 tests still green. Public API preserved via re-exports.
- **2026-04-27 (Phase 1):** Extracted `redistributeTopMatches` + constants → `utils/redistributeTopMatches.ts`; `promoteMatchingProperties` + `PROMOTED_PROPERTIES_BY_SEARCH_TERM` → `utils/promoteProperties.ts`; `keywordShortcutValue` + `withKeywordShortcuts` → `utils/keywordShortcuts.tsx`. All re-exported from original locations. 228/228 tests green. Added `FEATURE_FLAGS.TAXONOMIC_FILTER_HEADLESS = 'taxonomic-filter-headless'`. Decision: defer `@tanstack/react-query` (not in repo); model the internal `useTaxonomicResource` after react-query's API so we can swap later.

---

## 0. TL;DR

- `TaxonomicFilter` today = 1 React entry component + 3 kea logics (`taxonomicFilterLogic` ~1.6k LOC, `infiniteListLogic` ~990 LOC, `recentTaxonomicFiltersLogic` + `taxonomicFilterPinnedPropertiesLogic`) + 5 sub-components (search input, results, infinite list, row, empty state).
- It is the universal selection surface for Events / Actions / Properties / Cohorts / HogQL / Data Warehouse / etc. — 30+ group types, ~100 consumer sites.
- The kea coupling (parent logic + N child list logics keyed by `taxonomicFilterLogicKey`) is the main refactor obstacle. Children read from parent through `connect`, parent dispatches actions into children built lazily by a selector. Replacing this with a hook means re-creating the parent/child dispatch graph as a single `useTaxonomicFilter` returning slot state objects.
- Design target: hook that owns search/tab/index state + per-group result fetching (via react-query-style cache), exposes a normalized `groups[]` and `activeList` API, plus imperative `move`/`select`/`setTab` actions. View layer composes Combobox + Tabs + ScrollArea (+ react-window for the list).
- Compatibility shim: keep current `TaxonomicFilter` as a thin wrapper over the new component until callsites migrate.

---

## 1. Scope

In scope:

- Re-implement TaxonomicFilter on base-ui/quill primitives.
- Introduce `useTaxonomicFilter` hook owning all state.
- Provide a headless component (`<TaxonomicFilter.Root>` etc.) plus a default skin.
- Maintain feature parity (recents, pinned, suggested filters, top match redistribution, keyword shortcuts, data warehouse field defaults, scoped/expanded endpoints, virtualization, keyboard nav, async debouncing, definition popover).

Out of scope (initial cut):

- Touching the actual underlying APIs (`event_definitions`, `property_definitions`, `groups`, etc.).
- Changing wrapper components' public APIs (`TaxonomicPopover`, `PropertyFilters`, `BreakdownFilter`, `UniversalFilters`). They become consumers of the new hook.
- Removing kea logics on day one — they stay until consumer migration completes.

---

## 2. Today's architecture

### 2.1 Component tree

```text
TaxonomicFilter                       # entry, BindLogic + searchInputRef + style/width
├── TaxonomicFilterSearchInput        # kbd handler (↑/↓/Tab/Enter/Esc), LemonInput + suffix
└── InfiniteSelectResults             # category column + per-tab list container
    ├── CategoryPill (×N)             # one per visible group type, BindLogic each
    └── InfiniteList (active tab)
        └── react-window rows
            ├── InfiniteListRow       # real items
            ├── SkeletonRow           # while loading suggested filters
            ├── ExpandRow             # scoped→full toggle
            └── NonCapturedEventRow   # `allowNonCapturedEvents`
```

Empty states routed via `TaxonomicFilterEmptyState`. Definition popover routed via `DefinitionPopoverContents` reaching back into `taxonomicFilterLogic` for `selectedItemMeta` and `dataWarehousePopoverFields`.

### 2.2 Logic graph

```text
taxonomicFilterLogic[key]              # parent: tabs, search, top matches, group config
  ├── infiniteListLogic[key, Events]
  ├── infiniteListLogic[key, Actions]
  ├── infiniteListLogic[key, EventProperties]
  ├── ... one per active group type
  │
  ├── connect: teamLogic, projectLogic, groupsModel,
  │            dataWarehouseSettingsSceneLogic, joinsLogic,
  │            propertyDefinitionsModel, featureFlagLogic
  │
  └── side-dispatch (via isMounted): recentTaxonomicFiltersLogic
                                     taxonomicFilterPinnedPropertiesLogic
                                     eventUsageLogic
                                     propertyDefinitionsModel.updatePropertyDefinitions
```

`infiniteListLogic` itself connects back to `taxonomicFilterLogic` for `taxonomicGroups`, `searchQuery`, `activeTab`, `value`, `topMatchItemsWithSkeletons`, `anyGroupLoading` plus `recentFilterItems` / `pinnedFilterItems`. Two-way coupling.

### 2.3 Data flow (canonical search path)

```text
keystroke
  └─► LemonInput.onChange
       └─► taxonomicFilterLogic.setSearchQuery(q)        [reducer]
            ├─► resets topMatchItems = []
            ├─► child infiniteListLogic[*].setSearchQuery (via parent value subscription)
            │     ├─► loadRemoteItems({offset:0, limit:100})  [breakpoint(500)]
            │     │     └─► fetch endpoint or scopedEndpoint+endpoint pair
            │     │          └─► loadRemoteItemsSuccess(remoteItems)
            │     │               └─► parent.infiniteListResultsReceived(groupType, results)
            │     │                    ├─► appendTopMatches(matches)  [reducer: dedup-by-group]
            │     │                    └─► if EventProps/PersonProps/Numerical → updatePropertyDefinitions
            │     └─► local groups push localItems via parent.infiniteListResultsReceived
            └─► [debounce 500ms] capture 'taxonomic_filter_search_query'
```

Selectors then derive:

- `redistributedTopMatchItems = redistributeTopMatches(topMatchItems, activeGroupCount, taxonomicGroupTypes)`
- `topMatchItemsWithSkeletons` — only used when search query present, inserts `SKELETON_ROWS_PER_GROUP=3` per loading group
- `infiniteListCounts` (Record<group, totalListCount>) drives tab badge counts and tab visibility for `tabLeft/tabRight`

### 2.4 Selection path

```text
Enter / click
  └─► taxonomicFilterLogic.selectSelected (or selectItem)
       ├─► infiniteListLogic.selectSelected → resolves selected item by index
       ├─► capture event if QuickFilterItem
       ├─► setTimeout(0) recentTaxonomicFiltersLogic.recordRecentFilter (skip property groups)
       ├─► props.onChange(group, value, item)   ← TaxonomicFilter contract
       │   (or props.onEnter(query) if no item)
       └─► setSearchQuery('')
```

---

## 3. Inventory (full)

### 3.1 Entry component props (`TaxonomicFilterProps`)

| Prop                                                              | Type                                     | What it controls                                                                                                                                                         |
| ----------------------------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `taxonomicGroupTypes`                                             | `TaxonomicFilterGroupType[]`             | Which tabs appear, in what order. Filtered/reordered by `taxonomicGroupTypes` selector (mutually exclusive shortcut pairs, meta promotion, recent/pinned auto-injection) |
| `taxonomicFilterLogicKey`                                         | `string`                                 | Kea instance key. Auto-generated if absent                                                                                                                               |
| `groupType`                                                       | `TaxonomicFilterGroupType`               | Initial active tab (overrides default-to-first-non-meta)                                                                                                                 |
| `value`                                                           | `string\|number\|null`                   | Currently selected value (for highlight + DW row pin)                                                                                                                    |
| `onChange`                                                        | `(group, value, item) => void`           | Selection callback                                                                                                                                                       |
| `onEnter`                                                         | `(query) => void`                        | Fallback when Enter pressed with no selection                                                                                                                            |
| `onClose`                                                         | `() => void`                             | Esc handler                                                                                                                                                              |
| `filter`                                                          | `LocalFilter`                            | Pass-through metadata (consumed via `selectedItemMeta`)                                                                                                                  |
| `optionsFromProp`                                                 | `Partial<Record<group, SimpleOption[]>>` | Static items per group (Metadata, Wildcards)                                                                                                                             |
| `eventNames`                                                      | `string[]`                               | Constrains property/flag endpoints. Drives autocapture-element promotion                                                                                                 |
| `schemaColumns` / `schemaColumnsLoading`                          | DW columns                               | Populates DW group                                                                                                                                                       |
| `endpointFilters`                                                 | `Record<string, any>`                    | Extra URL params (logs/spans)                                                                                                                                            |
| `height` / `width`                                                | size                                     | Layout sizing                                                                                                                                                            |
| `popoverEnabled`                                                  | bool                                     | Definition popover on hover                                                                                                                                              |
| `selectFirstItem` / `autoSelectItem`                              | bool                                     | Initial index behavior                                                                                                                                                   |
| `excludedProperties` / `selectedProperties` / `propertyAllowList` | `TaxonomicFilterGroupValueMap`           | Per-group filtering / selection state                                                                                                                                    |
| `metadataSource`                                                  | `AnyDataNode`                            | HogQL editor context                                                                                                                                                     |
| `hideBehavioralCohorts`                                           | bool                                     | Hides behavioural cohorts + footer link                                                                                                                                  |
| `showNumericalPropsOnly`                                          | bool                                     | Shows only numeric properties                                                                                                                                            |
| `dataWarehousePopoverFields`                                      | `DataWarehousePopoverField[]`            | DW popover field schema (default: id/timestamp/distinct_id)                                                                                                              |
| `maxContextOptions`                                               | `MaxContextTaxonomicFilterOption[]`      | Max AI "On this page" items                                                                                                                                              |
| `useVerticalLayout`                                               | bool                                     | Force columnar layout (default: auto when >`VERTICAL_LAYOUT_THRESHOLD`=4 groups)                                                                                         |
| `initialSearchQuery`                                              | string                                   | Seed input                                                                                                                                                               |
| `allowNonCapturedEvents`                                          | bool                                     | Show "use 'foo' as event name" row                                                                                                                                       |
| `hogQLGlobals` / `hogQLExpressionShowBreakdownLabelHint`          | HQL editor config                        |                                                                                                                                                                          |
| `definitionPopoverRenderer`                                       | fn                                       | Override popover contents                                                                                                                                                |
| `minSearchQueryLength`                                            | number                                   | Override per-group min                                                                                                                                                   |
| `suggestedFiltersLabel`                                           | string                                   | Override "Suggested filters" tab label                                                                                                                                   |
| `hideSearchInput`                                                 | bool                                     | Hide built-in input (external input drives)                                                                                                                              |
| `searchQuery`                                                     | string                                   | Controlled search query (synced into logic)                                                                                                                              |
| `enableKeywordShortcuts`                                          | bool                                     | Surface `$event_type` shortcuts as `QuickFilterItem`s                                                                                                                    |

### 3.2 Group config (`TaxonomicFilterGroup`)

Per-group config built by parent logic. Fields:

| Field                                                     | Used for                                                                             |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `name`, `searchPlaceholder`, `categoryLabel(count)`       | UI labels                                                                            |
| `type`: `TaxonomicFilterGroupType`                        | Identity                                                                             |
| `endpoint` / `scopedEndpoint`                             | Server fetch URL (scoped used until "expand results")                                |
| `expandLabel({count, expandedCount})`                     | Expand button                                                                        |
| `options[]`                                               | Static items (Metadata, Wildcards, etc.)                                             |
| `logic` + `value` + `valueLoading`                        | Read items + loading from another kea logic (Actions, Cohorts, Replay)               |
| `localItemsSearch(items, q)`                              | Override Fuse search (Replay)                                                        |
| `isLocalOnly`                                             | Skip server fetch + skeletons + top-match aggregation                                |
| `isMetaGroup`                                             | Excluded from loading state, top matches, auto-tab-away, definition popover          |
| `getName/getValue/getPopoverHeader/getIcon/getIsDisabled` | Item adapters                                                                        |
| `excludedProperties`, `propertyAllowList`                 | Per-group filtering                                                                  |
| `keywordShortcuts(q) -> QuickFilterItem[]`                | `$event_type` shortcuts for autocapture                                              |
| `minSearchQueryLength`, `searchDescription`               | Gate server search until enough chars typed                                          |
| `searchAlias`                                             | Alternate query param name (e.g. `value` for shortcut groups)                        |
| `valuesEndpoint(key)`                                     | Fetch enum values for a property                                                     |
| `getFullDetailUrl(item)`                                  | Definition popover deep link                                                         |
| `componentProps`                                          | Forwarded to `render` component                                                      |
| `render(TaxonomicFilterRenderProps)`                      | Custom replacement for InfiniteList (HogQL editor, ReplaySavedFilters, HogFlow vars) |
| `footerMessage`                                           | Static row at bottom of list                                                         |
| `groupTypeIndex`                                          | Used by dynamic group / group-name groups (`GroupsPrefix_N`, `GroupNamesPrefix_N`)   |

### 3.3 Per-tab list state (`infiniteListLogic`)

Reducers:

- `index` — keyboard highlight (`NO_ITEM_SELECTED` | int)
- `pinnedRowIndex` + `hasAppliedInitialPin` — DW detail-pane pin
- `showPopover` — static prop mirror
- `limit` (default 100), `startIndex`, `stopIndex` — virtualization window
- `isExpanded` — scoped→full results toggle
- `hasMore` — pagination flag (groups endpoint)
- `remoteItems` (loader) — `{ results, searchQuery, count, expandedCount, queryChanged, first }`

Listeners worth preserving exactly:

- `loadRemoteItems` debounce (`breakpoint(500)`), first-call fast path (`breakpoint(1)`), AbortController prepared per call
- Scoped+expanded parallel fetch (Promise.all)
- Global API cache (60 s TTL via `window.setTimeout`) — replaceable with react-query's `staleTime`
- `onRowsRendered` virtualizer callback → fetch missing pages from cursor
- `setActiveTab` resets `pinnedRowIndex` if tab changed
- `setSearchQuery` resets pinned + triggers remote load (or local push)
- `selectSelected` → handles Expand row, calls `getIsDisabled` gate, emits `parent.selectItem`
- `loadRemoteItemsSuccess` → `parent.infiniteListResultsReceived`
- `expand` → `loadRemoteItems({ offset: index, limit })`
- `afterMount` → kicks initial fetch (or sets index to current value match)

Selectors that drive UI:

- `items` (composite ListStorage): keyword shortcuts → recentPrefix → pinnedPrefix → suggestedPinnedMatches → localItems → remoteItems → topMatches (for SuggestedFilters), with `promoteMatchingProperties` applied when query present
- `rowCount` — special cases: 1 if showing non-captured row; 7 skeleton rows on first load; otherwise `max(results.length, totalListCount)` + suggested empty state row
- `showEmptyState`, `showLoadingState`, `showSuggestedFiltersEmptyState`, `needsMoreSearchCharacters`
- `isLocalDataLoading` reads `group.valueLoading` from arbitrary logic + `schemaColumnsLoading` for DW props
- `topMatchesForQuery` — sliced to `MAX_TOP_MATCHES_PER_GROUP=10`, promoted, prepended with keyword shortcuts

### 3.4 Pure helpers (already pure — keep)

- `redistributeTopMatches(items, activeGroupCount, groupTypeOrder)` — slot allocation across groups; `DEFAULT_SLOTS_PER_GROUP=5`, `MAX_TOP_MATCHES_PER_GROUP=10`, surplus slots prefer `REDISTRIBUTION_PRIORITY_GROUPS = [CustomEvents, PageviewUrls, Screens]` when fewer than 3 groups present
- `promoteMatchingProperties(items, query)` — moves `PROMOTED_PROPERTIES_BY_SEARCH_TERM[q]` to top; today: `{url:['$current_url'], email:['$email']}`
- `keywordShortcutValue(item)` — `JSON.stringify({q,v,e})` synthetic key (never parsed)
- `withKeywordShortcuts(base, {popoverHeader, buildShortcuts})` — wraps group getters to handle `T | QuickFilterItem` union
- `buildAutocaptureSeriesShortcuts(q)` / `buildEventTypeFilterShortcuts(q)` (eventTypeShortcuts.ts) — match against `eventTypeToVerb` map, suppress when >`MAX_SHORTCUT_MATCHES=3`
- `getDataWarehouseItemWithFieldDefaults(item, meta)` — id/timestamp/distinct_id auto-detection (case-insensitive name candidates + datetime sniff)

### 3.5 Persistence

| Storage key                                                                  | Owner                                | Shape                     | Cap  | Eviction                                                               |
| ---------------------------------------------------------------------------- | ------------------------------------ | ------------------------- | ---- | ---------------------------------------------------------------------- |
| `${teamId}__recentFilters`                                                   | recentTaxonomicFiltersLogic          | `RecentTaxonomicFilter[]` | 20   | Drop expired (>30d) on insert; dedup by groupType+value+propertyFilter |
| `${teamId}__pinnedFilters`                                                   | taxonomicFilterPinnedPropertiesLogic | `PinnedTaxonomicFilter[]` | none | Manual togglePin only                                                  |
| `taxonomicFilterPinnedProperties__migrated__${teamId}`                       | migration flag                       | string                    | —    | once                                                                   |
| `scenes.session-recordings.player.playerSettingsLogic.quickFilterProperties` | legacy → migrated to pinned          | `string[]`                | —    | deleted post-migration                                                 |

Both global; both inject `_recentContext` / `_pinnedContext` markers onto items so consumers can re-hydrate filter state.

### 3.6 External coupling

- `propertyDefinitionsModel.updatePropertyDefinitions(defs)` — populates app-wide cache so other surfaces see freshly-loaded definitions
- `eventUsageLogic.reportTaxonomicFilterCategorySelected(group, eventName)` and `capture('taxonomic_filter_search_query'|'taxonomic suggested filter selected')`
- `captureTimeToSeeData(metric)` — perf instrumentation per remote load
- `groupsModel`, `joinsLogic`, `featureFlagLogic`, `dataWarehouseSettingsSceneLogic` — read-only deps for group config

---

## 4. Consumer surface

~100 callsites grouped by usage shape (see appendix A for full table).

| Pattern               | Examples                                                                                | Contract relied on                                                                                                                      |
| --------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Direct popover usage  | TaxonomicPopover/TaxonomicStringPopover                                                 | `(value, groupType, item)` callback (note inverted args)                                                                                |
| Property filter row   | PropertyFilters → TaxonomicPropertyFilter                                               | `selectItem(group, value, item.propertyFilterType, item)`, parses `_recentContext.propertyFilter`                                       |
| Breakdown picker      | TaxonomicBreakdownPopover                                                               | Up to 3 multi-select; uses `selectedProperties` + `excludedProperties`                                                                  |
| Universal filters     | UniversalFilters AddFilterButton (3 sites)                                              | Handles `isQuickFilterItem`                                                                                                             |
| Insight series picker | ActionFilterRow + entityFilterLogic                                                     | `enableKeywordShortcuts=true`, branches on `isQuickFilterItem`                                                                          |
| Standalone selectors  | EventSelect, PropertySelect, FlagSelector, AddEventButton                               | Various small subsets                                                                                                                   |
| Logic-only consumers  | DefinitionPopover, FunnelDataWarehouseStepDefinitionPopover, SavedFiltersTaxonomicGroup | `useValues(taxonomicFilterLogic)` for `taxonomicGroups`, `selectedItemMeta`, `dataWarehousePopoverFields`; `useActions(...).selectItem` |

Recurring `taxonomicGroupTypes` presets we should expose as named constants:

- `EVENT_PICKER = [Events, Actions]`
- `PROPERTY_PICKER = [EventProperties, PersonProperties]`
- `BREAKDOWN_PICKER = [EventProperties, PersonProperties, Cohorts, EventFeatureFlags, EventMetadata, SessionProperties, HogQLExpression, ...DW variants]`
- `COHORT_CRITERIA_PICKER = [Events, Actions]`
- `MAX_CONTEXT_PICKER = [Events, Actions, EventProperties, PersonProperties, MaxAIContext]`

---

## 5. Quill / base-ui inventory available

(Full memo from quill-survey agent above.)

Reusable as-is for the rewrite:

- `Combobox` (Root/Input/List/Group/Collection/Item/Portal/Positioner/Popup/Chips/ChipRemove/Trigger/Value)
- `Tabs` (Root/List/Tab/Panel/Indicator) — for category column
- `Popover` — for definition popover
- `Field` — wrap input with label/description
- `ScrollArea`, `Empty`, `Item` (list row), `MenuLabel`, `MenuEmpty`
- `Button`, `Input`, `Chip`, `Badge`, `Spinner`, `Tooltip`, `Separator`

To add (not in quill yet):

- Virtualized list helper. Pick `react-window` (already installed, used elsewhere) — wrap inside `Combobox.Popup` so `aria-activedescendant` still works.

Hard rules (memory-derived):

- **No plural `classNames` slot prop.** Compose via sub-components + single `className` + CVA variants.
- Combobox `filter={null}` + `filteredItems={...}` to bypass internal filtering. Keep that pattern — we want to drive items entirely from the hook.
- `Combobox.Input` must live inside `Combobox.Chips` if multi-select with chips is needed.
- `inputInsidePopup` controlled by whether `Input` is inside `Positioner` — choose deliberately per popover/inline mode.

---

## 6. State decomposition for `useTaxonomicFilter`

Goal: a single hook that owns everything the kea logic owns today, exposed as small, well-named slices. Each slice maps to a distinct part of the UI.

### 6.1 Hook signature (sketch)

```ts
function useTaxonomicFilter(opts: UseTaxonomicFilterOptions): TaxonomicFilterApi
```

Where:

```ts
interface UseTaxonomicFilterOptions {
  // identity
  key?: string // for cache scoping; auto-generated

  // group selection
  taxonomicGroupTypes: TaxonomicFilterGroupType[]
  initialGroupType?: TaxonomicFilterGroupType

  // controlled value(s)
  value?: TaxonomicFilterValue
  onChange?: (group, value, item) => void
  onEnter?: (query: string) => void

  // controlled search
  searchQuery?: string
  initialSearchQuery?: string
  onSearchQueryChange?: (q: string) => void
  minSearchQueryLength?: number

  // data shaping
  optionsFromProp?: Partial<Record<TaxonomicFilterGroupType, SimpleOption[]>>
  eventNames?: string[]
  schemaColumns?: DatabaseSchemaField[]
  schemaColumnsLoading?: boolean
  endpointFilters?: Record<string, any>
  metadataSource?: AnyDataNode
  dataWarehousePopoverFields?: DataWarehousePopoverField[]
  maxContextOptions?: MaxContextTaxonomicFilterOption[]
  hogQLGlobals?: Record<string, any>

  // filtering / display gates
  excludedProperties?: ExcludedProperties
  selectedProperties?: SelectedProperties
  propertyAllowList?: AllowedProperties
  showNumericalPropsOnly?: boolean
  hideBehavioralCohorts?: boolean
  allowNonCapturedEvents?: boolean
  enableKeywordShortcuts?: boolean
  suggestedFiltersLabel?: string

  // misc
  selectFirstItem?: boolean
  autoSelectItem?: boolean
}
```

Returned API:

```ts
interface TaxonomicFilterApi {
    // search
    searchQuery: string
    setSearchQuery(q: string): void
    searchPlaceholder: string

    // tabs
    groups: TaxonomicFilterGroup[]              // already filtered/reordered
    activeGroup: TaxonomicFilterGroup
    activeGroupType: TaxonomicFilterGroupType
    setActiveGroupType(g: TaxonomicFilterGroupType): void
    counts: Record<TaxonomicFilterGroupType, number>
    loadingGroupTypes: TaxonomicFilterGroupType[]
    tabLeft(): void
    tabRight(): void

    // active list (delegates to per-group sub-state)
    list: {
        items: TaxonomicDefinitionTypes[]
        rowCount: number
        index: number
        setIndex(i: number): void
        moveUp(): void
        moveDown(): void
        selectAtIndex(i?: number): void
        isLoading: boolean
        hasMore: boolean
        showEmptyState: boolean
        showLoadingState: boolean
        showSuggestedFiltersEmptyState: boolean
        needsMoreSearchCharacters: boolean
        isExpandable: boolean
        expand(): void
        onRowsRendered(window: { startIndex: number; stopIndex: number; overscanStopIndex?: number }): void
        // pin (DW detail)
        pinnedRowIndex: number | null
        togglePinnedRow(rowIndex: number): void
    }

    // imperative selection from outside
    selectItem(group, value, item): void
    selectSelected(): void

    // for definition popover & legacy consumers
    selectedItem: TaxonomicDefinitionTypes | undefined
    selectedItemValue: TaxonomicFilterValue | undefined
    selectedItemMeta: LocalFilter | undefined

    // bag for headless components to spread
    rootProps: { onKeyDown, ... }
    inputProps: { value, onChange, onKeyDown, ... }
}
```

### 6.2 Internal layering inside the hook

Three concentric layers, all hook-local (no kea):

1. **`useTaxonomicGroups(opts)`** — pure derivation. Builds the `groups[]` array from the same inputs the parent kea selector uses today (`teamLogic.currentTeam`, `groupsModel.groupTypes`, `propertyDefinitionsModel.eventMetadataPropertyDefinitions`, `featureFlagLogic.featureFlags`, etc.). For now we keep reading those via existing kea `useValues` shims; later we can replace each with a smaller dedicated hook. Returns `{ groups, taxonomicGroupTypes, metaGroupTypes }`.
2. **`useGroupList(group, sharedCtx)`** — one instance per active group, owned by a `Map<groupType, groupListState>` inside `useTaxonomicFilter`. Owns `remoteItems`, `index`, `pinnedRowIndex`, `isExpanded`, plus selectors for `items`, `rowCount`, `topMatchesForQuery`, etc. Async loads delegated to a shared fetch util (see §6.4).
3. **`useTaxonomicFilter(opts)`** — orchestrates the two above, owns `searchQuery` + `activeGroupType` + `topMatchItems`, and dispatches "search changed → re-fetch each group list" via effects. Computes `redistributedTopMatchItems` + `topMatchItemsWithSkeletons` as memoized values.

Why three layers and not one giant hook: the per-group state container is heavy enough (loader + virtualization cursor + index + pin) that it deserves isolation. Mirrors the kea split today and lets us swap the data source per group cleanly (e.g. data warehouse uses `useDataWarehouseTables`, properties use `usePropertyDefinitions`, etc.) without growing one mega-hook.

### 6.3 Cross-coupling resolution

Today's parent ↔ child cross-reads we need to recreate without kea connect:

| Today                                                                                                   | Hook equivalent                                                                                              |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `infiniteListLogic` reads `taxonomicFilterLogic.searchQuery`                                            | hook passes `searchQuery` into each `useGroupList(...)` call                                                 |
| `infiniteListLogic` reads `taxonomicFilterLogic.value`                                                  | same                                                                                                         |
| `infiniteListLogic` reads `taxonomicFilterLogic.topMatchItemsWithSkeletons`                             | only the SuggestedFilters list needs it; pass via `sharedCtx`                                                |
| `infiniteListLogic` reads `taxonomicFilterLogic.anyGroupLoading`                                        | derive in parent hook by reducing list-state map                                                             |
| `taxonomicFilterLogic.appendTopMatches` from child loader success                                       | each `useGroupList` exposes a `topMatchesForQuery` value; parent hook subscribes via effect, dedups by group |
| `taxonomicFilterLogic.infiniteListResultsReceived` → propertyDefinitionsModel.updatePropertyDefinitions | dedicated effect inside `useGroupList` for property groups                                                   |

### 6.4 Async fetching

**Decision (2026-04-27):** `@tanstack/react-query` is **not** present in the repo (`pnpm ls` confirms; only `query-selector-shadow-dom` matches the keyword). Adding it is a separate conversation (bundle weight + new pattern across the codebase). To keep migration moving, ship Phase 3 with an in-house micro-cache hook that **mirrors react-query's API surface** so we can swap later without touching call-sites:

```ts
function useTaxonomicResource<T>(
  key: ReadonlyArray<unknown>,
  fn: ({ signal }: { signal: AbortSignal }) => Promise<T>,
  opts?: {
    enabled?: boolean
    staleTime?: number // default 60_000 (mirrors today)
    keepPreviousData?: boolean // default true (mirrors today)
  }
): { data: T | undefined; isLoading: boolean; isFetching: boolean; refetch: () => void }
```

Backed by a module-scoped `Map<keyHash, { data, ts, inflight, subscribers }>` with deterministic key serialisation (`JSON.stringify` on a stable shape). Aborts via `AbortController` plumbed into `fn`. Subscribers notified on data change so consumers re-render.

Why mirror react-query exactly:

- Hot-swap path: when we adopt TanStack later, the only change is the import.
- Forces us to design for cache identity, not for kea-style action chaining.

Implementation notes (same as before):

- `staleTime: 60_000` mirrors today's cache.
- `keepPreviousData: true` while typing — matches "preserve old results until new arrive" behaviour.
- Custom `fn` handles the scoped+full `Promise.all` when `scopedEndpoint && !isExpanded`.
- Local-only groups (`isLocalOnly`) skip the resource hook entirely and derive `items` from local sources (Fuse over `rawLocalItems`).
- Cursor-based fetch on `onRowsRendered` → `fetchNextPage` analog (own `useTaxonomicInfiniteResource` later if needed; for first cut, do offset/limit through plain refetch since today's logic already does that).

### 6.5 Side-effect surfaces

Carve these out as dedicated hooks called from `useTaxonomicFilter`:

- `useRecordRecentFilter()` — wraps `recentTaxonomicFiltersLogic.recordRecentFilter` (kept for now; thin React-side wrapper around the existing localStorage logic). Keeps the dedup/expiry rules intact.
- `useTaxonomicAnalytics(key, opts)` — wraps `eventUsageLogic.reportTaxonomicFilterCategorySelected` + `posthog.capture('taxonomic_filter_search_query'|'taxonomic suggested filter selected')`.
- `useUpdatePropertyDefinitionsCache()` — wraps `propertyDefinitionsModel.updatePropertyDefinitions`.
- `useCaptureTimeToSeeData()` — wraps existing util.

Each is a small bridge, not a rewrite. They get deleted if/when those underlying kea logics are migrated themselves.

### 6.6 Keyboard handling

Hook returns a single `rootProps.onKeyDown` builder so the headless component can attach to its container (or to the input via `inputProps.onKeyDown`):

- `ArrowUp/Down` → `list.moveUp/moveDown` (and disable mouse hover for 100 ms — port the `mouseInteractionsEnabled` flag)
- `Tab/Shift+Tab` → `tabRight/tabLeft` (skip empty groups; default behavior: only when the category dropdown is in `control` variant — match current toggle)
- `Enter` → `list.selectAtIndex()` (or fallback `onEnter(query)` if no selection)
- `Escape` → `setSearchQuery('')` + `onClose?.()`

Mouse-interaction lockout matches the existing trick: any keyboard nav disables hover-driven `setIndex` for 100 ms so the cursor doesn't yank focus back to whatever the mouse was over.

---

## 7. Headless component layer

Compound component on top of the hook. Two variants ship in the same package:

```tsx
<TaxonomicFilter.Root {...hookOpts}>
  <TaxonomicFilter.Input placeholder="Search..." />
  <TaxonomicFilter.Layout>
    <TaxonomicFilter.Categories /> {/* default: vertical pills, switch via prop */}
    <TaxonomicFilter.Results>
      <TaxonomicFilter.Title /> {/* hides when single tab */}
      <TaxonomicFilter.List /> {/* virtualized via react-window */}
      <TaxonomicFilter.EmptyState />
      <TaxonomicFilter.Footer /> {/* optional, group.footerMessage */}
    </TaxonomicFilter.Results>
  </TaxonomicFilter.Layout>
  <TaxonomicFilter.DefinitionPopover /> {/* optional */}
</TaxonomicFilter.Root>
```

Notes:

- `Root` calls the hook and provides context; everything else reads via `useTaxonomicFilterContext()`.
- Headless = no styles inside the primitives. A sibling `<TaxonomicFilterDefault />` ships our current visual.
- `TaxonomicFilter.List` accepts `renderRow={(item, state) => ...}` for full row override; default renderer mimics today's `InfiniteListRow`.
- `TaxonomicFilter.Categories` accepts `variant: 'pill' | 'icon' | 'control'` so the existing `TAXONOMIC_FILTER_CATEGORY_DROPDOWN` flag still has somewhere to live.
- For consumers that pass `render` on a group config (HogQL editor, ReplaySavedFilters, HogFlow vars), the `List` renderer detects `activeGroup.render` and substitutes the custom component, just like today.

### 7.1 Keep current `TaxonomicFilter` as wrapper

```tsx
export function TaxonomicFilter(props: TaxonomicFilterProps) {
    return (
        <TaxonomicFilterRoot {...mapPropsToHook(props)}>
            {!props.hideSearchInput && <TaxonomicFilter.Input ... />}
            <TaxonomicFilter.Layout>
                <TaxonomicFilter.Categories variant={resolveCategoryVariant(...)} />
                <TaxonomicFilter.Results>...</TaxonomicFilter.Results>
            </TaxonomicFilter.Layout>
        </TaxonomicFilterRoot>
    )
}
```

This is the migration shim. Existing callsites work unchanged. Once everyone is migrated to the headless API, kill this file and the kea logics.

---

## 8. Migration plan (incremental)

Each phase shippable in its own PR; no consumer break across phases.

**Phase 0 — instrumentation & tests** (1 PR)

- Lock current behavior with RTL + logic tests at the 8 known sensitive points (group ordering, redistribution, recents, pinned, keyword shortcuts, scoped expand, empty states, keyboard nav).
- Add stories for any uncovered consumer shape (esp. `hideSearchInput=true`, `enableKeywordShortcuts`, autocapture-element promotion).
- Snapshot of TaxonomicFilter.stories.tsx as visual regression.

**Phase 1 — extract pure helpers** ✅ **DONE 2026-04-27**

- ✅ `redistributeTopMatches` + `DEFAULT_SLOTS_PER_GROUP` + `MAX_TOP_MATCHES_PER_GROUP` + `REDISTRIBUTION_PRIORITY_GROUPS` + `SKELETON_ROWS_PER_GROUP` + `TopMatchItem` → `utils/redistributeTopMatches.ts`
- ✅ `promoteMatchingProperties` + `PROMOTED_PROPERTIES_BY_SEARCH_TERM` → `utils/promoteProperties.ts`
- ✅ `keywordShortcutValue` + `withKeywordShortcuts` + `BaseGroupFns` → `utils/keywordShortcuts.tsx`
- ✅ Re-exports from `taxonomicFilterLogic.tsx` keep the existing public API (`DEFAULT_SLOTS_PER_GROUP`, `MAX_TOP_MATCHES_PER_GROUP`, `REDISTRIBUTION_PRIORITY_GROUPS`, `SKELETON_ROWS_PER_GROUP`, `TopMatchItem`, `redistributeTopMatches`).
- ✅ Existing parameterised tests for `redistributeTopMatches` (in `taxonomicFilterLogic.test.ts`) still green via re-export — no test changes required.
- ✅ `dataWarehouseItemUtils.ts` and `eventTypeShortcuts.ts` already standalone with own test files; left in place.
- ✅ Test suite: 228/228 pass (`hogli test frontend/src/lib/components/TaxonomicFilter/`).

**Phase 2 — group config builder** ✅ **DONE 2026-04-27**

- ✅ `buildTaxonomicGroups(ctx)` lives in `utils/buildTaxonomicGroups.tsx`. `BuildTaxonomicGroupsContext` is the explicit input contract (16 fields, mirroring the kea selector's deps).
- ✅ `taxonomicFilterLogic.tsx`'s `taxonomicGroups` selector is now a one-liner that forwards into the builder.
- ✅ Hook (Phase 3) will call the same `buildTaxonomicGroups` with values pulled from a `useTaxonomicGroupsContext()` bridge of equivalent kea-`useValues` calls.
- ✅ Public exports preserved: `eventTaxonomicGroupProps`, `propertyTaxonomicGroupProps`, `defaultDataWarehousePopoverFields` re-exported from logic file.
- ✅ 228/228 tests pass.

**Phase 3 — `useTaxonomicFilter` hook (no UI change)** ✅ **DONE 2026-04-27**

- ✅ `hooks/useTaxonomicResource.ts` — react-query-shaped data fetcher (15 tests).
- ✅ `hooks/useTaxonomicGroupsContext.ts` — kea bridge → `BuildTaxonomicGroupsContext` (4 tests).
- ✅ `utils/buildGroupAnalyticsGroups.ts` + `hooks/fetchTaxonomicListPage.ts` — supporting pure helpers.
- ✅ `hooks/useGroupList.ts` — per-tab list state (18 tests).
- ✅ `hooks/useTaxonomicFilter.ts` — orchestrator + headless prop bags (15 tests).
- ✅ Full suite 280/280 across 13 suites.
- Deferred (intentionally out of v1 scope, documented inline):
  - DataWarehouse pinned-row detail-pane state
  - `captureTimeToSeeData` perf instrumentation
  - GroupNamesPrefix clickhouse fast path (still works, just slower)
  - Top-match aggregation across groups (handled by existing kea path until Phase 5 flip)
  - `propertyDefinitionsModel.updatePropertyDefinitions` cache priming side-effect
  - `localOverride` for `group.logic`-driven items (e.g. Actions, Cohorts, Experiments) — orchestrator passes `undefined` for now; Phase 5's per-tab component can wire these via dedicated `useValues` calls or a small `useGroupLogicValue(group)` bridge.

**Phase 4 — headless components on top of hook** ✅ **DONE 2026-04-27**

- ✅ `TaxonomicFilterHeadless.{Root,Input,Categories,Panel}` shipped under `headless/`.
- ✅ Built directly on Quill primitives (`Button`, `InputGroup`, `InputGroupInput`, `ItemMenuItem`, `Empty`/`EmptyHeader`/`EmptyTitle`, `Spinner`).
- ✅ 7 RTL integration tests + full suite at 299/299.
- Pending for Phase 5: storybook entries, default skin (compatibility wrapper for legacy callsites), feature-flag flip from old kea path to headless path.

**Phase 5 — flip the entry component** ✅ **DONE 2026-04-27**

- ✅ `TaxonomicFilter.tsx` reads `featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_HEADLESS]`. When on → `<TaxonomicFilterAdapter />` (headless path). When off → `<TaxonomicFilterLegacy />` (existing kea body, untouched).
- ✅ `TaxonomicFilterAdapter.tsx` maps the legacy `TaxonomicFilterProps` interface onto `<TaxonomicFilterHeadless.{Root,Input,Categories,Panel}>`. Forwards `onClose` via Escape interception at the adapter level (headless API doesn't ship a dedicated onClose option).
- ✅ Storybook entries under `headless/TaxonomicFilterHeadless.stories.tsx` for visual review.
- ✅ Full TaxonomicFilter suite still green (299/299, 14 suites) with both paths coexisting.
- Flag is **user-toggleable** via the PostHog flag UI so consumers can opt in/out if they hit a 1:1 mismatch.
- Rollout: 0% → dev → 1% → 10% → 100%, monitoring `eventUsageLogic` events.
- Keep both code paths behind the flag for at least one minor release before deleting the kea path.

**Phase 6 — parity validation** (1 PR)

- Add a parameterised RTL test that runs the existing `TaxonomicFilter` test suite under both flag values (`TAXONOMIC_FILTER_HEADLESS=on` and `=off`). Each behavioural assertion runs against both the legacy kea path and the headless adapter path, locking parity in CI.
- Address the v1 gaps documented in the Phase 4/5 changelog (`group.logic`-driven local items for Actions/Cohorts/Experiments, definitionPopoverRenderer, DataWarehouse pinned-row, top-match aggregation across SuggestedFilters tab) until the parity test passes for every existing story + RTL case.
- Storybook visual diff: snapshot every existing TaxonomicFilter story under both flag values, fail on visual diff above threshold.
- Exit criteria: dual-flag suite green, visual diffs ≤ threshold, no consumer-flagged regressions during a 1-2 week dogfood window.

**Phase 7 — consumer migration + delete kea logics** (N PRs over weeks)

- Migrate wrappers (`TaxonomicPopover`, `PropertyFilters`, `BreakdownFilter`, `UniversalFilters`) to consume the hook directly. Each becomes thinner.
- Migrate logic-only consumers (DefinitionPopover, FunnelDataWarehouseStepDefinitionPopover, SavedFiltersTaxonomicGroup) to read from a `TaxonomicFilterContext` or to receive the hook return as a prop.
- Once no callsite imports `taxonomicFilterLogic`/`infiniteListLogic`, delete them.
- Keep `recentTaxonomicFiltersLogic` and `taxonomicFilterPinnedPropertiesLogic` (they're independent utilities — fine to leave for now, or migrate to small `usePersistedState` hooks).

**Phase 8 — move primitive to `@posthog/quill`** (1 PR, post-parity)

- After parity is signed off, lift the pure parts (types, hook stack, headless components) into `packages/quill/packages/components/src/filters/taxonomic/v1/`. Generify the group-type as `string`, leave the PostHog enum behind.
- PostHog keeps a thin `useKeaTaxonomicFilter` shim that calls `useTaxonomicGroupsContext` + `buildTaxonomicGroups` and forwards into quill's `useTaxonomicFilter({ ...opts, groups })`.
- The legacy `<TaxonomicFilter>` adapter re-points at the shim. No call-site changes.
- Stories move to `quill-storybook` (already picks up `packages/*/src/**/*.stories.@(...)`), no app dep cycle.
- This is the natural end-state — but it has to wait for the API surface to stabilise.

---

## 9. Risks & mitigations

| Risk                                                                                                                      | Mitigation                                                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Kea connections we forgot (e.g. `joinsLogic.columnsJoinedToPersons` for extended person properties) silently drop a group | Phase 0 RTL tests must cover every group-type-conditional render                                                                 |
| `propertyDefinitionsModel.updatePropertyDefinitions` side-effect breaks app-wide caches                                   | Keep the bridge hook (`useUpdatePropertyDefinitionsCache`) until Phase 7                                                         |
| Order-sensitive selectors (top match redistribution, recent ordering, suggested filters tab order) regress                | Move pure helpers in Phase 1 with parameterised tests; hook re-uses same fns                                                     |
| Keyboard nav corner cases (skip empty groups, mouse lockout window, autocapture quick filter selection)                   | Mirror behavior bit-for-bit; add explicit tests for each (skip, lockout, QF selection)                                           |
| Autosizer / virtualization perf regression                                                                                | Stick with `react-window` + `react-virtualized-auto-sizer` (already in repo); benchmark before/after on a 10k-property workspace |
| QuickFilterItem branching in consumers                                                                                    | Hook MUST forward `item` unchanged; `isQuickFilterItem(item)` check in callsites stays valid                                     |
| `TaxonomicPopover` arg order divergence (`(value, groupType, item)` vs. `(group, value, item)`)                           | Wrapper-level concern, not hook-level. Map at the boundary                                                                       |
| recents/pinned `_recentContext`/`_pinnedContext` hidden marker fields stripped by hook                                    | Preserve as-is; document as part of `TaxonomicDefinitionTypes` shape                                                             |
| ‘No `classNames` slot’ rule violated                                                                                      | Reviewer checklist + lint if possible                                                                                            |
| react-query introduction adds bundle weight or conflicts with existing data-fetching                                      | Audit usage in repo first; if blocked, ship with in-house micro-cache                                                            |

---

## 10. Open questions

- ~~**react-query yes/no?**~~ **RESOLVED 2026-04-27:** Not in repo. Defer dep addition; ship in-house `useTaxonomicResource` shaped like react-query so we can swap later. See §6.4.
- **Does the hook live in `packages/quill/packages/components` or in `frontend/src/lib/components/TaxonomicFilter/`?** Lean toward the latter initially (uses kea-bridges). Move to quill once kea bridges removed.
- **How do `groupAnalyticsTaxonomicGroups` / `groupAnalyticsTaxonomicGroupNames` interact with the hook?** They generate dynamic group entries from `groupsModel.groupTypes`. Plan: their generation lives inside `buildTaxonomicGroups`, fed by a small `useGroupTypes()` bridge.
- **What does the headless `<Categories>` look like for the icon-only variant?** Current code switches between `LemonTag` pills and a `CategoryDropdown`. Needs design alignment with quill button/menu styles.
- **Definition popover** — currently reaches back into `taxonomicFilterLogic` for `selectedItemMeta` + `dataWarehousePopoverFields`. Hook should expose those. Render can stay with the existing `DefinitionPopoverContents` initially.
- **`hideBehavioralCohorts` footer link** — render via `group.footerMessage` already, fine. Confirm.
- **Controlled vs uncontrolled search query** — keep both: pass `searchQuery` for controlled, `initialSearchQuery` for uncontrolled. Today's effect `useEffect(() => setSearchQuery(controlledSearchQuery))` is jank; replace with proper controlled-prop pattern.
- **Multi-select behavior** — most consumers pick one item at a time. BreakdownFilter does up to 3 via `selectedProperties`. Should the hook expose multi-select natively, or leave it to the wrapper? Recommend: wrapper-level for now, hook stays single-pick + callback-driven.
- **Is `recentTaxonomicFiltersLogic` ever consumed outside of TaxonomicFilter?** If yes, leave kea wrapper. If no, fold into a `useRecentTaxonomicFilters()` hook backed by `localStorage`. (TODO grep.)
- **Move `dataWarehouseItemUtils.ts` and `eventTypeShortcuts.ts` under `utils/`?** Both are already pure standalone files with their own tests. Phase 1 leaves them in place to avoid touching ~15 import sites for zero behaviour change. Optional cleanup in Phase 6/7.
- **kea + react-query coexistence (deferred dep)** — when we eventually add TanStack Query, kea-loaders and react-query both handle async + caching. They'd cohabit fine (different state stores), but having both adds cognitive load. Plan: only adopt TanStack if/when we're already removing kea from a region of code, not piecewise.

---

## 11. Acceptance criteria

A migration is "done" when:

1. `TaxonomicFilter` and `TaxonomicPopover` consumers render via the new headless component path with the feature flag at 100%.
2. All RTL + kea-test-utils tests pass before and after the flip on the same suite.
3. No regression in `eventUsageLogic` event volumes (`taxonomic_filter_search_query`, `taxonomic suggested filter selected`, `reportTaxonomicFilterCategorySelected`).
4. No console warnings about missing kea logic mounts in storybook or app.
5. Bundle delta < +10 KB gzipped (less if we don't add react-query).
6. Performance: keystroke-to-results latency unchanged on a 5k-property workspace (median + p95).
7. Keyboard parity: Storybook chromatic + manual checks for ↑/↓/Tab/Shift+Tab/Enter/Esc on every story.

---

## Appendix A — full consumer list

(See agent report; abbreviated here. Will expand into a per-file callsite ledger before Phase 5 flip so we know which consumer flips when.)

- TaxonomicFilter direct: 21 sites
- TaxonomicPopover/TaxonomicStringPopover: 14 sites
- PropertyFilters: 9+ sites
- PropertySelect: 3+ sites
- TaxonomicPropertyFilter (internal): driven by PropertyFilters
- Logic-only useValues consumers: 6 sites

## Appendix B — files touched / created (target end state)

Created:

- `lib/components/TaxonomicFilter/useTaxonomicFilter.ts` (hook)
- `lib/components/TaxonomicFilter/useGroupList.ts` (per-tab hook)
- `lib/components/TaxonomicFilter/useTaxonomicGroups.ts` (group config builder bridge)
- `lib/components/TaxonomicFilter/utils/redistributeTopMatches.ts`
- `lib/components/TaxonomicFilter/utils/promoteProperties.ts`
- `lib/components/TaxonomicFilter/utils/keywordShortcuts.ts`
- `lib/components/TaxonomicFilter/utils/dataWarehouseFieldDefaults.ts`
- `lib/components/TaxonomicFilter/headless/Root.tsx`
- `lib/components/TaxonomicFilter/headless/Input.tsx`
- `lib/components/TaxonomicFilter/headless/Categories.tsx`
- `lib/components/TaxonomicFilter/headless/List.tsx`
- `lib/components/TaxonomicFilter/headless/Row.tsx`
- `lib/components/TaxonomicFilter/headless/EmptyState.tsx`
- `lib/components/TaxonomicFilter/headless/DefinitionPopover.tsx`
- `lib/components/TaxonomicFilter/headless/index.ts` (compound exports)
- `lib/components/TaxonomicFilter/TaxonomicFilterDefault.tsx` (default skin)

Mutated → eventually deleted:

- `taxonomicFilterLogic.tsx`
- `infiniteListLogic.ts`
- `TaxonomicFilter.tsx` (becomes shim, deleted Phase 7)
- `InfiniteSelectResults.tsx`, `InfiniteList.tsx`, `InfiniteListRow.tsx` (deleted Phase 7)

Kept:

- `recentTaxonomicFiltersLogic.ts`, `taxonomicFilterPinnedPropertiesLogic.ts` (independent persistence; optional later cleanup)
- `eventTypeShortcuts.ts`, `dataWarehouseItemUtils.ts` (already pure utils, used by hook)
- `types.ts` (`TaxonomicFilterGroup`, `TaxonomicFilterGroupType` etc. stay as the canonical types)
- `TaxonomicFilterEmptyState.tsx`, `CategoryDropdown.tsx`, `InlineHogQLEditor.tsx` (consumed by headless or default skin)

---

_End of initial draft. Will keep extending as Phase 0 / Phase 1 implementation surfaces new constraints._
