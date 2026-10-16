# Conversion goal setup with AI

## Current scope

Status: implemented behind `marketing-analytics-conversion-setup-ai` and prepared for draft review.
The branch is `codex/marketing-warehouse-attribution`; production gateway validation and the recommendation-quality gate remain pending.
This is an event/action-first implementation with backend services, generated MCP tools, and a Setup interface.
It uses each project's sources, permissions, configuration, and business definitions; it has no organization-specific event names or mappings.

The existing configuration union remains authoritative: `EventsNode`, `ActionsNode`, and `DataWarehouseNode`.
ID, timestamp, identity, amount, and currency describe the fields a query needs, not a requirement to copy every organization's conversions into one new table.
An event can be used directly, an existing action retains its filters, and warehouse tables or saved views use explicit source mappings.
Creating a view and materializing it are separate operations with separate permissions.

## Implemented behavior

1. The first eligible dashboard or Setup visit starts one project-wide analysis of the previous 30 days.
2. The server persists the run, its dates, candidates, explanations, questions, and draft definitions.
3. Later analysis requires an explicit update and covers the previous 14 days. Navigation and age do not rerun the model.
4. Concurrent requests reuse an active run. The previous completed results remain available during updates and failures.
5. The dashboard notice can always be dismissed. Dismissal is local to the user and project; Setup retains the recommendations.
6. Reviewing a candidate runs a fresh preview. Editing its name, source, filters, calculation, or classification invalidates the preview and confirmation.
7. Saving requires an exact previewed definition, explicit business confirmation, and project-admin access.
8. The server binds a 15-minute preview reference to the project, user, goal, relevant configuration, and action definition. Applying the same reference again returns the same goal, including after a lost response.
9. Responses from an old editor mount cannot affect a new draft after navigation.

The initial surface is **Marketing analytics → Setup → Conversion goals**.
The dashboard notice links back to that section.
The existing deterministic setup suggestions and manual goal editor remain available.
The on-demand PostHog AI workflow can also supply a draft through the scene integration.

## Discovery and recommendation limits

Discovery considers up to 20 active custom events and 20 recently updated accessible actions.
Event counts exclude configured test accounts; action volume and filters are checked in the preview.
Only bounded source metadata, property names, numeric-property evidence, and aggregate counts go to the model.
Raw event rows, property values, and person identifiers are not included.

Counts and UTM coverage help find candidates; neither establishes revenue or customer acquisition.
Leads, demo requests, signups, trials, and activation milestones are conversions.
Customer intent requires metadata explicitly identifying first-time acquired paying customers.
A generic paid invoice or settled order is a transaction, not evidence of first acquisition.
Revenue drafts require an observed numeric amount property and retain questions about payment status, units, currency, refunds, and duplicate transactions.
Recommendations remain hypotheses that require review.

The provider call uses the Go AI gateway, bounded output, a timeout, and no automatic retries.
The worker requires `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY`.
Generation checks organization AI data-processing approval, feature access, membership, and source permissions, including immediately before the provider call.
Missing approval or permission produces a concrete disabled reason.
Worker failures preserve older results and require a manual retry.

## API and MCP contract

| Operation                               | Behavior                                                                                |
| --------------------------------------- | --------------------------------------------------------------------------------------- |
| `GET conversion_recommendations`        | Read persisted results and run state; never start generation.                           |
| `POST conversion_recommendations/start` | Start once with `refresh: false`; explicitly update with `refresh: true`.               |
| `POST conversion_goals/preview`         | Evaluate an unsaved goal using attribution semantics and bounded query execution.       |
| `POST conversion_goals/apply`           | Apply the exact event/action draft with `preview_ref` and `definition_confirmed: true`. |

Generated MCP tools expose all four operations with project scopes and feature flags.
Read tools do not start AI; starting analysis is a write operation even though it only creates proposals.
All four tools use the conversion Setup flag; endpoint Setup and project-access checks also apply.
The compact preview/apply MCP schema keeps the generated API validator as its final parsing step, so specialized filters and validation remain supported.
See [configuration API details](marketing-analytics-configuration-writes.md) for response fields, permissions, retry behavior, and unsupported combinations.

Two additive team-scoped models store recommendation runs and preview evidence.
Writes lock the product configuration/evidence rows rather than the Team or Organization rows.
Expired unused preview evidence is reclaimed in batches of up to 500 on a subsequent preview; applied receipts remain available for idempotent retries.

