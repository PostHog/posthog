# Dynamic cohorts in exposure criteria

## The gap

When an experiment's exposure criteria filters on a dynamic cohort, flag evaluation and the
exposure query don't read the same source of truth for that cohort's membership:

- **Flag evaluation** checks the cohort's underlying filters against live person properties at
  request time. Users are routed into variants as soon as they qualify.
- **The exposure query** compiles the cohort filter to a membership check against the cohort's
  stored membership list (`raw_cohort_people`, pinned to the last completed version), which only
  recalculates periodically.

Users who qualify for the cohort's filters in the gap between recalculations get routed by the
flag but aren't reflected by the exposure query yet. When the cohort is used to _exclude_ users,
the effect inverts: users the flag no longer routes are still counted. Either way, exposure counts
drift away from flag routing, the control/test imbalance grows between recalculations and only
partially resets at each one, and the experiment eventually trips a sample ratio mismatch warning
whose cause is invisible in randomization or exposure-event configuration.

This has been observed in production: a customer used a dynamic cohort in exposure criteria to
exclude a group of users, and the imbalance grew steadily between cohort recalculations until it
tripped a sample ratio mismatch. Static cohorts don't have this gap, since their membership is
fixed at creation and both reads agree.

## What we surface

Two warnings, one detection:

- **View-time.** `ExperimentExposuresQueryRunner._evaluate_dynamic_cohort_risk` collects cohort
  ids referenced anywhere in the experiment's exposure criteria (`_collect_cohort_ids`), resolves
  them, and hands `{id, name, is_static}` to the pure evaluator
  `analysis_health.evaluate_dynamic_cohort_risk`, which returns a `DynamicCohortExposureRisk`
  naming the dynamic cohorts (or `None`). The risk rides on `ExperimentExposureQueryResponse` and
  `DynamicCohortWarning.tsx` renders it as a banner on the metrics tab, so experiments configured
  before the warning shipped still get caught.
- **Editor-time.** `ExposureCriteria.tsx` checks the in-flight criteria against `cohortsModel`
  (`getExposureCriteriaCohortIds` + `is_static`) and shows an inline warning the moment a dynamic
  cohort is attached, before anything is saved or queried.

The view-time detection also reads `team.test_account_filters` when `filterTestAccounts` is on:
`build_test_accounts_filter` ANDs those entries into the exposure query, and a cohort is one of the
allowed filter types there, so a dynamic cohort in that list carries the same gap. Editor-time
doesn't cover it: test-account filters are team settings edited elsewhere, so the exposure criteria
modal isn't where anyone would act on the warning.

The warning fires on any dynamic cohort in exposure criteria, regardless of population size or
observed imbalance. This departs from `bias_risk`, which waits for observed evidence. The gap here
is a property of the configuration rather than of the data, and the SRM only appears once the drift
is large enough to trip it, by which point the investigation cost is already paid.

## The remedy we recommend

Replace the cohort filter with a direct person-property filter — ideally the same property in both
the flag's release conditions and the exposure criteria, so flag routing and the exposure query
stay in sync by construction.
