# Management warnings

The rules v2 management warning contract is dormant.
It defines a diagnostic value and its wire representation, and three configuration detectors behind a facade entrypoint that no production write path calls yet.

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
`detail` is presentation text; `attr` identifies a field when present.
An omitted `attr` and `attr: null` both mean no field and parse as `None`.
Serialization omits `attr` when it is `None`, so explicit null normalizes to an omitted member.

The five codes are the complete `warning_codes` list of the harness registry 2.0.0 in contract package 2.0.0, released in [posthog-sdk-test-harness 1.5.0](https://github.com/PostHog/posthog-sdk-test-harness/tree/e487249c34176c053f524d96bf0f99818dc91247/contracts/feature_flag_rules_v2); the DTO rejects any other code.
`products/feature_flags/backend/test/rules_v2_contract/` vendors that release's config schema, registry, warning schema and config fixtures with a digest-checked pin.

Share the diagnostic output type across callers.
Define detector inputs alongside their implementations: rule checks need evaluated targeting and rollout fields, and lifecycle checks need the proposed operation.
The structural `ConfigV2` reader omits these fields, so it cannot serve as a universal detector input; the rule detectors read `ValidatedConfig` from the strict validator instead.

## Configuration validation and rule detectors

`facade/config_validation.py` validates a complete canonical config version 2 candidate: the document a writer is about to persist, with rule ids and seeds already resolved, plus explicit `ValidationLimits` (the deployment filter byte limit and a per-rule metadata bound) from the trusted caller.
It returns a `ValidatedConfig` or raises `ConfigValidationError` with every field error in document order, each as a stable code (`required`, `invalid`, `unknown_field`, `not_unique`, `unsupported`, `limit_exceeded`), a presentation detail and a `filters.…` path.
It does not read or write the database, assign ids or seeds, check permissions, or mutate the input, and a valid result is not permission to store or activate anything.

The admitted family is deliberately narrower than the published schema: person-assigned boolean flags with `targeted_release` and `percentage_rollout` rules whose targeting uses person properties with the contract's canonical operators.
String, number and object values, experiment rules, group assignment (`aggregation_group_type_index`) and cohort, group and flag properties are refused with the `unsupported` code, never with a shape code, so a schema-valid contract fixture is not relabelled as malformed and no partially checked document succeeds.
Cohort and flag references wait for the dependency validation task; the other families wait for their milestones.

`facade/rule_warnings.py` owns the three configuration detectors and `review_config`, the dormant entrypoint that validates a candidate and returns its warnings as `ManagementWarning` values.
Validation runs first, so a warning never accompanies an invalid document.
Given the stored `ValidatedConfig`, the entrypoint also compares rule order; without it no reorder warning is claimed.

The detectors reason about one population at a time: the people who satisfy a rule's whole predicate set.
A rule provably applies to that population when its own predicate set is a subset of the population's; any other relation is inconclusive and stops the analysis, so the detectors never guess how two different predicates overlap and never claim an affected percentage.
Within a population, percentage rules split people by their assignment hash: rules that share a seed reuse the same hash interval, rules with different seeds are treated as independent, 0% includes nobody and 100% everybody.

- `UNREACHABLE_LOWER_RULE` fires for a rule that no path reaches because earlier applicable rules already settled everyone: a targeted release, a `return_default` rule or a 100% rollout that covers the rule's population, or same-seed rollouts that together close the hash space. A continuing partial rollout, a narrower conditional rule and a same-seed rollout that includes nobody do not block.
- `ROLLOUT_MISS_CAN_ENTER_LOWER_RULE` fires when a continuing partial rollout serves a value to somebody and a lower rule with the same value provably serves it to people who missed that rollout: a covering targeted release, a rollout with another seed, or a same-seed rollout with a higher percentage. A lower rule with another value, a same-seed rollout at or below the upper percentage, a 0% rule, a terminal rule in between, and an inconclusive overlap all suppress it.
- `RULE_ORDER_CHANGES_TRAFFIC` fires for a pair of rules present in both configs whose relative order flipped when some population provably settles on different values in the two orders. Equal values, disjoint or inconclusive targeting, an unmoved terminal rule above both, and rules added or removed by the edit do not produce it.

Warnings are deterministic and deduplicated per rule or rule pair; `attr` points at the affected rule and `detail` names the other rule by id, never a seed or property value.
The two lifecycle codes are not detected here; they belong to the reset and conclusion previews.
