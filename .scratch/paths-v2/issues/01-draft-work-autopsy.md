# Draft-work autopsy

Type: research
Status: resolved
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

Findings: [research/draft-work-autopsy.md](../research/draft-work-autopsy.md). Resolved 2026-07-27 by a `/research` agent. Gist:

- **The draft ([PR #29364](https://github.com/PostHog/posthog/pull/29364), tip `8cbbcfdc`, 81 commits, last real work Sep 2025) is a complete vertical slice** of a _separate_ `PathsV2Query` insight kind: schema (`PathsV2Filter` defaults — `maxSteps: 5`, `maxRowsPerStep: 3`, `windowInterval: 14`, `windowIntervalUnit: day`, `collapseEvents: false`, plus `series` for start/end points), runner, and full frontend insight-type plumbing behind flag `paths-v2`.
- **The core runner pipeline is done and tested**: events → per-actor arrays → gap-based `arraySplit` sessionization → consecutive dedupe → dropoff append → `maxSteps` slice → transition flattening → per-step `ROW_NUMBER() <= maxRowsPerStep` with `$$__posthog_other__$$` bucketing → aggregation with other/dropoff-last sorting. Known bugs: `toInvervalMonth` typo (month windows broken); path item hard-coded to `$pathname` (the `event` alternative commented out).
- **Half-done or absent**: start/end-point trimming is WIP at the tip (tests skipped; follow-up branch `paths-v2-base`/`ce5106d4` rips it back out), "group events by" is an unwired UI mock, persons modal is a no-op, query summary / context menu / v1→v2 migration don't exist, several tests are stale, and the tip doesn't compile (dangling `./renderPaths` import, duplicate import — merge artifacts).
- **Master has no `PathsV2Query` anywhere.** Its `frontend/src/scenes/paths-v2/` (merged [PR #28495](https://github.com/PostHog/posthog/pull/28495)) is a re-skinned Sankey consuming **v1 `PathsQuery`** results, flag-swapped at `InsightVizDisplay.tsx:383`; the legacy `"<n>_name"` prefix is stripped only at display time (`pathUtils.ts`). It kept full v1 parity (persons modal, view-funnel, exclude, set start/end).
- **Sharpest rebase conflict**: the draft deletes the flag-swap (`isUsingPathsV1/V2`) and rewrites the very scene files master now ships and evolved; the flag constant it references was renamed.
- **Structural drift**: v1 paths runner moved to `products/product_analytics/backend/hogql_queries/paths/` ([PR #58954](https://github.com/PostHog/posthog/pull/58954)), so the draft's `posthog/hogql_queries/insights/paths_v2/` no longer matches its sibling; `get_query_runner` registration stays a trivial insert.
- **Codegen drift**: schema pipeline unchanged in shape (`schema-general.ts → schema.json → schema.py`) but gained enum-splitting (`posthog/schema_enums.py`) — the PR's ~1,000 generated lines must be regenerated, not rebased. `AnalyticsQueryRunner`'s subclass contract is intact.
- **Other friction**: `d3-sankey` removed from package.json (now vendored), `EditorFilters.tsx` moved to flat `show:` flags, kea typegen now inline, and the draft's generic `entity_to_expr(EntityNode, ...)` clashes with the retention-specific one at `posthog/hogql/property.py:1369`. The draft's `ActionFilter.tsx` and `funnels/base.py` hunks already landed independently (no-ops).