## Local commits and proposed PR boundaries

These are planning labels, not GitHub PR numbers.
The work is ordered in local commits so the final publication can be split without mixing product work with the shared evaluation harness.

| Planned PR                                     | Local implementation                                                                                                                           | Local commit                                          |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| P1: conversion value and warehouse attribution | Existing integration foundation; additional fixes validate IDs after filters and bound identity lookup to conversion IDs.                      | Integration base plus `4a91b47c57e` and review fixes. |
| P2: preview API and MCP                        | Unsaved preview, exact goal definitions, generated contract, and query limits.                                                                 | `40e48c94979`                                         |
| S1: shared AI evaluation harness               | Accurate results, local sandbox configuration, and timeout reporting.                                                                          | `556aaf39ad9`                                         |
| P3: AI workflow and evaluations                | Organization-independent skill, synthetic scenarios, and evaluation tooling.                                                                   | `aa1e940ac75`                                         |
| P4: assisted editor                            | Editable drafts, fresh previews, confirmation, verification, and dismissible notice.                                                           | `c240d6ad486`                                         |
| P5/P7: persistence and validated application   | First 30-day analysis, manual 14-day updates, shared state, preview receipts, retry safety, generated MCP tools.                               | `e7943ea8d90`                                         |
| P6: persisted Setup interface                  | Recommendation cards, loading/update/error/empty states, retained results, and manual update.                                                  | `58b71c33cd2`                                         |
| Review corrections                             | Consent/flag rechecks, diagnostic compatibility, editor lifetime isolation, bounded cleanup, clearer errors, and recommendation-quality fixes. | `14143afd659`                                         |
| Runtime verification                           | Product query tags for preview/discovery, development guard coverage, and deterministic permission fixtures.                                   | Final local fix commit after `7b0e9b6e3a0`.           |

The October 15 integration incorporates `origin/master` at `0dfcf980e0c3` and preserves the local commit history.
It reconciles the modular dashboard with upstream onboarding and table/chart changes, moves the team serializer changes into its new package, and regenerates API contracts.
The local PostgreSQL migrations now follow upstream migration 1397 as 1398 and 1399; the conversion setup model migration depends on 1399.
Conversion services initialize the team extension through the shared helper before locking or reading preview evidence, including projects with no existing configuration.
Warehouse attribution retains its existing session path when the new event-only optimization is enabled.
Integration validation uses separate test databases; the earlier demo database is not migrated in place.
No push, public screenshot upload, PR creation, or merge is included.

## Validation

The local verification combines regression tests, full type checking, real query execution, browser interaction, independent review, and a small real-provider trial.

| Check                                     | Result and scope                                                                                                                                                       |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API/recommendation/serializer regressions | 50 passed after the final runtime fixes, including consent revocation, duplicate/unknown model references, evidence cleanup, and diagnostic compatibility.             |
| Warehouse attribution regressions         | 71 passed, with 3 query snapshots, after bounding the identity lookup and fixing filtered ID validation.                                                               |
| Frontend regression suites                | 13 passed across 4 suites, including first-run/manual-update policy, feature gating, and navigation during save.                                                       |
| Main frontend TypeScript                  | Full check passed.                                                                                                                                                     |
| MCP TypeScript                            | Full check passed.                                                                                                                                                     |
| Python types                              | Repository-wide mypy passed for 20,980 source files.                                                                                                                   |
| Migration                                 | Actual forward and reverse execution in a fresh schema on an isolated test database passed; existing public relations were unchanged.                                  |
| Generated MCP handlers                    | Event/action preview and read/start/apply request contracts passed a focused smoke check.                                                                              |
| Browser                                   | Rendered loading, ready, updating, failed, narrow, preview, saved, and dismissible loading states. Clicked through preview → confirmation → save → saved verification. |
| Independent review                        | Six agents covered correctness, breakability, security, database, reliability, and frontend. See the QA report for findings and dispositions.                          |

Storybook evidence uses invented fixtures and mocked HTTP responses, including a 520px scene container.
A separate local browser acceptance test used the actual Django API, PostgreSQL, and ClickHouse: three synthetic orders totaled USD 375, with two attributed orders worth USD 175 and one unattributed order worth USD 200.
The browser edited the draft, obtained another preview, confirmed it, saved it, and displayed Saved and verified; the saved definition was read back through the API.
That runtime test found missing query tags in preview and candidate discovery; both paths now attach Marketing analytics tags, and an existing real-query regression exercises the development-mode guard.
The demo keeps AI consent off and no recommendation worker is running. Its cached proposal came from the separate real-provider synthetic trial, so this is not live Go gateway/queue verification.

