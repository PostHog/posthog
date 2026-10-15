# Feature inventory

Every user-facing feature of the picker, how much it is used, and its current status.
Ratios are from a 14-day non-staff window (2026-10).
Update this file when you add, remove or change a feature.

Status meanings:

- **Protect:** carries real use.
  Changes need a metric and a guardrail.
- **Improve:** used, with a measured weakness.
- **Fix:** broken or failing for a measurable share of users.
- **Keep:** small, cheap and harmless.
- **Candidate for removal:** low use relative to cost.
  Removal still needs the checks in "Before removing anything".

| Feature                                                                                   | Use                                          | Status                            | Notes                                                                                                    |
| ----------------------------------------------------------------------------------------- | -------------------------------------------- | --------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Suggested view (default)                                                                  | ~74% of selections                           | Protect                           | It is the product.                                                                                       |
| Recents inside Suggested                                                                  | ~40% of selections                           | Protect, improve                  | Stored per browser. Syncing per user would help people on several machines.                              |
| Search                                                                                    | ~55% of selections involve it                | Protect                           | See [failure-modes](failure-modes.md) 1 and 2.                                                           |
| Email and URL promotion                                                                   | Row 0 for the top terms                      | Protect                           | `PROMOTED_PROPERTIES_BY_SEARCH_TERM`. Human sign-off to change.                                          |
| Event properties tab                                                                      | Large                                        | Improve                           | Ranking: selected items sit far down the list.                                                           |
| Person properties tab                                                                     | Large, ~70% engaged open-to-selection        | Improve                           | Weakest big tab.                                                                                         |
| Empty-result state                                                                        | ~4% of searches                              | Fix                               | Should show matches in other groups. Suggested is not counted.                                           |
| Fetch error handling                                                                      | ~2% of timed searches fail                   | Fix                               | Legacy shows an error with retry. The rebuild shows an empty list: add an error and retry.               |
| Persons search latency                                                                    | p90 ~4s                                      | Fix                               | Slowest group.                                                                                           |
| Custom key for unseen properties                                                          | Ticket theme                                 | Fix                               | Flags and cohorts especially.                                                                            |
| Pin toggle                                                                                | ~4% of selections come from pins             | Keep                              | Cheap.                                                                                                   |
| Recents tab (standalone)                                                                  | Tiny next to recents in Suggested            | Candidate for removal             | Same items already in Suggested. Its open-to-selection rate is below baseline.                           |
| Pinned tab (standalone)                                                                   | Tiny next to pins in Suggested               | Candidate for removal             | Keep the pin toggle.                                                                                     |
| Pseudo-category tabs (autocapture, pageview, screen, email addresses, elements, metadata) | Tab rarely opened                            | Candidate for removal as tabs     | Their **items** are picked through Suggested and search (`sourceGroupType`). Keep them as sources.       |
| Event match suggestion (model call)                                                       | Well under 1% of answers lead to a selection | Candidate for removal or redesign | Calls a model only for an uncached empty search. Measure uncached calls before judging cost.             |
| Search intent switch banner                                                               | ~1 in 6 shown banners lead to a switch       | Decide from its experiment        | Promotion of the predicted group happens without the banner.                                             |
| Category rail docking                                                                     | ~2% of closes are docked                     | Keep                              | Same pick rate docked or not.                                                                            |
| Include stale toggle                                                                      | Small, steady                                | Keep                              | Cheap.                                                                                                   |
| Rebuild menu (`TAXONOMIC_FILTER_MENU_REBUILD`)                                            | Some customers still see it                  | Finish or turn off                | Selection rate looks lower than legacy, but the rebuild counts every close and legacy only engaged ones. |

## Before removing anything

1. Measure use by `sourceGroupType`, not only by `groupType`.
   A tab can be unused while its items are picked every day through Suggested.
2. Separate "rarely used" from "failing".
   If a group's fetches fail, fix them before judging use.
3. Check both surfaces and every call site that passes the group.
   See [call-sites-and-blast-radius](call-sites-and-blast-radius.md).
4. Check for a running experiment on the feature.
5. Keep the telemetry event (or retire it on purpose) so dashboards don't silently go flat.
   See [telemetry-contract](telemetry-contract.md).
