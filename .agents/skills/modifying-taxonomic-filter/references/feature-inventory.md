# Feature inventory

Every user-facing feature of the picker, how much it is used, and its current status.
Ratios come from the queries in [refreshing-product-reality](refreshing-product-reality.md), with the windows set there (2026-10), on the legacy picker unless a row says otherwise.
Update this file when you add, remove or change a feature.

Status meanings:

- **Protect:** carries real use.
  Changes need a metric and a guardrail.
- **Improve:** used, with a measured weakness.
- **Fix:** broken or failing for a measurable share of users.
- **Keep:** small, cheap and harmless.
- **Candidate for removal:** low use relative to cost.
  Removal still needs the checks in "Before removing anything".

| Feature                                                                                   | Use                                                    | Status                        | Notes                                                                                                          |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------------ | ----------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Suggested view (default)                                                                  | ~70% of selections                                     | Protect                       | It is the product.                                                                                             |
| Recents inside Suggested                                                                  | ~40% of selections                                     | Protect, improve              | Stored per browser. Syncing per user would help people on several machines.                                    |
| Search                                                                                    | ~55% of selections involve it                          | Protect                       | See [failure-modes](failure-modes.md) 1 and 2.                                                                 |
| Email and URL promotion                                                                   | Row 0 for the top terms                                | Protect                       | `PROMOTED_PROPERTIES_BY_SEARCH_TERM`. Human sign-off to change.                                                |
| Event properties tab                                                                      | Large                                                  | Improve                       | Ranking: selected items sit far down the list.                                                                 |
| Person properties tab                                                                     | Large, ~64% of closes on it pick (query 13, final tab) | Improve                       | Weakest big tab.                                                                                               |
| Empty-result state                                                                        | ~5 per 100 search queries (query 13)                   | Fix                           | Should show matches in other groups. This snapshot excludes Suggested; new clients record All-tab empties.     |
| Fetch error handling                                                                      | ~0.2 failure events per 100 search queries (query 10)  | Keep                          | Shows an error with retry.                                                                                     |
| Persons search latency                                                                    | p90 ~4s                                                | Fix                           | Slowest group.                                                                                                 |
| Custom key for unseen properties                                                          | Ticket theme                                           | Fix                           | Flags and cohorts especially.                                                                                  |
| Pin toggle                                                                                | ~4% of selections come from pins                       | Keep                          | Cheap.                                                                                                         |
| Recents tab (standalone)                                                                  | ~0.3% of closes (query 13)                             | Candidate for removal         | Same items already in Suggested. ~36% of closes on it pick, vs ~86% overall (final-tab association, query 13). |
| Pinned tab (standalone)                                                                   | ~0.06% of closes (query 13)                            | Candidate for removal         | Keep the pin toggle.                                                                                           |
| Pseudo-category tabs (autocapture, pageview, screen, email addresses, elements, metadata) | Each under 3% of category clicks (query 14, click mix) | Candidate for removal as tabs | Their **items** are picked through Suggested and search (`sourceGroupType`). Keep them as sources.             |
| Search intent switch banner                                                               | ~1 in 6 shown banners lead to a switch                 | Decide from its experiment    | Promotion of the predicted group happens without the banner.                                                   |
| Category rail docking                                                                     | ~1% of closes have docking on (query 13, preference)   | Keep                          | Pick rate ~79% docked vs ~86% undocked.                                                                        |
| Include stale toggle                                                                      | Small, steady                                          | Keep                          | Cheap.                                                                                                         |

## Before removing anything

1. Measure use by `sourceGroupType`, not only by `groupType`.
   A tab can be unused while its items are picked every day through Suggested.
2. Separate "rarely used" from "failing".
   If a group's fetches fail, fix them before judging use.
3. Check every call site that passes the group.
   See [call-sites-and-blast-radius](call-sites-and-blast-radius.md).
4. Check for a running experiment on the feature.
5. Keep the telemetry event (or retire it on purpose) so dashboards don't silently go flat.
   See [telemetry-contract](telemetry-contract.md).
6. Follow the low-usage rule in the repo's `AGENTS.md` before you remove a feature for low use.
   Query its usage over the last 6 months.
   Trigger the feature locally and confirm its events arrive, because missing events can mean broken tracking.
   Post the feature and its usage numbers in the platform UX Slack channel, and wait for the keep or remove decision there.
   Do not remove it before that decision.
