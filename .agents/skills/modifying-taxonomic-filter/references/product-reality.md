# Product reality

How users actually use the picker, from production telemetry, replay review and support tickets.
Ratios only: this is a public repo.

**Last refreshed 2026-10-15.**
Telemetry is a 90-day window unless a line says otherwise.
Re-run with [refreshing-product-reality](refreshing-product-reality.md) when this is older than about three months.

## How users pick

- **~85% of engaged opens end in a selection.** p50 dwell ~5.5s, p90 ~23s.
  Most engaged opens are quick and successful.
- "Engaged" means the user interacted.
  The legacy picker sends `taxonomic filter closed` only when `hadInteraction` is true, so an open dismissed untouched is not counted.
  The rate over all opens is lower.
- The previous figure (~34%, May 2026) came from before close telemetry was complete.
  Don't compare the two numbers as a trend.
- **Position is everything.**
  Row 0 takes ~52% of picks, row 1 ~23%, row 2 ~10%.
  About 85% of picks are in the top three rows.
  These are legacy figures: the rebuild's `all` scope counts recents and pinned rows in its positions, so its numbers do not compare.
- **~96% of engaged opens never select a real category** (7-day sample, legacy picker, sessions split at each `taxonomic filter closed`).
- **Suggested carries about three quarters of selections.**
  Roughly half of those are recents.

## Selection paths

These overlap: one pick can be both searched and from recents.

| Path                         | Share of selections |
| ---------------------------- | ------------------- |
| Had search input             | ~55%                |
| From recents                 | ~40%                |
| Browsed, no search or recent | ~16%                |
| From pinned                  | ~4%                 |

Recents matter more than search share suggests.
In replay review, sessions that used a recent were classed as struggling or abandoned one third to one half as often as sessions that didn't, at every experience level.

## What users select (`sourceGroupType`)

`sourceGroupType` is where the item lives.
`groupType` is the tab that was active.
Use `sourceGroupType` when judging whether a group is used, or you'll undercount anything reached through Suggested.

| Source group type   | Share |
| ------------------- | ----- |
| `events`            | ~40%  |
| `event_properties`  | ~30%  |
| `person_properties` | ~15%  |
| `event_metadata`    | ~3%   |
| `cohorts`           | ~2%   |
| `email_addresses`   | ~2%   |
| `pageview_urls`     | ~1%   |
| `actions`           | ~1%   |
| everything else     | <1%   |

## What users search for (share of top-8 terms)

| Term     | Share |
| -------- | ----- |
| `email`  | ~19%  |
| `user`   | ~16%  |
| `url`    | ~14%  |
| `utm`    | ~13%  |
| `app`    | ~10%  |
| `page`   | ~10%  |
| `person` | ~9%   |
| `s`      | ~9%   |

`email` and `url` are still the biggest single terms, which is why `PROMOTED_PROPERTIES_BY_SEARCH_TERM` promotes `$email` and `$current_url` to row 0.
They are no longer half of the top 8.

## What values users filter on

- Email and URL properties are ~38% of chosen property values.
- Custom (non-`$`) properties are ~42% as a group.
- About half of users who filter use email or URL at all in two weeks.
  Roughly a third use only those.

So promote email and URL, but don't design only for them.

## Where it goes wrong

Summary only.
Detail in [failure-modes](failure-modes.md).

- Category picked, then a search that finds nothing: ~10% of opens with a category pick have an empty result after the pick, vs ~3% of opens without one.
  The ~3% is too low: Suggested sends no empty-result event.
- Opens with a category pick end in a selection ~56% of the time, vs ~85% without one.
- Most empty searches are ordinary words in the wrong scope.
- Recovery within 30s of an empty result fell from ~46% to ~39% (Jul to Oct 2026, health dashboard session tile) while the empty-result rate stayed flat.
- About 2% of timed searches end in a fetch failure (health dashboard).
  Per typed legacy search the overall rate is well under 1%.
  Cohorts, events, person properties and flags make up most of the failures.
- Person properties is the weakest big tab: ~70% of engaged opens on it end in a selection.

## What customers report

Support tickets mentioning the picker, by theme (12 months):

| Theme                                    | Share of tickets |
| ---------------------------------------- | ---------------- |
| UI bugs: placement, can't click, crashes | ~45%             |
| Missing items (not yet ingested, hidden) | ~33%             |
| Wrong category or type                   | ~23%             |
| Slowness                                 | none             |

Engineering latency data shows real slow tails (see [performance](performance.md)).
Customers don't name it as the problem.

## Input mode

~93% typed, ~7% pasted.

## Caveats

- The open-level splits cover engaged legacy opens only.
  A picker that stays mounted can merge several opens into one, so treat those ratios as direction.
- Some dashboard tiles include staff traffic.
  Filter it when it matters.
- Replay classifier results are a sample, and the prompt has changed over time.
  Compare within one scanner version.
