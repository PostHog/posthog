# Surfaces and mirroring

There are two live surfaces, and the rebuild is a parallel
reimplementation of the legacy data and group layer, not a skin over it.
A behaviour change usually has to land in both, or the two arms diverge.

## Two surfaces

One feature flag selects between them. A bug report that doesn't
reproduce locally is almost always a surface mismatch. Confirm which
surface the reporter is on first: every `taxonomic filter *` event
carries `surface`.

| Surface        | Flag                            | Value | What renders                                  |
| -------------- | ------------------------------- | ----- | --------------------------------------------- |
| `legacy-pill`  | `TAXONOMIC_FILTER_MENU_REBUILD` | off   | classic picker with a category dropdown       |
| `rebuild-menu` | `TAXONOMIC_FILTER_MENU_REBUILD` | on    | ground-up rewrite in `menu/` over `headless/` |

- **legacy-pill** is the classic picker (`taxonomicFilterLogic.tsx` +
  `InfiniteList`) with a suffix category dropdown. A person can pin the
  category rail from that dropdown.
- **rebuild-menu** is a fresh implementation: the `menu/` dropdown and
  combobox UI on top of `headless/` (a hooks-based filter panel). It does
  **not** route through `taxonomicFilterLogic` or `infiniteListLogic`. It
  has its own group definitions, fetch, pagination and ordering. See
  `headless/UX_SPEC.md` for its design source of truth. Some customers
  still see it, so treat it as live.

The rebuild is opt-in in exactly **two consumer wrappers**:
`TaxonomicPopover.tsx` and
`PropertyFilters/components/TaxonomicPropertyFilter.tsx`. Both check
`TAXONOMIC_FILTER_MENU_REBUILD` and render `<TaxonomicFilterMenu>` or the
legacy `<TaxonomicFilter>`.

A call site reaching one of those wrappers can still land on the legacy
path. `TaxonomicPopover` renders the rebuild only when
`newMenuSupportsCallSite` holds (`!allowClear && closeOnChange && ref ==
null`), because the rebuilt menu can't honour those three capabilities.
So "does this reach the rebuild?" depends on the wrapper and the props
that call site passes. `ActionFilterRow` goes through `TaxonomicPopover`
and passes none of the three, so it does reach the rebuild. Only a call
site that hand-rolls its own popover around `<TaxonomicFilter>` bypasses
the wrappers entirely.

**Touching tab or group rendering means testing both surfaces.**

## Mirroring changes

The same concern lives in two files. There is **no lint rule or test**
enforcing parity; the only guard is "Mirrors the legacy…" comments. When
you change one, change the other, or tell the reviewer you couldn't.

| Concern                                                  | Legacy                                                            | Rebuild                                                                           |
| -------------------------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Group definitions (endpoint, excluded props, group meta) | `taxonomicFilterLogic.tsx` `taxonomicGroups` selector             | `utils/buildTaxonomicGroups.tsx`                                                  |
| Group ordering + SuggestedFilters injection              | `taxonomicFilterLogic.tsx` `taxonomicGroupTypes` selector         | `hooks/useTaxonomicFilter.ts` `resolveTaxonomicGroupTypes`                        |
| Per-tab fetch / pagination / min-query-length            | `infiniteListLogic.ts`                                            | `hooks/useGroupList.ts` + `useTaxonomicResource.ts` + `fetchTaxonomicListPage.ts` |
| Data-warehouse config flow                               | inline in `InfiniteList.tsx`                                      | `menu/DwhFlow.tsx`                                                                |
| `taxonomic filter item selected` / `closed` telemetry    | `taxonomicFilterLogic.tsx`                                        | `menu/TaxonomicFilterMenu.tsx`                                                    |
| New `TaxonomicFilterGroupType` enum value                | `types.ts` (shared), then add group config in **both** rows above |                                                                                   |
| Logic-backed group data (Actions, Dashboards, …)         | already in kea                                                    | also register in `hooks/useTaxonomicLocalOverrides.ts`                            |

**Shared, change once:** `types.ts` (the enum),
`utils/promoteProperties.ts` (`PROMOTED_PROPERTIES_BY_SEARCH_TERM`),
`recentTaxonomicFiltersLogic.ts` and
`taxonomicFilterPinnedPropertiesLogic.ts`. The rebuild reads recents and
pins through these via a bridge; it doesn't fork them.

`redistributeTopMatches` is legacy-only: it lives in
`taxonomicFilterLogic.tsx` and the rebuild never calls it.

One intentional divergence is documented in `useTaxonomicFilter.ts`: both
surfaces lead with SuggestedFilters when the picker has more than one
substantive group. Preserve documented divergences; don't "fix" them
into parity.
