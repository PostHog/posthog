# Failure modes

The ways the picker fails users, ranked roughly by how many people they hit.
Each entry says how to spot it in data and what a fix should do.

## 1. The hidden category trap

A user picks a category, then searches for something that lives in another group, and gets nothing.

- **Signal:** a category pick followed by an empty result is ~9x more common than the reverse order.
  ~11% of opens with a category pick have an empty result after the pick, vs ~3% of opens without one.
  Selection rate drops ~23 points (~62% vs ~85%).
- **Caveat:** the ~3% is too low.
  In this snapshot, opens that stay on Suggested sent no empty-result event, so their empty states are not counted.
  New clients record All-tab empties with `scope = 'all'`; compare periods with the same coverage.
  The same gap pushes the ~9x order ratio up, because an empty search on Suggested before a category pick is never counted.
  The selection drop does not use empty-result events, so lean on it first.
- **Why:** the active category silently narrows search.
  Users don't hold the category in mind once they start typing.
- **Fix direction:** search all groups even when a tab is active.
  Show the active tab's results first, then matches from other groups.
  Never show a bare "no results" when other groups match.

## 2. Right word, wrong scope

Most empty searches are real words that exist somewhere else.

- **Signal:** the top empty queries are terms like `email`, `url`, `last seen`, `person` typed in a group that doesn't hold them.
- **Signal:** users type type-names as queries: `person`, `event`, `user`, `cohort`, `group`.
  They are trying to navigate by searching.
- **Fix direction:** the empty state should say where the term was found ("found in Person properties") and offer one click to go there.
  Treat a type-name query as a request to show that group.

## 3. Poor recovery after an empty result

- **Signal:** the health dashboard's recovery tile fell from ~46% to ~39% over three months, while the empty-result rate stayed flat.
- **Fix direction:** measure recovery directly.
  See [measuring-changes](measuring-changes.md).

## 4. Failed requests

- **Signal:** `taxonomic filter fetch failed` ~0.2 times per 100 search queries (query 10).
  One search can send several events, so this is not a share of failed searches.
  The health dashboard shows ~2%, but it divides every failure, first loads included, by timed searches, so it overstates the rate.
  Events, cohorts, person properties and flags fail most.
  Some pseudo-category groups fail more often than they are picked.
  First-load failures have only been captured since 2026-09-13, so compare from then on.
- **Why it matters:** a failure that looks like loading or like "no results" sends users away, and a 403 must not look like a slow request.
- **Current state:** the picker ends loading and shows "Couldn't load results" with a retry, except for a 403.
  `InfiniteList.tsx` (`InfiniteListErrorState`) handles this, fed by `infiniteListLogic.ts`.
  `remoteFetchForbidden` (`infiniteListLogic.ts`) shows an access-denied message with no retry for a `permission_denied` 403.
  Reduce the failures themselves.
  See [performance](performance.md).

## 5. Slow tails on a few groups

- **Signal:** `taxonomic filter search latency` (`time_to_see_data_ms`). p50 is ~200ms overall.
  Persons search has a p90 of ~4s and a p99 over 10s.
  Pageview URLs also have a slow p99.
- **Note:** customers rarely report slowness.
  Fix it, but don't rank it above failure modes 1 to 4 without evidence.

## 6. Items that don't exist yet

- **Signal:** about a third of picker support tickets.
  Users want to target a person property before any event has sent it, or can't find a distinct ID in replay filters.
- **Fix direction:** allow typing a custom key where the backend accepts it, and say plainly that it hasn't been seen yet.

## 7. Broken UI in specific scenes

- **Signal:** the largest ticket theme.
  Popover placement, options that can't be clicked or scrolled, crashes in `infiniteListLogic`, and crashes in data-warehouse flows.
- **Fix direction:** reproduce at the reporter's call site first (see [call-sites](call-sites-and-blast-radius.md)).
  Add an RTL regression test at that call site.

## 8. The weakest big tab: person properties

- **Signal:** ~64% of closes on it end in a selection (~86% across all tabs), the lowest of the large tabs.
  This counts the tab open at close, so read it as direction (see query 13 in [refreshing-product-reality](refreshing-product-reality.md)).
  Average selected position is far down the list.
  It is also the top scope for empty queries.
- **Fix direction:** rank properties seen on the chosen event or recently used higher, and separate system from custom properties.

## What "abandoned" means in replay

The replay classifier tags some sessions as abandoned.
About half of those describe the user opening and dismissing the picker without a struggle signal.
Count empty results, reopens and retyping before calling an abandoned session a failure.
