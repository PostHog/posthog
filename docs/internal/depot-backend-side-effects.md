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
