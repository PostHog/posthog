# Pulse outcome loop

Date: 2026-08-30
Status: Implemented and locally verified; production rollout remains gated
Scope: Close the recommendation-to-outcome loop for proactive prompt subscriptions

## 1. Decision

Extend the subscription-owned Pulse domain with durable outcome plans and immutable observations. Every delivered recommendation must explain why it matters now, state its confidence and effort, define an expected metric movement, and carry a server-validated measurement plan.

Preparing an artifact and adopting a recommendation are separate facts. A verified draft pull request or inert experiment is prepared. A person adopts advice explicitly, a pull request is adopted when it merges, and an experiment is adopted when a person launches it. Adoption schedules a bounded outcome readout. The completed readout joins the next normal subscription delivery instead of creating a second notification.

Existing `Opportunity` and `ActionProposal` identities remain the cross-run memory backbone. The system passes a bounded structured history to later analysis runs and enforces duplicate suppression on the server before reserving another artifact or outcome plan.

## 2. Success criteria

1. Every recommendation delivered with outcome readouts enabled has a validated baseline, expected movement, confidence, effort, and measurement plan.
2. A verified artifact never marks a recommendation adopted by itself.
3. Manual advice can be adopted or dismissed explicitly.
4. The exact Pulse-created pull request merging or experiment launching records adoption automatically.
5. Adoption schedules one readout using an allowed delay of 3, 7, 14, or 28 days.
6. A due readout appears in the first normal subscription delivery after it becomes due.
7. Readouts use reviewed PostHog reads and never arbitrary write access or arbitrary HogQL.
8. Every readout records the baseline, observed result, delta, verdict, evidence, and failure state durably.
9. Retries and overlapping deliveries cannot measure the same due plan twice or create duplicate artifacts.
10. Later runs receive enough structured history to suppress repeated recommendations without replaying raw evidence or model reasoning.
11. Disabling outcome readouts leaves normal reports, recommendations, and already prepared artifacts available.
12. No outcome readout can merge a pull request, launch an experiment, activate a flag, or mutate the measured product state.

## 3. Non-goals

- Immediate outcome notifications outside the normal subscription schedule.
- Automatic pull request merge, approval, or ready-for-review transitions.
- Automatic experiment launch, stop, conclusion, or traffic changes.
- A generic metric builder or unrestricted query replay system.
- Team-wide portfolio planning across unrelated subscriptions.
- Automatic edits to an already published Pulse pull request.
- Broader MCP write scopes.
- Causal claims for non-experiment outcomes. These readouts report an observed association against the declared baseline.

## 4. Existing foundations

The current Pulse implementation already provides the required ownership boundaries:

- `Opportunity` supplies a stable team-scoped opportunity identity.
- `ActionProposal` supplies a stable action identity and normalized target.
- `RunAction` stores the recommendation shown for one run and already has confidence and effort columns.
- `Artifact` stores authoritative prepared pull request and experiment state.
- `EvidenceToolCall` stores normalized audited tool provenance and short-lived encrypted raw bodies.
- The run snapshot includes bounded, versioned plan and outcome memory for later analysis.
- The five-minute Pulse reconciler already converges Tasks publication state.
- Tasks records authoritative pull request state from verified GitHub webhooks.
- Experiments owns launch state behind a product facade.

This design extends those seams. It does not introduce another scheduler or recommendation system.

## 5. Domain model

### 5.1 RunAction additions

Persist the complete recommendation snapshot on `RunAction`:

```text
why_now: text
confidence: decimal in [0, 1]
effort: enum[small, medium, large]
metric_name: string
metric_unit: enum[count, ratio, percent, currency, duration, other]
metric_direction: enum[increase, decrease, maintain]
expected_change_type: enum[absolute, relative_percent]
expected_change_lower: decimal
expected_change_upper: decimal
readout_after_days: enum[3, 7, 14, 28]
```

The analysis contract requires all fields. The server rejects non-finite numbers, inverted ranges, unsupported units, and unapproved readout windows. Existing `rationale` remains the evidence-backed explanation; `why_now` is the concise prioritization reason. When V1 outcome readouts are enabled, the server replaces the model-supplied metric label and unit with the measurement adapter's bounded identity and `count` unit before persistence and duplicate-key derivation.