### Validation after integrating master

Merge commit `07c089ccaef` includes upstream `0dfcf980e0c3`.
The post-integration checks passed:

- 168 API tests, plus 134 attribution/session/evaluation tests. A separate 151-test run repeats the 134 tests and all 17 preview tests, including a project with no existing config row.
- 141 frontend tests across 16 suites, including migrated dashboard assertions and success-only settings telemetry. A final eight-test run also verifies flag gating and dashboard rendering after the project API URL and test-query lint fixes.
- 61 MCP tests, including strict schemas, schema-size limits, instructions, and compact goal parsing through the generated validator.
- 95 shared evaluation-harness tests.
- Full frontend and MCP TypeScript checks; all 1,444 Kea logic types were current; repository-wide mypy passed for 23,917 files.
- OpenAPI generation, including the desktop client; product lint; Django model/migration drift check against the isolated database. Security Semgrep passed with 35 rules over 151 files; the six new devex errors were fixed and their two rules passed on both affected files.
- Forward and reverse execution of the conversion setup migration in a temporary schema, rolled back with public relations unchanged.

These integration checks do not rerun the real-provider quality evaluation.
Preflight confirms the branch is current with the fetched master and passes format, dependency, and generated-contract checks.
Its global migration-readiness check still fails against the old local database history after migration renumbering; this is not a claim of a fully migrated development stack.
The new demo uses separate databases instead of rewriting that history.

### Real-provider quality check

Four invented catalogues ran through the production recommendation prompt and server draft construction with a real Claude Sonnet 4.6 call:

| Catalogue                                                         | Observed result                                                                                    |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Settled orders with a numeric amount, plus frequent product views | Proposed the order event for revenue, retained business/source questions, ignored the distraction. |
| Qualified demo action and workspace activation                    | Proposed generic conversions, preserved the action ID, and did not classify either as a customer.  |
| Frequent tooltip/sidebar interactions only                        | Returned no recommendations.                                                                       |
| Paid invoice without numeric amount or first-acquisition evidence | Proposed a generic conversion without revenue/customer classification.                             |

All four checks passed after tightening the prompt and retaining the first proposal when a known source is repeated.
This is a smoke evaluation, not a calibrated quality score or release gate.
The real-provider check used the existing local Anthropic client with synthetic data because Go gateway configuration was absent; production Go gateway routing remains an integration check.
An earlier definition-review evaluation scored 21/24 (87.5%), below the intended 90% target.
It repeated eight synthetic scenarios three times each; these were not 24 organizations or end-to-end saved-goal trials.
All 24 model calls completed without execution errors.
The run had no configured failure threshold, so its successful exit did not mean the quality target was met.

Comparing the three rejected responses with the evaluation criteria shows these omissions:

- Transaction identity, one of three repetitions: the response deduplicated transactions correctly but did not require a supported person mapping for attribution in the proposed warehouse view.
- Recurring revenue, two of three repetitions: the responses reopened the already specified refund treatment and did not review the attribution window/model. One mentioned a later preview; neither completed the expected definition review.

The other six scenarios passed all three repetitions.
These were incomplete recommendations; the evaluation did not execute queries or save conversion goals.
The result artifact has binary judge scores without detailed judge rationales, so the omissions above are a review against the criteria rather than a quoted judge explanation.
The four-case recommendation smoke check uses a different workflow and does not replace this evaluation.

### Definition review follow-up before judge calibration

The first follow-up updated the skill to carry forward resolved business choices and require a complete contract for proposed sources: row grain, stable conversion ID, timestamp, amount and currency where applicable, and supported person identity.
It separates definition readiness from measured attribution, works supplied numeric examples, and distinguishes business-object counts from unique-person counts.
Missing signed amounts can overstate or understate a total; a missing currency does not establish that the base-currency fallback is right or wrong.
These rules use supplied evidence and do not prescribe a provider, event name, or organization-specific customer definition.

