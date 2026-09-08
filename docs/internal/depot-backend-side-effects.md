# Backend CI routing between GitHub Actions and Depot CI

Each Backend CI event runs on exactly one engine. Both workflows call
`.github/scripts/ci_backend_route.py` from their first job and skip every heavy
job when the answer is not them, so the tests and their side effects (snapshot
commits, uploads, comment posters, telemetry) never run twice.

## The switch

- `CI_BACKEND_DEPOT_PERCENT`, a GitHub repository variable from 0 to 100. A pull
  request routes to Depot when `pr_number % 100 < percent`, so one PR stays on
  one engine across pushes. GitHub Actions reads it through `vars`; Depot CI reads
  it through the REST API with its ambient token. Unreadable or invalid means 0.
- Labels override the percent for one PR: `ci-backend-github` wins over
  `ci-backend-depot`. Fork PRs and `no-ci` drafts always route to GitHub.
- Manual dispatches run on the engine that received them. Master pushes prime
  each engine's own schema cache, on Depot only while the percent is above 0.

Change the percent with `gh variable set CI_BACKEND_DEPOT_PERCENT --repo PostHog/posthog --body <n>`.
Setting it to 0 routes every new run to GitHub Actions; runs already in flight finish where they started.

## What the Depot workflow exposes

The `sample` job outputs `route`, plus `sampled` and `side_effects`, which are
both true only when the route is `depot`. Every ported side effect gates on
`needs.sample.outputs.side_effects`, so it runs exactly when Depot runs the tests.

The required `Django Tests Pass` check stays a GitHub Actions job. When a PR is
routed to Depot, that job relays Depot's gate conclusion instead of running the
matrix. Branch protection does not change during the rollout.

Hourly scheduling and `mirror-schema-cache` remain on GitHub Actions for now.

## Trunk uploads and quarantine

Enabled shards use canonical Trunk uploads and failure verdicts.
`TRUNK_UPLOAD_ENABLED` remains the upload kill switch, and
`TRUNK_QUARANTINE_ENABLED` controls whether a successful quarantine result can
clear a test failure. An unavailable uploader never clears a failing test.
With side effects disabled, test failures stop the shard directly.

## Artifacts and sharding plans

Enabled runs upload JUnit, coverage, selection results, timing files, and migrated
schemas to Depot. Test jobs apply the run-scoped durations snapshot before pytest.
The gate downloads failing shards' reports and keeps their latest attempt before
listing failures. Disabled runs keep floating cache restores and upload nothing.

The artifact probe used canonical upload-artifact v6 and download-artifact v7 pins.
The PR records the proof run. The probe verified JUnit contents and a hidden
`.test_durations` file across jobs. A pattern matching one artifact extracts
directly into the destination; named downloads do too. Retention expiry and
rerun replacement remain unverified.

## Cutover blockers

[Capability probe 4w340lvlgb](https://depot.dev/orgs/ntsdt08fpt/workflows/kc1d3w0pl1?job=d8k2vdqdzk)
tested a workflow-name expression and a scoped self-cancel command. Depot kept
the expression literal in both the workflow name and `github.workflow`. The
cancel command failed during run lookup with `unauthenticated: Invalid token`
using the injected job credential. No cancellation job or primary-role switch
is enabled by this stack.

The smallest naming alternative is a separate, reviewed cutover commit that
changes the static workflow name to `Backend CI`, removes sampling in the
primary role, and includes `trunk-merge/**` PRs. It must accompany the required
check's app/context change; flipping a Depot variable cannot perform the rename.
Cancellation needs an explicitly authorized CI-control credential or a Depot
capability change. Do not inject an organization credential as an implicit
fallback, and scope any future cancellation to this workflow rather than the
whole Depot run, which can contain unrelated workflows.

Auto-commits and posters need another prerequisite: the canonical snapshot
composite posts with `github.token`, while the CI report engine accepts only
`github-actions[bot]` comments. Copying it unchanged violates the dedicated-App
token requirement, and substituting an App token alone can create duplicate
reports. Add an explicit, authenticated report-author policy before porting
those steps. Coverage reporting must also retain its PR-head-script trust
boundary; do not give that job a broader App credential.

The running-time action reads GitHub Actions run metadata. Depot has separate
run identifiers, so its timing collector needs an engine-aware adapter. Reserve
`ci_engine: depot_ci` for the Depot event marker; `runner: depot` already describes
GitHub Actions jobs using Depot compute. No telemetry events are emitted by this
stack. Snapshot/OpenAPI bot commits, a known-flake quarantine, a single report
comment, per-PR label proofs, and telemetry arrival remain unverified.