The API no longer writes the existing `acted_on`, `acted_on_at`, and `acted_on_by_id` fields. The columns remain temporarily readable for compatibility. Artifact preparation never inherits the old automatic `acted_on=true` behavior.

### 5.2 OutcomePlan

`OutcomePlan` is a team-scoped durable state machine:

```text
team_id
subscription_id
proposal_id
source_action_id
measurement_spec: validated versioned JSON
baseline_value: decimal
baseline_from: datetime
baseline_to: datetime
adoption_status: pending | adopted | dismissed | abandoned
adoption_source: manual | pull_request_merged | experiment_launched | null
adopted_at: datetime | null
decided_by_id: integer | null
readout_status: waiting | scheduled | due | measuring | measured | inconclusive | cancelled
next_readout_at: datetime | null
attempt_count: integer
claimed_by_run_id: UUID | null
claimed_at: datetime | null
last_failure_code: string | null
completed_at: datetime | null
```

Only one non-terminal plan may exist for a stable proposal. The source action identifies the exact recommendation and baseline that created it. A later run may observe the proposal again, but it cannot create another active plan or reserve another artifact.

### 5.3 OutcomeObservation

`OutcomeObservation` is immutable and team-scoped:

```text
plan_id
run_id
attempt_number
status: measured | inconclusive | failed
observed_value: decimal | null
observed_from: datetime | null
observed_to: datetime | null
absolute_delta: decimal | null
relative_delta: decimal | null
verdict: improved | flat | regressed | inconclusive
confidence: decimal | null
evidence_set_id: UUID | null
failure_code: string | null
created_at
```

The server derives numeric deltas and verdicts. The model may write a concise explanation, but it cannot choose or override the computed result.

### 5.4 State transitions

```text
Recommendation proposed
        |
        +-- artifact verified --------------------> Prepared artifact
        |                                               |
        |                                  PR merged / experiment launched
        |                                               |
        +-- person adopts advice ----------------------> Adopted
        |                                               |
        +-- person dismisses / PR closes unmerged       v
        |                                      Readout scheduled
        |                                               |
        +-----------------------------------------------v
                                      Measured or inconclusive
```

Prepared remains an `Artifact` state. Adoption remains an `OutcomePlan` state. Neither field is inferred from the other except at the explicit merge and launch boundaries.

## 6. Measurement contract

### 6.1 Candidate supplied by analysis

Every analysis action returns a `measurement` candidate:

```json
{
  "baseline_tool_call_id": "call-id",
  "metric_name": "Checkout completions",
  "metric_unit": "count",
  "direction": "increase",
  "expected_change": {
    "type": "relative_percent",
    "lower": "2.0",
    "upper": "5.0"
  },
  "readout_after_days": 7,
  "selector": {}
}
```

The candidate must reference a successful evidence call from the same run. The server resolves it through a versioned measurement adapter and persists only the canonical server-produced specification.

### 6.2 Measurement adapters

V1 supports an explicit registry for numeric, replayable read tools. Initial adapters cover:

- `data-catalog-metric-run`
- `query-trends`
- `query-funnel`

Each adapter owns:

- accepted tool schema versions;
- selector validation;
- baseline extraction;
- finite decimal normalization;
- the exact date-range fields that may change;
- equivalent comparison-window construction; and
- result extraction for the readout.

V1 adapters extract integer counts only. Catalog metrics must return the explicit `count` unit. Trend measurements accept exactly one unbroken event or action total-count series. Funnel measurements accept only ordered step results for at least two event or action steps. Breakdowns, comparisons, sampling, group aggregation, formulas, multipliers, derived math, and non-step funnel visualizations are ineligible. Saved-insight replay remains ineligible because its mutable definition does not provide a stable scalar binding.

Each adapter derives a readable name and a separate semantic identity. Query identities include every immutable scalar-affecting filter, test-account policy, selected step, and complete funnel sequence. Commutative filters, value sets, and funnel exclusions are sorted before hashing. Comparison windows, output controls, cosmetic labels, and count-neutral funnel display settings are excluded. A model label cannot relabel a count as a percentage, merge two different filtered metrics, or split duplicate suppression by renaming the same series. Ratio, currency, duration, and percentage readouts remain ineligible until an adapter owns their scalar semantics.