The suite now contains 36 synthetic scenarios, retaining the original eight prompts and criteria and the original binary semantic judge.
The 28 business cases cover retail, coworking, subscriptions, healthcare, fundraising, marketplaces, education, printing, transport, fitness, CRM contracts, groceries, utilities, admissions, auctions, brokerage, games, staffing, hotels, equipment finance, gardening, wholesale produce, travel, music lessons, appliances, bike sharing, libraries, and pet grooming.
All sets have now informed development or review; cohort labels such as `holdout` record their original grouping, not an untouched validation set.

The guidance retained at that stage was evaluated on 32 scenarios three times, followed by three more repetitions of the original eight and eight newer cases: 144 responses in total.
The four final cases were evaluated only with a later experimental guidance version, which was discarded.
All 36 need a new generation run after the subsequent skill and evaluator changes below.

| Guidance version                                                     | Raw judge result | Conservative review result | Disposition                                      |
| -------------------------------------------------------------------- | ---------------- | -------------------------- | ------------------------------------------------ |
| Retained guidance, 32 distinct scenarios across two runs             | 139/144 (96.53%) | 120/144 (83.33%)           | Useful changes retained; quality target not met. |
| Shorter experimental guidance, 36 distinct scenarios across two runs | 136/144 (94.44%) | 116/144 (80.56%)           | Discarded.                                       |
| Structured-response pilot, original eight scenarios                  | 24/24 (100%)     | 15/24 (62.5%)              | Discarded; broader run not started.              |

The conservative counts retain every raw rejection and also exclude responses that independent agent review identified as false positives.
They do not replace the original judge scores or constitute a calibrated human quality benchmark.
All responses in these three experiments completed with nonempty text and `end_turn`; none had execution or judge errors.
Earlier exploratory runs scored 45/48, 68/72, and 69/72, but incomplete-output evidence and false positives prevented accepting those scores as a quality gate.
A separate-model comparison returned no generations because provider access failed; this is an infrastructure failure, not a zero quality score.

That version addressed the three previously identified omissions in both repeated runs: transaction proposals preserved person mapping, and recurring-revenue reviews preserved the supplied renewal/refund policy and discussed attribution readiness.
Other errors remained, including unsupported group counting, invented source facts, and omitted project filters.
The automatic judge accepted some of these errors and rejected some valid definition-only reviews for mentioning a later preview.
The above-90% quality target is therefore still unvalidated.

The evaluation now records the returned model, token usage, and stop reason, rejects incomplete generations before judging, and allows 4,096 output tokens instead of 1,800.
Twenty-seven deterministic scorer and generation tests pass, including truncated and empty responses; skill packaging and structural checks pass.
Because both guidance and output budget changed, the earlier 21/24 result is not a controlled estimate of the guidance's effect.

This suite makes one model call with the skill and reference text, without tools or an agent sandbox.
The completed follow-up runs used `claude-sonnet-5` and the unchanged `gpt-5.4` judge.
It does not exercise persisted Setup cards, which use a separate recommendation prompt through the Go gateway with `claude-sonnet-4-6`.
The conversational Setup workflow loads the skill in an agent run whose model depends on run configuration.
No production model configuration changed.
Definition-review scores do not validate discovery, MCP execution, saved goals, or production gateway routing.

Before claiming the quality target, calibrate the evaluator against reviewed failures, fix the remaining definition errors, freeze new validation cases, and repeat under the intended runtime and model configuration.
Retain failed responses and require all planned trials, complete generations, and no execution or judge errors in addition to a score above 90%.

### Offline calibration preparation

The skill now keeps the counted entity, attributed person, and aggregation separate, preserves project filters in future previews, and avoids inferring unstated source facts.
The customer flag follows the project's explicit definition; authoritative first-payment evidence is one supported case, not a universal customer definition.
A complete definition can be accepted before a live preview, and a corrected source must preserve the full conversion contract without asking again about resolved choices.

The definition evaluator is versioned as `evidence-checklist-v4`.
It retains all 36 generation prompts and their criteria, but replaces the previous single semantic verdict with six required checks: criterion coverage, evidence fidelity, entity semantics, source contract, numbers and filters, and review scope.
A local validator requires every check, rejects duplicates and malformed or contradictory verdicts, and accepts only a complete judge response.
One failed check rejects the answer; a provider or parser error remains a measurement error and cannot count as a correctly rejected answer.
Version 4 requires answer evidence for each criterion obligation.
An explicit reference retaining all applicable constraints can satisfy them, but retaining one constraint does not imply retention of other omitted constraints.
The local Responses adapter requests low reasoning effort for the judge while retaining its 3,000-token output budget and 60-second timeout.
Scores from different judge versions must not be combined.

