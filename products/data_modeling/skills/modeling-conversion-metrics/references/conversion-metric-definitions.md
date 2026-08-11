# Conversion metric definitions

| Metric                      | Definition                                                                                                            |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Overall conversion rate** | units reaching step k / units entering step 1, within the conversion window.                                          |
| **Step-to-step conversion** | units reaching step k / units reaching step k-1. Isolates per-step drop-off.                                          |
| **Drop-off**                | `1 − step-to-step conversion` at each step; the count that entered step k-1 but not step k.                           |
| **Time to convert**         | elapsed time between step entries for converted units; report median and mean (mean is skewed by long tails).         |
| **Conversion window**       | max elapsed time from step 1 to the final step for a unit to count as converted. A hard filter, not a display option. |

## Order modes

- **Ordered** — steps happen in order; other events may occur between them. The usual default.
- **Strict** — no other tracked event may occur between two steps. Rare; use for tight flows.
- **Any order** — steps in any sequence within the window.

## Attribution (for breakdowns)

When you break a funnel down by a property whose value can differ across a unit's events, pick how the unit
gets its breakdown value:

- **First-touch** — the value on the unit's first step. Most common for acquisition analysis.
- **Last-touch** — the value at conversion.
- **Per-step** — the value on each step (a unit can appear in different buckets at different steps).

The rates change with the choice, so state it explicitly in the model's column annotations.

## Aggregation unit

`person_id` for user funnels; a group key (`$group_0`, account id) for B2B/account funnels — an account
"converts" if _any_ of its users completes the steps. Keep this consistent with your revenue and activation
models so the numbers reconcile.