The model cannot provide a JSON path or mutate arbitrary arguments. Unsupported tools, selectors, or result shapes make that recommendation ineligible for delivery and artifact reservation. Other valid recommendations in the same analysis may still proceed.

Experiment-backed plans use the recommendation's validated PostHog metric for baseline and readout. The Experiments facade is authoritative only for draft, launch, deletion, and adoption timing in V1. Pulse does not reinterpret arbitrary cached experiment-statistics payloads or claim causal lift.

### 6.3 Interpretation

For replayed metrics, the server compares the observed value with the baseline in the declared direction. The expected range is a forecast, not the boundary between success and failure. The result is:

- `improved` when movement is materially in the declared direction;
- `regressed` when movement is materially opposite;
- `flat` when movement remains inside the adapter's neutral tolerance; or
- `inconclusive` when data, permissions, or result shape is insufficient.

When the baseline is zero, the server records the absolute delta and leaves the relative delta null. For `maintain`, movement inside the adapter tolerance is `flat` and movement outside it is `regressed`.

Experiment readouts report observed movement in the declared metric after launch. They remain associative. A later version may add causal experiment results after Experiments exposes a proven scalar primary-metric contract.

## 7. Analysis and persistence flow

The Pulse analysis output gains two arrays:

```text
readouts: completed evidence references for claimed due plans
actions: zero to three new measurable recommendations
```

The active analysis sandbox obtains each claimed comparison through `pulse-outcome-replay-get`. This task-bound read tool returns only the server-derived tool name, schema version, selector, and comparison arguments. The sandbox then executes that exact read with `call --json`.

Tasks reconstructs bounded, completed PostHog MCP calls from the exact completed analysis run's persisted ACP log. Direct calls require the tool identity stamped by the ACP adapter; a model-controlled title or input field cannot assert that identity. Pulse imports only output-referenced, successful, non-truncated calls into its short-lived encrypted evidence store, then applies its own adapter validation. Tasks does not learn Pulse measurement schemas.

At analysis persistence time the server:

1. validates each due readout against its claimed plan and canonical adapter;
2. writes immutable observations with an exact evidence set, then releases or completes the plans;
3. validates new recommendation measurements against same-run evidence;
4. resolves stable opportunities and proposals;
5. suppresses proposals with an existing active, adopted, dismissed, or recently measured plan;
6. persists valid actions and outcome plans;
7. reserves at most one eligible implementation; and
8. terminalizes normally even when individual recommendations were filtered.

If no recommendation has a valid measurement, the delivery says that Pulse found no measurable recommendation. It does not publish an unmeasurable action merely to fill the report.

## 8. Adoption reconciliation and scheduling

The existing five-minute Pulse reaper gains a bounded outcome batch after its current run and publication reconciliation.

### Pull requests

Tasks exposes a narrow caller-bound artifact lifecycle DTO. Pulse queries only the task, run, publication lease, and pull request reserved by the plan's artifact.

- verified open pull request: prepared, adoption pending;
- merged pull request: adopted with source `pull_request_merged`;
- closed unmerged pull request: abandoned and readout cancelled;
- unknown state: leave unchanged and retry later.

Reconciliation binds artifacts to `OutcomePlan.source_action_id`, not only to the stable proposal. An older artifact for a repeated proposal cannot adopt a fresh plan.

### Experiments

Experiments exposes a narrow lifecycle DTO for the exact Pulse-created experiment.

- no start date: prepared draft, adoption pending;
- start date set: adopted with source `experiment_launched`;
- deleted before launch: abandoned and readout cancelled;
- ended: keep the original adoption time and make authoritative results available to the due readout.

A combined action is adopted only after its exact pull request has merged and its exact experiment has launched. The later authoritative timestamp schedules the readout. If either required artifact is abandoned, the combined plan is abandoned.

### Manual advice

The recommendation endpoint becomes an explicit decision endpoint accepting `adopted` or `dismissed`. It records the current user for a manual decision. Dismissal cancels an unclaimed readout. A person may reverse a manual decision before measurement; the endpoint records a new telemetry transition and schedules from the new adoption time. Measured plans and artifact-derived adoption cannot be reversed through this endpoint.

### Scheduling

