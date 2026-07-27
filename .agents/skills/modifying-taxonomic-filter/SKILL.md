---
name: modifying-taxonomic-filter
description: Guides safe modification of the TaxonomicFilter — PostHog's multi-tab picker for events, actions, properties, cohorts, and more. Front-loads the empirical product reality (what users actually pick and search for) plus the three live variants (legacy-control, legacy-pill behind TAXONOMIC_FILTER_CATEGORY_DROPDOWN, and the opt-in rebuild menu behind TAXONOMIC_FILTER_MENU_REBUILD) so changes are judged against real behavior and mirrored across surfaces, not made against one arm in isolation. Use when adding features, fixing bugs, or refactoring TaxonomicFilter, the rebuild menu, or the headless filter panel.
---

# Modifying the TaxonomicFilter

The TaxonomicFilter is the picker users hit to choose any "thing PostHog
knows about" — events, properties, actions, cohorts, groups. It's the
on-ramp into almost every analytics and replay configuration. Code lives
in `frontend/src/lib/components/TaxonomicFilter/`.

**Two unbreakable rules:**

1. Changes that demote items users _actually pick_ are regressions, even
   with all tests passing. Read "Product reality" before deciding any
   change is safe. Ordering, promotion, or position-0 changes need
   explicit human sign-off — don't let an agent decide alone.
2. There are **three live variants** behind two feature flags, and the
   rebuild is a parallel reimplementation of the legacy data + group
   layer — not a skin over it. A behaviour change usually has to land in
   **both** the legacy code and the rebuild, or the two arms of the
   experiment diverge. Read "Three variants" and "Mirroring changes"
   before assuming one edit is enough.

## Product reality (last refreshed 2026-05-02, 90-day window)

Ratios from production telemetry. Re-run via
[references/refreshing-product-reality.md](references/refreshing-product-reality.md)
when older than ~3 months.

### How users pick

- **Top three rows carry ~80% of selections** (position 0: ~56%,
  position 1: ~15%, position 2: ~8%). Demoting a popular item out of
  the top three is a real-user regression.
- **~34% selection rate.** Two of every three opens close without a
  pick. p50 dwell ~7s, p90 ~53s — most opens are quick glances.
- **Selection paths**: ~65% via search, ~19% browsed-no-search,
  ~16% from recents, <1% from pinned items.

### What users select

| Source group type   | Share |
| ------------------- | ----- |
| `events`            | ~40%  |
| `event_properties`  | ~30%  |
| `person_properties` | ~14%  |
| `cohorts`           | ~2%   |
| `email_addresses`   | ~2%   |
| `actions`           | ~2%   |
| `pageview_urls`     | ~1%   |
| everything else     | <1%   |

### What users search for (share of top-8 terms)

| Term      | Share |
| --------- | ----- |
| `email`   | ~29%  |
| `url`     | ~22%  |
| `user`    | ~12%  |
| `utm`     | ~10%  |
| `page`    | ~9%   |
| `path`    | ~8%   |
| `current` | ~6%   |
| `country` | ~5%   |

`email` and `url` are over half the top-8. They're the entire reason
`PROMOTED_PROPERTIES_BY_SEARCH_TERM` (in `infiniteListLogic.ts`) maps
them to `$email` and `$current_url` at position 0. **Touching
promotion or ordering needs explicit human sign-off.**

### Empty searches

`email`, `url`, `utm`, `path` against `cohorts`, `event_feature_flags`,
`session_properties` produce most empty-result events — users type the
same canonical terms across every tab. Tab order, suggested-filters
aggregation, and shortcut routing are how they get to the right answer.

### Input mode

~93% typed, ~7% pasted. Both feed `inputMode` on `taxonomic_filter_search_query`.

## Telemetry is a contract

Treat property shapes as a public API. Every `taxonomic filter *` event now
carries a `surface` property (`legacy-control` / `legacy-pill` /
`rebuild-menu`) so the experiment arms are distinguishable by an explicit
property, not a feature-flag join. The legacy stamp comes from
`legacyTaxonomicSurface()` in `taxonomicFilterSurface.ts`; the rebuild stamps
`rebuild-menu` from `menu/TaxonomicFilterMenu.tsx`.

Shared events both surfaces emit (keep these comparable across arms):

- `taxonomic filter closed` — `surface`, `dwellMs`, `hadSelection` (legacy
  also sends `groupType`; the rebuild omits it — there's no single active
  tab at close)
- `taxonomic filter item selected` — `surface`, `groupType`,
  `sourceGroupType`, `wasFromRecents`, `wasFromPinnedList`, `wasQuickFilter`,
  `hadSearchInput`, `position`, `query`, `wasStale`

Legacy-only: `taxonomic_filter_search_query`
(`searchQuery`, `groupType`, `inputMode`, `pastedFraction`),
`taxonomic filter empty result` (`groupType`, `searchQuery`),
`taxonomic filter include stale toggled`,
`taxonomic filter category dropdown opened` (pill only).

Rebuild-only menu events: `taxonomic filter menu opened` / `drilled` /
`closed` / `option clicked` / `item selected`.

When you add a property to a **shared** event, add it to **both** emitters
or the arms stop being comparable. Adding properties: fine. Removing dead
ones: fine. **Renaming or repurposing silently is the worst case** —
dashboards keep working and start lying.