Twelve independently written synthetic pairs provide 24 fixed answers with local reference labels.
Each pair contains an acceptable answer and a distinct error, including controls for a valid definition without a preview and an explicitly withdrawn mistake.
Only the audit, answer, and neutral criterion go to the judge; labels and case names stay local.
The calibration report records source and fixture hashes, a confusion matrix overall and by error class, and every disagreement.
Its gate requires all planned trials, unchanged sources, no judge errors, accuracy strictly above 90%, false-positive rate at most 5%, and false-negative rate at most 10%.
These are diagnostic references authored by agents, not a human benchmark or a representative production sample.

The calibration runner defaults to a dry run, which writes `pending_real_calibration` without generating or judging answers.
Live mode judges the fixed answers with `JUDGE_MODEL`; it does not call the recommendation generator.
It requires an explicit `OPENAI_BASE_URL` and the matching `OPENAI_API_KEY`, does not load credentials from files, and stops at the first provider or judge error.
Database access is blocked, and SDK and evaluation-library retries are disabled for this path.
The local Responses adapter preserves completion status and applies the judge output-token budget; incomplete responses cannot become valid verdicts.
When the evaluation harness enables tracing, the adapter preserves its explicit capture client and per-trial trace metadata.
Private calibration does not initialize global capture.
Reports retain completed judgments after each trial using a flushed temporary file and atomic replacement.
A failed write or replacement leaves the previous checkpoint readable.

From an activated repository environment, prepare a new report:

```bash
python -m products.marketing_analytics.evals.run_definition_calibration \
  --output /tmp/conversion-judge-readiness.json
```

When the provider is available, run the frozen cases three times using a new output path:

```bash
python -m products.marketing_analytics.evals.run_definition_calibration \
  --live --trials 3 --output /tmp/conversion-judge-calibration.json
```

Offline contract tests and reference-label inspection do not establish improved model accuracy.
A local live smoke run exposed a version 2 false positive: the judge treated retention of a reporting window as implicit retention of an omitted account filter.
The version 4 rubric addresses this inference without changing the reference labels or generation criteria.
Live calibration and production-card results must be reported separately from offline checks.
After the calibration gate passes, rerun generation and review on the intended runtime with fresh validation cases before claiming the recommendation-quality target.

### Production card generator evaluation

A payment event without an observed numeric amount property is recommended as a count conversion, with a question about the missing amount mapping, unless it meets the explicit first-customer criteria.
Revenue intent requires an observed numeric amount property.
The backend still leaves an unsupported revenue proposal without a draft if the model violates this instruction.

A separate sequential runner calls the production `ConversionRecommendationService.generate()` and `suggest()` methods with synthetic discovery candidates.
The production methods supply the prompt, model (`claude-sonnet-4-6` at this revision), token budget, forced tool schema, response parser, and draft construction; the runner does not copy those definitions or fall back to a direct provider.
Nine cases cover leads, settled revenue, activation, filtered actions, missing amounts, untrusted metadata, configured sources, first paying customers, and irrelevant activity.

The default dry run substitutes HTTP responses and blocks network access.
It proves request and draft wiring, not AI quality.
Live mode requires the production Go gateway settings `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY` and uses the same client as the worker.
It records requested and returned models, token usage, catalogs, raw responses, reasons, questions, drafts, and source hashes.
Provider errors, truncation, and invalid source references stop the run before another request.
No project database reads or writes occur.

```bash
python -m products.marketing_analytics.evals.recommendation_cards_runner \
  --dry-run --output /tmp/conversion-cards-readiness.json
```

When the gateway and provider are available, start with one case, then use a new report path for all nine cases:

```bash
python -m products.marketing_analytics.evals.recommendation_cards_runner \
  --live --case demo_is_a_lead --output /tmp/conversion-cards-smoke.json
python -m products.marketing_analytics.evals.recommendation_cards_runner \
  --live --trials 3 --output /tmp/conversion-cards-live.json
```

A live `contract_passed` result checks the selected sources, intent, math, flags, amount mappings, source identity, filters, and unresolved-decision state.
It leaves `semantic_review_status` pending: reasons and questions still require review, including unsupported factual claims.
The synthetic runner substitutes discovery and authorization and excludes database persistence, Celery dispatch, journey previews, and browser rendering.
Use the manual acceptance checklist for those separate integration boundaries.
The runner saves its initial state and each completed trial with the same atomic checkpoint writer; interruption preserves completed responses and cannot produce a passing result.