An adoption transition sets `next_readout_at = adopted_at + readout_after_days`. The reaper marks elapsed plans `due`; it does not start a workflow or send a notification.

When a normal subscription delivery creates its Pulse snapshot, it atomically claims at most the configured number of due plans for that subscription. Claims expire after a bounded interval so a failed run cannot strand a plan.

The analysis task measures claimed plans before proposing new work. Successful and inconclusive observations join the same immutable delivery bundle before new recommendations. A delivery cutoff does not wait beyond the existing Pulse budget.

Failed measurements wait at least 24 hours before a later scheduled report can retry them, at most twice. A transient failed attempt remains an immutable audit record but does not render as a final readout. The final failure records an `inconclusive` observation and terminalizes the plan.

An analysis may return `not_ready` when the declared comparison is not yet available. This releases the claim without consuming a measurement attempt and reschedules the plan for the next delivery. A plan that remains not ready 90 days after adoption becomes inconclusive so it cannot stay active forever.

## 9. Cross-run memory and duplicate suppression

The run snapshot replaces the acted-on bucket summary with a versioned bounded memory object containing:

- active plans for the same subscription;
- recent adopted, dismissed, abandoned, measured, and inconclusive proposals;
- stable opportunity and action keys;
- target category and metric name;
- last-seen time;
- adoption source and result verdict; and
- aggregate acceptance and outcome rates by action kind and target category.

The snapshot excludes raw evidence, raw tool arguments/results, artifact credentials, and model reasoning. It is capped by row count and serialized bytes.

Prompt instructions tell the model not to repeat an active, dismissed, or recently measured proposal. Server persistence is the hard boundary:

- an active plan prevents another plan;
- an active draft pull request claim prevents another pull request;
- a repeated proposal updates `last_seen_at` and telemetry but does not render another recommendation card;
- dismissed, abandoned, measured, and inconclusive proposals remain suppressed for 90 days after their terminal transition; and
- after that window, genuinely fresh evidence may create a new plan tied to the latest action while retaining the same stable proposal identity; and
- a materially different target must use a different normalized target and stable action key.

Memory is subscription-local in the model prompt. Team-scoped uniqueness remains the final duplicate-artifact guard across overlapping subscriptions.

## 10. API and report surface

The history response adds structured recommendation and outcome fields. It never exposes measurement replay arguments or raw evidence bodies.

Each delivery renders sections in this order:

1. Outcome readouts
2. New recommendations
3. Prepared artifacts
4. Collapsed operational details

Recommendation cards show:

- why now;
- confidence and effort;
- expected metric movement;
- baseline and planned readout window;
- evidence provenance;
- artifact preparation state; and
- adoption state.

Advice-only cards show explicit `Adopt` and `Dismiss` actions with loading and double-submit guards. Artifact-backed cards show read-only `Prepared`, `Merged`, `Launched`, or `Abandoned` state. They do not let a person claim adoption before the authoritative external transition.

Readout cards show the adapter-owned metric identity and unit, baseline, observed result, absolute and relative movement, computed verdict, measurement window, associated recommendation, and artifact link when present. The same frozen bundle renders readouts before proactive actions in email and Slack. Operational build and test detail remains available but visually secondary.

## 11. Safety and failure behavior

- Outcome reads use the existing Pulse read posture and an explicit measurement adapter registry.
- No new MCP write scope is introduced.
- Measurement replay may change only adapter-owned time-window fields.
- Permission loss produces an inconclusive result, not a privileged fallback.
- Pull request adoption trusts only the Tasks caller-bound state produced from verified GitHub events.
- Experiment adoption trusts only the Experiments facade and exact stored experiment ID.
- Readout claims use row locks and expiry for concurrency safety.
- Temporal inputs carry plan IDs and references, never unbounded result bodies.
- A readout failure cannot suppress the base report or valid new recommendations.
- The destination still receives one immutable bundle per scheduled delivery.

## 12. Migration

Add a new Subscriptions migration after `0003_pulserun_orchestration_state`.

The migration:

- adds the new recommendation snapshot fields;
- creates `OutcomePlan` and `OutcomeObservation` with fail-closed team scoping;
- adds conditional uniqueness for one active plan per proposal;
- adds due-plan and reconciliation indexes; and
- leaves existing acted-on columns temporarily readable for migration compatibility.

