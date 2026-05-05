---
name: modifying-taxonomic-filter
description: Guides safe modification of the TaxonomicFilter — PostHog's multi-tab picker for events, actions, properties, cohorts, and more. Front-loads the empirical product reality (what users actually pick and search for) so changes can be judged against real behavior, not architectural taste. Use when adding features, fixing bugs, or refactoring TaxonomicFilter.
---

# Modifying the TaxonomicFilter

The TaxonomicFilter is the picker users hit to choose any "thing PostHog
knows about" — events, properties, actions, cohorts, groups. It's the
on-ramp into almost every analytics and replay configuration. Code lives
in `frontend/src/lib/components/TaxonomicFilter/`.

**The unbreakable rule:** changes that demote items users _actually pick_
are regressions, even with all tests passing. Read "Product reality"
before deciding any change is safe. Ordering, promotion, or position-0
changes need explicit human sign-off — don't let an agent decide alone.

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

Five events validate every change. Treat property shapes as a public API:

- `taxonomic filter closed` — `dwellMs`, `hadSelection`
- `taxonomic filter item selected` — `sourceGroupType`, `wasFromRecents`, `wasFromPinnedList`, `wasQuickFilter`, `hadSearchInput`, `position`, `query`
- `taxonomic_filter_search_query` — `searchQuery`, `groupType`, `inputMode`, `pastedFraction`
- `taxonomic filter empty result` — `groupType`, `searchQuery`
- `taxonomic filter category dropdown opened` — A/B variant

Adding properties: fine. Removing dead ones: fine. **Renaming or
repurposing silently is the worst case** — dashboards keep working and
start lying.

## Variants you might not see locally

`TAXONOMIC_FILTER_CATEGORY_DROPDOWN` resolves to `'control'` (tab pills)
or `'pill'` (suffix dropdown). Bug reports that don't reproduce locally
are usually a variant mismatch. Touching tab rendering means testing both.

## Pre-change checklist

- [ ] Read references when relevant: [architecture](references/architecture.md),
      [common-pitfalls](references/common-pitfalls.md) (X/Y matrix),
      [call-sites](references/call-sites-and-blast-radius.md) (smoke tests),
      [testing-patterns](references/testing-patterns.md)
- [ ] Test both `control` and `pill` dropdown variants if you touched tabs
- [ ] Confirm telemetry payloads still have the same property shape
- [ ] Ordering / promotion / position-0 -> human sign-off, not agent judgement

```bash
hogli test frontend/src/lib/components/TaxonomicFilter/
```
