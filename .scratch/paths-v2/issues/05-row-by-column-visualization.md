# Row-by-column visualization

Type: prototype
Status: open
Blocked by: 01

## Question

Does the draft's row-by-column model (max steps × max rows per step, "other" bucket, drop-offs) look and behave right on real data?

Prototype: revive the draft viz (in-repo scene + [PR #29364](https://github.com/PostHog/posthog/pull/29364) pieces) behind `PRODUCT_ANALYTICS_PATHS_V2` on demo data; produce screenshots to react to.

React to, one by one:

- Defaults for `maxSteps` / `maxRowsPerStep` (draft ships pickers for both) — what's readable without tuning?
- **"Other" bucket**: per-step top-N by target with the rest grouped (draft: `ROW_NUMBER() ≤ maxRowsPerStep`). Is per-target grouping right, and should "other" be expandable?
- **Drop-off rendering**: draft appends a synthetic drop-off node per session end; issue asks for a calmer display than v1's red links.
- In-column ordering: count desc, then other, then drop-off (draft behavior) — confirm.
- Percentages on nodes/edges ([#25076](https://github.com/PostHog/posthog/issues/25076)) and full path names ([#37124](https://github.com/PostHog/posthog/issues/37124), [#21998](https://github.com/PostHog/posthog/issues/21998) legibility) — in or out.

Link the prototype branch/screenshots as assets; the layout decision lands in the resolution.