Existing rows remain compatibility history and do not receive synthetic outcome plans. No historical row has the canonical baseline evidence required to create a safe measurement plan.

The API stops writing acted-on fields in the same release. Removal happens only after a full deploy cycle and is not part of this change.

## 13. Rollout and limits

Add `PULSE_OUTCOME_READOUT_ENABLED`, effective only when `PULSE_PROACTIVE_ENABLED` is also enabled.

Add bounded settings for:

- maximum active outcome plans per subscription;
- maximum due readouts claimed per delivery;
- allowed readout windows;
- maximum measurement attempts;
- claim expiry; and
- memory row and byte caps; and
- a fixed 90-day terminal-proposal suppression and maximum not-ready age.

Disabling the outcome switch stops new plans, adoption reconciliation, claims, and measurements. Existing plan history remains readable. Normal reports, recommendations, and already prepared artifacts continue.

Telemetry records plans created, duplicate proposals suppressed, adoption source, readouts scheduled, claims expired, attempts, verdicts, inconclusive reasons, and time from adoption to measurement. Product evaluation emphasizes adoption and measured improvement, not artifact count.

## 14. Testing

### Domain and migration

- Model constraints, indexes, team scoping, and data migration semantics.
- Prepared artifacts never become adopted during migration.
- One active plan per stable proposal under concurrent writes.
- Immutable observations and finite decimal validation.

### Measurement

- Adapter validation and extraction for every supported tool schema.
- Production-shaped trend and funnel results, including exact event or action identity and step order.
- Semantic identity false-merge and false-split coverage for filters, labels, and complete funnels.
- Exact equivalent-window rewriting and rejection of arbitrary argument changes.
- Unsupported tools, selectors, breakdowns, scaling, stale evidence, permission loss, malformed values, and non-finite values.
- Server-derived deltas, tolerances, forecasts, and verdicts.
- Experiment lifecycle adoption and non-causal metric readout behavior.

### Lifecycle

- Manual adopt, dismiss, and reversal rules.
- Verified PR remains prepared; verified merge adopts; close without merge abandons.
- Experiment draft remains prepared; launch adopts; deletion before launch abandons.
- Scheduling windows, retries, terminal inconclusive state, claim expiry, and overlapping delivery claims.

### Memory and orchestration

- Stable-key suppression across runs and subscriptions.
- Recency updates without duplicate cards or artifacts.
- Memory row and byte caps.
- Partial analyses retain valid measurable recommendations and reject invalid ones.
- Readouts persist before bundle rendering and never create a second delivery.

### API and frontend

- Generated OpenAPI types and schemas.
- Adopt and dismiss loading guards and error recovery.
- Prepared versus adopted copy.
- Outcome readout cards for improved, flat, regressed, and inconclusive states.
- Stories for mixed readouts and new recommendations, no outcomes, permission loss, and retry exhaustion.

### Controlled runtime

- A Pulse pull request opens as prepared, merges through a verified webhook, schedules a readout, and measures once in the next eligible report.
- A Pulse experiment remains inert until a person launches it, then schedules and renders the validated associated-metric readout.
- Kill-switch and revocation tests leave base delivery intact.

The controlled runtime test uses invented local data and real domain/facade persistence boundaries. It does not exercise a live GitHub webhook, a running sandbox, or a production experiment statistics payload.

## 15. Implementation boundaries

Keep the work separable into three clean layers:

1. Subscriptions domain, measurement adapters, migrations, and deterministic state-machine tests.
2. Tasks and Experiments lifecycle facades plus readout claiming and orchestration.
3. API, generated types, report UI, stories, and controlled runtime evidence.

Do not create the PR stack until the complete implementation and review fixes settle. Preserve these boundaries in commits so the final branch can be unstacked without redesigning interfaces.

## 16. Production validation still required

- Run one complete persisted sandbox analysis against a non-sensitive test project and confirm its real ACP log shape matches the bounded Tasks parser.
- Exercise one verified GitHub merge webhook and one human experiment launch through the live reaper.
- Validate delivery rendering through the running product route in addition to Storybook.
- Add causal experiment readouts only after the Experiments facade exposes a stable scalar primary-metric result contract.
