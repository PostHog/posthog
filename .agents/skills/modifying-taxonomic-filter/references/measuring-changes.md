# Measuring a change

Decide before merging how you will know a change worked.
Picker changes are easy to ship and hard to judge after the fact.

## Metrics that matter

| Metric                                 | What it tells you                  | Direction                |
| -------------------------------------- | ---------------------------------- | ------------------------ |
| Engaged opens ending in a selection    | Overall success                    | Up                       |
| Position of the selected row           | Ranking quality                    | Lower is better          |
| Empty-result rate                      | Search coverage and scope mismatch | Down                     |
| Category-then-empty rate               | The hidden-mode failure            | Down                     |
| Recovery within 30s of an empty result | Empty-state quality                | Up                       |
| Select-then-reopen within 60s          | First pick was wrong               | Down, but read with care |
| Search latency p90 and p99 by group    | Speed                              | Down                     |
| Fetch failure events per search query  | Reliability                        | Down                     |
| Replay classifier success share        | Observed friction                  | Up                       |

The health dashboard (see [evidence-sources](evidence-sources.md)) has most of these as tiles.

## Guardrails

- Any ordering, default or promotion change: watch row-0 share, opens ending in a selection, and the Suggested view's share of picks.
- Any change to a group: watch that group's item use (`sourceGroupType`), not just its tab use.

## Experiments

- Ship behind a feature flag and use a PostHog experiment when the change touches defaults, ordering or what Suggested shows.
- Run long enough to include returning users.
  Effects on new users can disappear once existing users are included.
- Prefer a real control arm.
  An arm that changes the same thing in a different way can't tell you whether the change helps.

## After shipping

- Check replay evidence a week later.
  The classifier and summarizer catch failures telemetry misses.
- Update [product-reality](product-reality.md) and [feature-inventory](feature-inventory.md) if the facts changed.
