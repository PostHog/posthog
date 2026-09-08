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