## Three variants

Two feature flags, three surfaces. A bug report that doesn't reproduce
locally is almost always a variant mismatch — confirm which surface the
reporter is on first.

| Surface          | Flag                                 | Value       | What renders                                      |
| ---------------- | ------------------------------------ | ----------- | ------------------------------------------------- |
| `legacy-control` | `TAXONOMIC_FILTER_CATEGORY_DROPDOWN` | `'control'` | original tab-pill UI                              |
| `legacy-pill`    | `TAXONOMIC_FILTER_CATEGORY_DROPDOWN` | `'pill'`    | suffix category dropdown (`CategoryDropdown.tsx`) |
| `rebuild-menu`   | `TAXONOMIC_FILTER_MENU_REBUILD`      | on          | ground-up rewrite in `menu/` over `headless/`     |

- **legacy-control vs legacy-pill** is the same A/B we've always had —
  one codebase (`taxonomicFilterLogic.tsx` + `InfiniteList`), two render
  paths. Owner `@pauldambra`, multivariate `control,pill`. The direction
  of travel is to move everyone from control onto pill.
- **rebuild-menu** is a separate, opt-in experiment (`@adamleith`) being
  tested internally. It is a **fresh implementation**: the `menu/` dropdown
  and combobox UI on top of `headless/` (a hooks-based filter panel). It
  does **not** route through `taxonomicFilterLogic`/`infiniteListLogic`;
  it has its own group definitions, fetch/pagination, and ordering. See
  `headless/UX_SPEC.md` for its design source of truth.

The rebuild is opt-in in exactly **two consumer wrappers**:
`TaxonomicPopover.tsx` and
`PropertyFilters/components/TaxonomicPropertyFilter.tsx`. Both check
`TAXONOMIC_FILTER_MENU_REBUILD` and render `<TaxonomicFilterMenu>` or the
legacy `<TaxonomicFilter>`. Call sites that build their own popover (e.g.
`ActionFilterRow`) never see the rebuild — so "does this reach the
rebuild?" depends on the call site, not a single global switch.

**Touching tab/group rendering means testing all three surfaces.**

## Mirroring changes across variants

The rebuild reimplements the legacy data layer rather than reusing it, so
the same concern lives in two files. There is **no lint rule or test**
enforcing parity — the only guard is "Mirrors the legacy…" comments. When
you change one, change the other (or flag to the human that you can't).

| Concern                                                  | Legacy                                                               | Rebuild                                                                           |
| -------------------------------------------------------- | -------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Group definitions (endpoint, excluded props, group meta) | `taxonomicFilterLogic.tsx` `taxonomicGroups` selector                | `utils/buildTaxonomicGroups.tsx`                                                  |
| Group ordering + SuggestedFilters injection              | `taxonomicFilterLogic.tsx` `taxonomicGroupTypes` selector            | `hooks/useTaxonomicFilter.ts` `resolveTaxonomicGroupTypes`                        |
| Per-tab fetch / pagination / min-query-length            | `infiniteListLogic.ts`                                               | `hooks/useGroupList.ts` + `useTaxonomicResource.ts` + `fetchTaxonomicListPage.ts` |
| Data-warehouse config flow                               | inline in `InfiniteList.tsx`                                         | `menu/DwhFlow.tsx`                                                                |
| `taxonomic filter item selected` / `closed` telemetry    | `taxonomicFilterLogic.tsx`                                           | `menu/TaxonomicFilterMenu.tsx`                                                    |
| New `TaxonomicFilterGroupType` enum value                | `types.ts` (shared) — then add group config in **both** tables above |                                                                                   |
| Logic-backed group data (Actions, Dashboards, …)         | already in kea                                                       | also register in `hooks/useTaxonomicLocalOverrides.ts`                            |

**Genuinely shared — change once:** `types.ts` (the enum),
`utils/promoteProperties.ts` (`PROMOTED_PROPERTIES_BY_SEARCH_TERM`),
`utils/redistributeTopMatches.ts`, `recentTaxonomicFiltersLogic.ts` and
`taxonomicFilterPinnedPropertiesLogic.ts` (the rebuild reads recents/pinned
through these via a bridge, it doesn't fork them).

One intentional divergence is already documented in
`useTaxonomicFilter.ts`: the rebuild **always** leads with SuggestedFilters,
whereas legacy gates that on the pill variant. Preserve documented
divergences; don't "fix" them into parity.

## Pre-change checklist

- [ ] Read references when relevant: [architecture](references/architecture.md),
      [common-pitfalls](references/common-pitfalls.md) (X/Y matrix),
      [call-sites](references/call-sites-and-blast-radius.md) (smoke tests),
      [testing-patterns](references/testing-patterns.md)
- [ ] Decide whether the change must mirror across legacy and rebuild
      (see "Mirroring changes") — if you can only do one, say so explicitly
- [ ] Test all three surfaces if you touched tabs/groups: `legacy-control`,
      `legacy-pill`, `rebuild-menu`
- [ ] Confirm shared telemetry payloads still match across both emitters
- [ ] Ordering / promotion / position-0 -> human sign-off, not agent judgement
- [ ] Flag the ongoing experiments to the human reviewer: the
      control->pill rollout and the internal `rebuild-menu` opt-in

```bash
hogli test frontend/src/lib/components/TaxonomicFilter/
```
