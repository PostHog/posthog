# Surfaces and mirroring

There are two live surfaces, and the rebuild is a parallel reimplementation of the legacy data and group layer, not a skin over it.
A behavior change usually has to land in both, or the two arms diverge.

## Two surfaces

A feature flag and a per-user toggle select between them in the shared wrappers.
The flag `TAXONOMIC_FILTER_MENU_REBUILD` makes the rebuild available.
The user's saved choice in `taxonomicMenuPreferenceLogic.useNewMenu` (the "Switch to the classic filter" toggle) then decides which one renders.
It defaults to on, so a flag-on user gets the rebuild until they switch back.
A bug report that doesn't reproduce locally is almost always a surface mismatch.
Confirm which surface the reporter is on first: most `taxonomic filter *` events carry `surface` (see [telemetry-contract](telemetry-contract.md) for the exceptions).

| Surface        | When it renders                           | What renders                                  |
| -------------- | ----------------------------------------- | --------------------------------------------- |
| `legacy-pill`  | flag off, or flag on and `useNewMenu` off | classic picker with a category dropdown       |
| `rebuild-menu` | flag on and `useNewMenu` on               | ground-up rewrite in `menu/` over `headless/` |

- **legacy-pill** is the classic picker (`taxonomicFilterLogic.tsx` + `InfiniteList`) with a suffix category dropdown.
  A person can pin the category rail from that dropdown.
- **rebuild-menu** is a fresh implementation: the `menu/` dropdown and combobox UI on top of `headless/` (a hooks-based filter panel).
  It does **not** route through `taxonomicFilterLogic` or `infiniteListLogic`.
  It has its own group definitions, fetch, pagination and ordering.
  See `headless/UX_SPEC.md` for its design source of truth.
  Some customers still see it, so treat it as live.

Two **shared consumer wrappers** choose a surface: `TaxonomicPopover.tsx` and `PropertyFilters/components/TaxonomicPropertyFilter.tsx`.
Both check `TAXONOMIC_FILTER_MENU_REBUILD` and `useNewMenu`, then render `<TaxonomicFilterMenu>` or the legacy `<TaxonomicFilter>`.

Some call sites mount the rebuild directly and skip both checks.
Today that is Error Tracking's issue filters (`products/error_tracking/frontend/components/IssueFilters/FilterGroup.tsx`), which mounts `TaxonomicFilterHeadless.Root` and `TaxonomicFilterMenu`.
Every user there is on the rebuild, whatever the flag or toggle says.
Find others with a search for direct imports of `menu/TaxonomicFilterMenu` or `headless` outside `TaxonomicFilter/` and `TaxonomicPopover/`.

A call site reaching one of those wrappers can still land on the legacy path.
`TaxonomicPopover` renders the rebuild only when `newMenuSupportsCallSite` holds (`!allowClear && closeOnChange && ref == null`), because the rebuilt menu can't honor those three capabilities.
So "does this reach the rebuild?" depends on the wrapper and the props that call site passes.
`ActionFilterRow` goes through `TaxonomicPopover` and passes none of the three, so it does reach the rebuild.
`TaxonomicPropertyFilter` has a legacy branch too: without `disablePopover`, a new or empty row, or a HogQL row, sets `showInitialSearchInline` and renders the legacy picker inline, whatever the flag and toggle say.
With `disablePopover`, that branch is skipped and the flag and toggle decide.
A group row (`nestedGroup`) opens no picker at all; a leaf row inside a group follows the same rules as any other row.
Without `disablePopover`, only an existing, non-HogQL row reaches the flag and toggle check.

Many call sites skip the wrappers and mount the legacy picker directly, so they always render legacy.
Examples are `ColumnConfigurator.tsx` (inline `<TaxonomicFilter>`), `UniversalFilters.tsx` (`PureTaxonomicFilter`) and `TaxonomicBreakdownPopover.tsx`.
Search the repo for direct `<TaxonomicFilter` and `PureTaxonomicFilter` uses to find them all before you decide which surfaces a change touches.

**Touching tab or group rendering means testing both surfaces.**

## Mirroring changes

The same concern lives in two files.
There is **no lint rule or test** enforcing parity; the only guard is "Mirrors the legacy…" comments.
When you change one, change the other, or tell the reviewer you couldn't.

| Concern                                                  | Legacy                                                                                         | Rebuild                                                                                            |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Group definitions (endpoint, excluded props, group meta) | `taxonomicFilterLogic.tsx` `taxonomicGroups` selector                                          | `utils/buildTaxonomicGroups.tsx`                                                                   |
| Group ordering + SuggestedFilters injection              | `taxonomicFilterLogic.tsx` `taxonomicGroupTypes` selector                                      | `hooks/useTaxonomicFilter.ts` `resolveTaxonomicGroupTypes`                                         |
| Per-tab fetch / pagination / min-query-length            | `infiniteListLogic.ts`                                                                         | `hooks/useGroupList.ts` + `useTaxonomicResource.ts` + `fetchTaxonomicListPage.ts`                  |
| Fetch error state                                        | `InfiniteList.tsx` `InfiniteListErrorState` + `infiniteListLogic.ts`                           | `menu/Combobox.tsx` error block + `hooks/useGroupList.ts` `showErrorState`                         |
| Data-warehouse config flow                               | inline in `InfiniteList.tsx`                                                                   | `menu/DwhFlow.tsx`                                                                                 |
| `taxonomic filter item selected` / `closed` telemetry    | `taxonomicFilterLogic.tsx`                                                                     | `menu/TaxonomicFilterMenu.tsx`                                                                     |
| Standalone Recent and Pinned entries                     | `taxonomicFilterLogic.tsx` `taxonomicGroupTypes` selector (`recent_filters`, `pinned_filters`) | `menu/TaxonomicFilterMenu.tsx` (menu entries) + `menu/Combobox.tsx` (`recent` and `pinned` scopes) |
| New `TaxonomicFilterGroupType` enum value                | `types.ts` (shared), then add group config in **both** rows above                              |                                                                                                    |
| Logic-backed group data (Actions, Dashboards, …)         | already in kea                                                                                 | also register in `hooks/useTaxonomicLocalOverrides.ts`                                             |

**Shared, change once:** `types.ts` (the enum), `utils/promoteProperties.ts` (`PROMOTED_PROPERTIES_BY_SEARCH_TERM`), `recentTaxonomicFiltersLogic.ts` and `taxonomicFilterPinnedPropertiesLogic.ts`.
The rebuild reads recents and pins through these via a bridge; it doesn't fork them.

`redistributeTopMatches` is legacy-only: it lives in `taxonomicFilterLogic.tsx` and the rebuild never calls it.

Suggested ordering is shared behavior: both surfaces drop SuggestedFilters when there is one substantive group, and lead with it when there are two or more (legacy `resolveSuggestedFiltersGroup` in `taxonomicFilterLogic.tsx`, rebuild `resolveTaxonomicGroupTypes` in `hooks/useTaxonomicFilter.ts`).
Keep the two in parity when you change it.
Where a real divergence exists, it is documented next to the code; preserve those, and don't "fix" them into parity.
