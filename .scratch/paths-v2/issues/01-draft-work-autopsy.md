# Draft-work autopsy

Type: research
Status: claimed
Blocked by: —

## Question

What exactly does the existing paths v2 draft work contain, and how far has master diverged since?

Cover:

- Inventory of [PR #29364](https://github.com/PostHog/posthog/pull/29364) (branch `paths-v2-separation`, sha `8cbbcfdc`): the `PathsV2Query`/`PathsV2Filter` schema (all fields + defaults), the query-runner pipeline stages, the frontend pieces (editor filters, `PathsV2MaxRowsPerStepPicker`/`PathsV2MaxStepPicker`, `pathsV2DataLogic`, `renderPathsV2`), and test coverage.
- Which of the PR's todo checkboxes are actually done in code vs merely claimed.
- What the merged in-repo scene (`frontend/src/scenes/paths-v2/`, [PR #28495](https://github.com/PostHog/posthog/pull/28495)) does today, and where it still leans on v1 (`PathsQuery` results, legacy `1_/path` node-name format).
- What `paths-v2-base` (`ce5106d4`) adds, if anything, beyond the other branches.
- Divergence vs today's master that affects reviving the branch: paths runner moved to `products/product_analytics/` ([PR #58954](https://github.com/PostHog/posthog/pull/58954)), schema/codegen changes (`hogli build:openapi`, generated `*Api` types), `AnalyticsQueryRunner` API drift, insight scene changes, quill chart migration.

Facts only — the rebase-vs-reimplement decision belongs to [Build route](07-build-route.md).

## Answer

Findings: [research/draft-work-autopsy.md](../research/draft-work-autopsy.md)