Offline validation passed 78 tests with network and database access blocked.
The card dry run completed all nine cases three times using synthetic HTTP responses, with the requested production model recorded as `claude-sonnet-4-6`.
The judge dry run prepared 72 trials and executed none; its calibration result remains pending.

## Local live validation

A local run used personal provider credentials with synthetic inputs and retained the raw reports outside the repository.
The production card service and local Go gateway completed 18 of 18 contract checks across the nine cases, with two trials per case, after clarifying the missing-amount rule.
These checks cover source selection, intent, and draft construction; they do not score every explanation or question.
The `evidence-checklist-v4` judge matched all 24 reference labels in one pass, with no false positives or false negatives, using the same GPT model and explicit low reasoning effort.
The previous rubric-only revision matched 21 of 24 labels.
The final calibration combined four retained completed trials with the twenty remaining trials after a local process interruption; source hashes and complete fixture coverage matched.
This is one diagnostic calibration pass, not the planned three repetitions or a fresh generation-quality benchmark.

Offline tests passed 78 cases, and Ruff checks passed for the changed Python files.
The complete dashboard workflow remains unverified: the full local stack startup failed and OrbStack stopped unexpectedly.
The isolated gateway was recovered and its readiness checks passed.
Discovery, authorization, persistence, Celery, preview, and applying a goal still need their separate end-to-end verification.

## Manual acceptance checklist

Use a development project with the new flag enabled, Setup access, project-admin permissions, organization AI approval, and a running analytics Celery worker configured for the Go gateway.
Enable the scene AI flags and `marketing-analytics-mcp` to test the separate conversational workflow.

- Start with no recommendation run. Open the dashboard and confirm that one 30-day analysis starts, even across multiple tabs.
- Dismiss the loading notice. Open Setup → Conversion goals and confirm that the same run remains visible.
- Reload after completion and confirm that saved results return without starting another run.
- Request an update explicitly. Confirm a 14-day window and that the previous cards remain visible while the update runs.
- Review a proposal, change its definition, and confirm that saving requires a new preview and confirmation.
- Save, retry the same request, and verify that exactly one goal exists.
- Navigate away during a delayed save, return, and review a different draft. The delayed response must not save the new unconfirmed draft.
- Check missing AI approval, read-only access, unavailable source, provider failure, no meaningful candidates, and disabled flag states.

For interface-only review, open the persisted recommendation stories in Storybook.
The Ready story supports the complete synthetic preview/confirm/save interaction without a provider or project-data access.

## Deferred increments

1. Execute the prepared judge calibration, resolve disagreements, then rerun definition generation with fresh validation cases and the intended runtime. Run and semantically review the separate production-card evaluation before accepting its quality target.
2. Warehouse candidate discovery from accessible tables and saved views with usable identity and conversion fields.
3. Suggested saved views for joins, status filtering, unit conversion, refunds, and identity mapping, followed by an explicit write and fresh preview.
4. Materialization only when measured query cost warrants it and the source's freshness requirements allow it.
5. JEV or other candidate-ranking optimizations after the baseline workflow has measured quality and cost.

The existing warehouse preview/attribution foundation does not imply automatic warehouse setup is complete.
Warehouse previews remain read-only in the guided flow until source-version validation can support safe application.
Unique mode means the first conversion in the selected window, not first-ever customer acquisition.
Unsupported warehouse filter combinations remain explicit errors, and existing attribution caps and preview approximations remain visible.

## Query correctness and permission checks

Warehouse attribution caches include the resolved goal definition and the source's access restrictions, including resources referenced through saved views.
Changing a goal while retaining its ID invalidates its attribution results.
Warehouse preview and attribution bounds preserve fractional seconds, including explicit preview timestamps.
A preview with no matching conversions or touchpoints reports zero for the corresponding value total.

Revenue and conversion-value queries reuse the goal-to-series adapter, preserving the amount property, units, filters, and currency configuration.
The retention summary returns population medians for the current and previous periods before grouping by channel.
Acquisition cards use the same bounded range for new visitors and their traffic denominator, and identify the last-90-days limit in both numeric and empty states.
Failed metric queries show an error with a retry action; loading and a successful zero result remain distinct.
