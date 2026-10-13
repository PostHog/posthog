# Comparing runs without changing the denominator

Suppose two completed runs use the same suite, dataset revision, and scorer-version
UUID. Only the application revision changed. The server reports:

| Run       | Passing | Successful | Error | Missing among observed items |
| --------- | ------- | ---------- | ----- | ---------------------------- |
| Baseline  | 72      | 90         | 5     | 5                            |
| Candidate | 76      | 80         | 10    | 10                           |

The reported pass rates are 80% and 95%, a 15 percentage-point increase among
successful results. Successful coverage fell from 90 to 80 items, while errors and
missing scores grew. Report both facts; the rate alone does not establish a better
application. Inspect overlapping case identities and the newly unscored/error cases.

If the candidate instead uses a new scorer version with a looser threshold, the
rates describe different grading rules. Read both pinned configs, explain that
difference, and recommend comparing both runs under one version before attributing
the change to the application. Do not average across versions or substitute the
scorer's current config for the version attached to a result.

For repeated trials, the summary weights each item once. A case with ten trials has
ten times the weight of a case with one trial. Report differing trial coverage;
case-weighted conclusions need a separate, explicitly described calculation over
complete matching data.
