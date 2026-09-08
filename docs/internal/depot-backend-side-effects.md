# Backend side effects on Depot CI

The Depot backend workflow remains optional while GitHub Actions owns the required
`Django Tests Pass` check. Do not change branch protection as part of this rollout.

The `sample` job resolves one `side_effects` output. It is `true` when the
repository-scoped Depot variable `CI_DEPOT_SIDE_EFFECTS` equals `true`, or the PR
event contains the `depot-side-effects` label. Every ported effect consumes that
output through `needs`; missing or false outputs disable the effect.

Keep the variable `false` during shadow operation. A label enables a source PR
without raising `CI_DEPOT_SHADOW_PERCENT`; add it before the next push. Label
changes do not trigger workflows. A manual dispatch has no PR label context and
uses the Depot variable. The control job evaluates the gate even when sampling
is zero; downstream jobs retain their existing sampling behavior when disabled.

The gate initially has no effects attached. Later layers attach each group.
Hourly scheduling and `mirror-schema-cache` remain excluded: the shadow does not
own GitHub Actions' schema cache or its scheduled master baseline.

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
