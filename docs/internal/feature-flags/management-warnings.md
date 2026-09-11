# Management warnings

The rules v2 management warning contract is dormant.
It defines a diagnostic value and its wire representation; it has no detectors or production consumers.

## Supported codes

Management warnings describe an actionable consequence of an otherwise valid configuration or operation.
The following triggers guide detector implementations.

| Code                                | Trigger and placement                                                                                                                                                     | Suppress when                                                                                                                    |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `RULE_ORDER_CHANGES_TRAFFIC`        | An allowed reorder changes which rule receives an overlapping population. Show it in the reorder preview.                                                                 | Target populations are disjoint, or the reorder cannot change evaluation. Reject edits to a protected experiment prefix instead. |
| `UNREACHABLE_LOWER_RULE`            | An earlier terminal catch-all prevents evaluation from reaching a lower rule. Identify the blocking and unreachable rules so the user can move or remove them.            | The earlier rule can continue to the lower rule.                                                                                 |
| `ROLLOUT_MISS_CAN_ENTER_LOWER_RULE` | A continuing rollout miss reaches a lower rule that serves the same value outside the upper rule's percentage. Identify both rules and explain the effective reach.       | Continuation alone is the only evidence. Ordinary composition of rules does not need a warning.                                  |
| `ASSIGNMENT_RESET_CHANGES_TRAFFIC`  | Resetting a non-experiment percentage rollout's seed can change who receives its value. Show it in the reset preview.                                                     | The percentage is 0 or 100, the seed is unchanged, or evaluation cannot change. Started experiment resets remain invalid.        |
| `CONCLUSION_EXPANDS_POPULATION`     | Shipping a winner or concluding to a terminal replacement extends the chosen value to people excluded by rollout or holdout. Show the expansion in the operation preview. | The removed gates do not expand who receives the value. Variant consolidation alone does not trigger it.                         |

Reorder and rollout detectors must establish the relevant overlap and reachability before asserting an effect.
They do not need a general solver for arbitrary targeting predicates.
An inconclusive comparison must not claim a proven traffic change or an exact affected percentage.
Reset and conclusion warnings belong to the operation preview, so they do not persist after the operation completes.

## Other diagnostics

SDK readiness checks need observed SDK capabilities and evaluation modes.
They belong to activation and experiment-start validation rather than configuration-only warning detectors.
Readiness explains remote request requirements and local-only or bulk-local omissions before activation; expected remote fallback alone is not a configuration defect.
Missing attribution support is explained while drafting and blocks experiment start when the readiness policy fails.
Equal-valued variants are valid, including A/A tests; the editor may explain that variant identity distinguishes them, and equality alone is not a warning.
Number and object value compatibility behavior remains deferred until those values are enabled.
None of these carry a management warning code.

## Wire compatibility and detector ownership

`ManagementWarning` requires `code` and permits optional `detail` and `attr` members.
`detail` is presentation text; `attr` is a field string or explicit null.
Parsing and serialization preserve an omitted member separately from `attr: null`.

The five codes are the complete `warning_codes` list of the harness registry at contract package 2.0.0 ([posthog-sdk-test-harness#57](https://github.com/PostHog/posthog-sdk-test-harness/pull/57), unreleased); the DTO rejects any other code.

Share the diagnostic output type across callers.
Define detector inputs alongside their implementations: rule checks need evaluated targeting and rollout fields, and lifecycle checks need the proposed operation.
The structural `ConfigV2` reader omits these fields, so it cannot serve as a universal detector input.
