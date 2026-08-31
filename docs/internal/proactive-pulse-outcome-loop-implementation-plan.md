# Pulse outcome loop implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the proactive recommendation loop by tracking adoption and measured outcomes, surfacing the decision context in every report, and suppressing repeated proposals across runs.

**Architecture:** Extend the Subscriptions-owned Pulse domain with `OutcomePlan` and immutable `OutcomeObservation` records. Persist server-canonical measurement replay plans during analysis, reconcile authoritative PR and experiment lifecycle state through product facades, claim due readouts in the next normal delivery, and expose the result through generated API contracts and a LemonUI delivery surface.

**Tech stack:** Django/Postgres, frozen Python facade contracts, Celery reconciliation, Tasks and Experiments product facades, DRF/OpenAPI/Orval, Kea, React, LemonUI, Jest, pytest, Storybook, and browser QA.

**Spec:** `docs/internal/proactive-pulse-outcome-loop.md`

## Global constraints

- `PULSE_OUTCOME_READOUT_ENABLED` is effective only when `PULSE_PROACTIVE_ENABLED` is also enabled.
- Allowed readout delays are exactly 3, 7, 14, or 28 days.
- A normal delivery claims at most the configured bounded number of due plans; no separate notification or workflow is created.
- A failed measurement is attempted at most twice. A final failure records an inconclusive observation.
- A statistically immature experiment uses `not_ready` without consuming an attempt and becomes inconclusive after 90 days.
- Dismissed, abandoned, measured, and inconclusive proposals remain suppressed for 90 days.
- Measurement replay may change only adapter-owned time-window fields. No arbitrary JSON path, query, argument rewrite, HogQL, or new MCP write scope is allowed.
- A verified artifact is prepared, not adopted. Only an attested pull request merge, a human experiment launch, or an explicit advice decision records adoption.
- Artifact-backed adoption is read-only in the UI. Advice-only recommendations expose Adopt and Dismiss with loading and double-submit guards.
- Readout observations are immutable and their deltas and verdicts are computed by the server.
- Outcome readouts appear before new recommendations, prepared artifacts, and operational details in the existing immutable delivery bundle.
- Keep legacy `acted_on`, `acted_on_at`, and `acted_on_by_id` columns readable for one deploy cycle, but stop writing them.
- Use `@frozen` for new Subscriptions DTOs and pydantic frozen dataclasses for Tasks facade contracts.
- Use generated `*Api` frontend types and generated API functions. Never hand-edit generated files.
- Use LemonUI, keep business logic in `subscriptionSceneLogic`, and render loading, error, empty, and resolved states distinctly.
- Every production behavior follows red-green-refactor. Extend the nearest test unless the behavior belongs to a new pure unit.
- Preserve the three final commit boundaries: Subscriptions domain/measurement, lifecycle facades/orchestration, and API/UI/runtime evidence.

---

### Task 1: Persist outcome plans and observations

**Files:**

- Modify: `products/subscriptions/backend/models.py`
- Modify: `products/subscriptions/backend/pulse/models.py`
- Create: `products/subscriptions/backend/migrations/0004_pulse_outcome_loop.py`
- Modify: `products/subscriptions/backend/migrations/max_migration.txt`
- Modify: `products/subscriptions/backend/pulse/tests/test_models.py`
- Create: `products/subscriptions/backend/pulse/tests/test_migration_0004.py`

**Interfaces:**

- Produces `RunAction` recommendation snapshot fields: `why_now`, `metric_name`, `metric_unit`, `metric_direction`, `expected_change_type`, `expected_change_lower`, `expected_change_upper`, and `readout_after_days`; existing `confidence` and `effort` become required for new writes at the service boundary.
- Produces team-scoped `OutcomePlan` with proposal/source-action identity, canonical measurement spec, baseline window/value, adoption state, readout state, bounded claim state, and completion/failure timestamps.
- Produces immutable team-scoped `OutcomeObservation` with attempt, observation window/value, server-derived deltas, verdict, confidence, evidence link, and failure code.
- Later tasks import these models only from `products.subscriptions.backend.models`; `pulse/models.py` remains a compatibility re-export.

- [ ] **Step 1: Add failing model behavior tests**

Extend `TestPulseModels` with one setup helper that creates a measurable recommendation and cases that prove:

```python
assert plan.team_id == self.team.id
assert plan.adoption_status == OutcomePlan.AdoptionStatus.PENDING
assert plan.readout_status == OutcomePlan.ReadoutStatus.WAITING
assert plan.attempt_count == 0
assert plan.claimed_by_run_id is None
```

Add a transaction case where a second pending/adopted non-terminal plan for the same proposal raises `IntegrityError`, while a new plan after the first becomes `measured` is allowed. Add a case where calling `save()` on an existing `OutcomeObservation` raises `OutcomeObservation.ImmutableError`. Add a team-scope case proving another project cannot read either record through the default manager.

- [ ] **Step 2: Run the focused model tests and verify RED**

Run:

```bash
hogli test products/subscriptions/backend/pulse/tests/test_models.py
```

Expected: collection or assertions fail because `OutcomePlan`, `OutcomeObservation`, and the new `RunAction` fields do not exist.

- [ ] **Step 3: Add the additive models and migration**

Use nullable recommendation snapshot columns so historical `RunAction` rows remain valid. New analysis persistence in Task 3 rejects missing values.

Define closed enums on the models:

```python
class AdoptionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ADOPTED = "adopted", "Adopted"
    DISMISSED = "dismissed", "Dismissed"
    ABANDONED = "abandoned", "Abandoned"

class ReadoutStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    SCHEDULED = "scheduled", "Scheduled"
    DUE = "due", "Due"
    MEASURING = "measuring", "Measuring"
    MEASURED = "measured", "Measured"
    INCONCLUSIVE = "inconclusive", "Inconclusive"
    CANCELLED = "cancelled", "Cancelled"
```

Use `DecimalField(max_digits=30, decimal_places=10)` for metric values and deltas. Use `db_constraint=False` for the inherited Team FK and no User FK for `decided_by_id`. Add indexes over `(team, subscription_id, readout_status, next_readout_at)`, `(team, adoption_status, updated_at)`, and `(team, claimed_at)`. Add a conditional unique constraint on `proposal` while adoption is pending/adopted and readout is waiting/scheduled/due/measuring.

The compatibility data migration must not infer a plan from `expected_impact` or expired evidence. Historical rows have no server-canonical replay specification, so it creates no synthetic plans. This preserves manual acted-on rows as legacy history and keeps automatic no-actor rows as prepared artifacts only.

- [ ] **Step 4: Validate the migration SQL and model tests**

Run:

```bash
./manage.py sqlmigrate subscriptions 0004
hogli test products/subscriptions/backend/pulse/tests/test_models.py products/subscriptions/backend/pulse/tests/test_migration_0004.py
./manage.py makemigrations subscriptions --dry-run --check
```

Expected: additive SQL only, focused tests pass, and no model-state drift remains.

- [ ] **Step 5: Commit the domain schema**

```bash
git add products/subscriptions/backend/models.py products/subscriptions/backend/pulse/models.py products/subscriptions/backend/migrations/0004_pulse_outcome_loop.py products/subscriptions/backend/migrations/max_migration.txt products/subscriptions/backend/pulse/tests/test_models.py products/subscriptions/backend/pulse/tests/test_migration_0004.py
git commit -m "feat(subscriptions): add Pulse outcome records"
```

---

### Task 2: Canonicalize measurements and bounded cross-run memory

**Files:**

- Create: `products/subscriptions/backend/pulse/measurements.py`
- Create: `products/subscriptions/backend/pulse/outcome_memory.py`
- Modify: `products/subscriptions/backend/pulse/contracts.py`
- Modify: `products/subscriptions/backend/facade/contracts.py`
- Modify: `products/subscriptions/backend/pulse/services.py`
- Modify: `products/subscriptions/backend/facade/pulse.py`
- Create: `products/subscriptions/backend/pulse/tests/test_measurements.py`
- Create: `products/subscriptions/backend/pulse/tests/test_outcome_memory.py`
- Modify: `products/subscriptions/backend/pulse/tests/test_services.py`

**Interfaces:**

- Consumes the `RunAction`, `OutcomePlan`, and `OutcomeObservation` schema from Task 1.
- Produces frozen `MeasurementCandidate`, `MeasurementEvidence`, `CanonicalMeasurement`, and `OutcomeEvaluation` contracts.
- Produces `canonicalize_measurement(candidate, evidence) -> CanonicalMeasurement` and `evaluate_measurement(plan, evidence) -> OutcomeEvaluation`.
- Produces `build_outcome_memory(*, team_id: int, subscription_id: int, now: datetime | None = None) -> OutcomeMemoryDTO` with version `1`, bounded proposal rows, and aggregate adoption/outcome buckets.
- Produces semantic `stable_action_key(*, kind: ActionKind, normalized_target: dict[str, str], metric_name: str) -> str`; model-authored titles and summaries do not affect identity.

- [ ] **Step 1: Write failing pure measurement tests**

Create parameterized cases for `data-catalog-metric-run`, `insight-query`, `query-trends`, and `query-funnel`. Each fixture contains literal arguments, result, selector, baseline value, baseline window, and expected canonical specification. The regression named by these cases is accepting an unsupported result shape or allowing the model to choose an extraction path.

Add cases that prove:

```python
assert evaluation.absolute_delta == Decimal("5")
assert evaluation.relative_delta is None  # zero baseline
assert evaluation.verdict == "improved"
```

Also cover non-finite numbers, inverted expected ranges, unsupported tool/schema versions, selector fields outside the adapter allowlist, changed non-window arguments, `maintain` tolerance, and permission/result-shape failures returning an inconclusive evaluation.

- [ ] **Step 2: Run measurement tests and verify RED**

Run:

```bash
hogli test products/subscriptions/backend/pulse/tests/test_measurements.py
```

Expected: import failure because the registry and contracts do not exist.

- [ ] **Step 3: Implement the versioned adapter registry**

Define adapters by exact `(tool_name, tool_schema_version)` keys. Each adapter owns `validate_selector`, `canonicalize`, `comparison_arguments`, `extract_value`, and `neutral_tolerance`. Persist only the canonical replay arguments, selector, extraction kind chosen by the adapter, original baseline window/value, and adapter version. Reject JSON paths or arbitrary argument patches from the candidate.

`canonicalize_measurement` parses finite `Decimal` values, verifies the evidence call succeeded in the same run, and produces a JSON-serializable server-owned spec. `evaluate_measurement` reconstructs equivalent comparison windows, validates immutable arguments, computes absolute/relative deltas, and returns improved/flat/regressed/inconclusive without consulting the expected forecast range.

- [ ] **Step 4: Write failing memory and semantic-identity tests**

Create cases where the same normalized target and metric with different titles produce the same stable action key, while a changed target produces a different key. Create subscription-local history containing active, dismissed, abandoned, measured, and inconclusive plans and assert the versioned memory contains only bounded keys, state, metric, source, verdict, and timestamps. Assert raw evidence, arguments, results, rationale, and artifact credentials never occur in the serialized payload. Add row-cap and byte-cap cases.

- [ ] **Step 5: Implement the memory builder and retire acted-on summaries**

Replace `ActionHistorySummary` with:

```python
@frozen
class OutcomeMemoryDTO:
    version: int
    proposals: tuple[OutcomeMemoryProposalDTO, ...]
    buckets: tuple[OutcomeMemoryBucketDTO, ...]
    rows_considered: int
    truncated: bool
```

Read only the current subscription's plans/actions. Suppress active plans and terminal plans whose transition is less than 90 days old. Aggregate adoption and measured-improvement rates by action kind and target category. Apply configured row/byte caps after canonical JSON encoding.

- [ ] **Step 6: Run focused pure tests**

Run:

```bash
hogli test products/subscriptions/backend/pulse/tests/test_measurements.py products/subscriptions/backend/pulse/tests/test_outcome_memory.py products/subscriptions/backend/pulse/tests/test_services.py
```

Expected: all measurement, identity, privacy, and bounds cases pass.

- [ ] **Step 7: Commit deterministic measurement and memory**

```bash
git add products/subscriptions/backend/pulse/measurements.py products/subscriptions/backend/pulse/outcome_memory.py products/subscriptions/backend/pulse/contracts.py products/subscriptions/backend/facade/contracts.py products/subscriptions/backend/pulse/services.py products/subscriptions/backend/facade/pulse.py products/subscriptions/backend/pulse/tests/test_measurements.py products/subscriptions/backend/pulse/tests/test_outcome_memory.py products/subscriptions/backend/pulse/tests/test_services.py
git commit -m "feat(subscriptions): measure Pulse recommendations"
```

---

### Task 3: Persist measurable actions, suppress duplicates, and claim due readouts

**Files:**

- Create: `products/subscriptions/backend/pulse/outcomes.py`
- Modify: `products/subscriptions/backend/pulse/contracts.py`
- Modify: `products/subscriptions/backend/pulse/orchestration.py`
- Modify: `products/subscriptions/backend/facade/pulse.py`
- Modify: `products/subscriptions/backend/pulse/dispatch_snapshot.py`
- Modify: `products/subscriptions/backend/pulse/telemetry.py`
- Modify: `posthog/settings/subscriptions.py`
- Modify: `products/subscriptions/backend/pulse/tests/test_orchestration.py`
- Modify: `products/subscriptions/backend/pulse/tests/test_dispatch_snapshot.py`
- Create: `products/subscriptions/backend/pulse/tests/test_outcomes.py`
- Modify: `products/subscriptions/backend/pulse/tests/test_telemetry.py`

**Interfaces:**

- Consumes the canonical measurement/evaluation functions and outcome-memory DTOs from Task 2.
- Produces `claim_due_outcomes(*, team_id: int, subscription_id: int, run_id: UUID, now: datetime, limit: int) -> tuple[ClaimedOutcomeDTO, ...]` using row locks and claim expiry.
- Produces `persist_outcome_readouts(input: PulseOutcomeReadoutPersistenceInput) -> tuple[OutcomeObservationDTO, ...]`, which validates same-run evidence and finalizes or releases each claimed plan.
- Produces `create_outcome_plan(*, action: RunAction, measurement: CanonicalMeasurement) -> OutcomePlan` inside the analysis transaction.
- Extends the task output contract to exact top-level keys `readouts`, `actions`, and `selected_action_key`.
- Extends the dispatch snapshot with bounded outcome memory and claimed plan references only while both Pulse switches are enabled.

- [ ] **Step 1: Add failing orchestration tests for measurable persistence**

Extend the nearest persistence tests so an action without a valid measurement is filtered, a valid sibling still persists, and no invalid action reserves an artifact. Add a replay test proving the same proposal updates `last_seen_at` but creates no second `RunAction`, `OutcomePlan`, card, or artifact while suppressed.

Add a concurrency test where overlapping calls attempt to claim the same due plan and exactly one run receives it. Add claim-expiry, two failed-attempt, final-inconclusive, and experiment `not_ready` cases. Use injected `now` values and no sleeps.

- [ ] **Step 2: Run focused orchestration tests and verify RED**

Run:

```bash
hogli test products/subscriptions/backend/pulse/tests/test_outcomes.py products/subscriptions/backend/pulse/tests/test_orchestration.py
```

Expected: failures identify the missing claim service, measurement fields, and duplicate filtering.

- [ ] **Step 3: Implement the outcome state-machine service**

Keep state changes in short `transaction.atomic()` blocks. `claim_due_outcomes` selects plans for one team/subscription where `readout_status=due`, reclaims expired `measuring` rows, applies `select_for_update(skip_locked=True)`, binds `claimed_by_run_id`, sets `claimed_at`, and returns bounded DTOs. Never increment attempts at claim time.

`persist_outcome_readouts` increments attempts only for actual failed measurements, creates exactly one immutable observation per attempt, computes deltas through `measurements.py`, and terminalizes measured/inconclusive plans. `not_ready` releases and reschedules without incrementing. The 90-day maximum produces an inconclusive observation.

- [ ] **Step 4: Extend analysis parsing and persistence**

Add exact frozen inputs for readouts and measurement candidates. Change `_ANALYSIS_OUTPUT_SCHEMA` so every new action requires why-now, confidence in `[0, 1]`, effort in `small|medium|large`, metric fields, expected-change bounds, readout delay, selector, and baseline evidence call ID. Require `readouts` even when empty.

During persistence:

1. validate and store claimed readouts;
2. canonicalize each action independently against same-run evidence;
3. derive semantic proposal keys;
4. lock/update existing proposals and suppress active/recent ones;
5. create actions and outcome plans only for valid unsuppressed candidates;
6. select the highest-ranked still-eligible implementation; and
7. terminalize normally when all new candidates were filtered.

- [ ] **Step 5: Thread settings and snapshot data**

Add bounded defaults:

```text
PULSE_OUTCOME_READOUT_ENABLED=false
PULSE_MAX_ACTIVE_OUTCOME_PLANS=20
PULSE_MAX_DUE_READOUTS_PER_DELIVERY=3
PULSE_OUTCOME_MAX_ATTEMPTS=2
PULSE_OUTCOME_CLAIM_EXPIRY_SECONDS=7200
PULSE_OUTCOME_MEMORY_MAX_ROWS=50
PULSE_OUTCOME_MEMORY_MAX_BYTES=16384
```

Keep allowed windows and both 90-day limits as server constants. Add `allow_outcome_readouts` to effective flags and bounded claim/memory limits to the immutable dispatch snapshot. When disabled, do not create plans or claim readouts, but continue persisting measurable recommendation snapshots and already authorized artifacts.

Record plan creation, duplicate suppression, claims, attempts, verdicts, and inconclusive reasons through `ph_scoped_capture`. Pin the existing event namespace and add only bounded IDs, enums, durations, and counts. Never capture replay specifications, evidence bodies, prompts, titles, or rationale.

- [ ] **Step 6: Run orchestration and snapshot tests**

Run:

```bash
hogli test products/subscriptions/backend/pulse/tests/test_outcomes.py products/subscriptions/backend/pulse/tests/test_orchestration.py products/subscriptions/backend/pulse/tests/test_dispatch_snapshot.py products/subscriptions/backend/pulse/tests/test_activity_facade.py products/subscriptions/backend/pulse/tests/test_telemetry.py
```

Expected: partial valid analyses, duplicate suppression, claim lifecycle, and switch behavior pass.

- [ ] **Step 7: Commit analysis and claiming**

```bash
git add posthog/settings/subscriptions.py products/subscriptions/backend/pulse/outcomes.py products/subscriptions/backend/pulse/contracts.py products/subscriptions/backend/pulse/orchestration.py products/subscriptions/backend/facade/pulse.py products/subscriptions/backend/pulse/dispatch_snapshot.py products/subscriptions/backend/pulse/telemetry.py products/subscriptions/backend/pulse/tests/test_outcomes.py products/subscriptions/backend/pulse/tests/test_orchestration.py products/subscriptions/backend/pulse/tests/test_dispatch_snapshot.py products/subscriptions/backend/pulse/tests/test_activity_facade.py products/subscriptions/backend/pulse/tests/test_telemetry.py
git commit -m "feat(subscriptions): close the Pulse analysis loop"
```

---

### Task 4: Reconcile authoritative PR and experiment adoption

**Files:**

- Modify: `products/tasks/backend/facade/contracts.py`
- Modify: `products/tasks/backend/facade/api.py`
- Modify: `products/tasks/backend/tests/test_staged_task_runs.py`
- Modify: `products/experiments/backend/facade/contracts.py`
- Modify: `products/experiments/backend/facade/api.py`
- Modify: `products/experiments/backend/test/test_facade.py`
- Modify: `products/subscriptions/backend/pulse/reaper.py`
- Modify: `products/subscriptions/backend/pulse/outcomes.py`
- Modify: `products/subscriptions/backend/pulse/tests/test_orchestration.py`
- Modify: `products/subscriptions/backend/pulse/tests/test_experiment_drafts.py`

**Interfaces:**

- Consumes plan/adoption transition functions from Task 3 and exact artifact IDs already stored by Subscriptions.
- Tasks produces `get_staged_artifact_lifecycle(input: GetStagedArtifactLifecycleInput) -> StagedArtifactLifecycleDTO | None` with exact caller/task/run/lease ownership and state `open|merged|closed|unknown`.
- Experiments produces `get_pulse_experiment_lifecycle(team_id, experiment_id) -> PulseExperimentLifecycleDTO | None` with state `draft|launched|ended|deleted`, launch/end timestamps, result state `not_ready|measured|inconclusive`, observed value/delta/confidence when authoritative, and safe experiment link identity.
- Subscriptions consumes only those DTOs and the exact IDs already stored on its `Artifact`.

- [ ] **Step 1: Add failing facade contract tests**

For Tasks, extend staged-publication tests to prove a caller with the wrong run, successor run, or lease cannot learn lifecycle state. Prove webhook-attested merged and closed states map correctly and unknown stays unknown.

For Experiments, extend the facade tests to prove a draft has no adoption time, a launched experiment returns its exact `start_date`, a deleted pre-launch experiment is deleted, and an unfinished statistics calculation returns `not_ready` without inventing a value.

- [ ] **Step 2: Run facade tests and verify RED**

Run:

```bash
hogli test products/tasks/backend/tests/test_staged_task_runs.py products/experiments/backend/test/test_facade.py
```

Expected: imports or assertions fail because the lifecycle facade methods do not exist.

- [ ] **Step 3: Implement narrow lifecycle facades**

Map Tasks state only from caller-bound staged publication records and verified Task-side PR state. Do not call GitHub from Subscriptions. Map Experiments lifecycle and authoritative primary-metric result inside the Experiments product; permission/deletion/not-ready outcomes remain explicit DTO states.

- [ ] **Step 4: Add failing reaper adoption tests**

Extend reaper tests with these observable transitions:

```text
verified open PR -> prepared, pending
merged PR -> adopted, pull_request_merged, scheduled
closed PR -> abandoned, cancelled
draft experiment -> prepared, pending
launched experiment -> adopted, experiment_launched, scheduled
deleted draft -> abandoned, cancelled
```

Add due marking, expired claim release, exact scheduling from `adopted_at + readout_after_days`, idempotent repeat polling, and outcome-switch-off cases.

- [ ] **Step 5: Append bounded outcome reconciliation to the existing reaper**

Keep `reconcile_pulse_runs_task()` and the existing five-minute schedule. After current run/publication convergence and evidence purge, process a bounded plan/artifact batch. Use the outcome service for transitions and schedule telemetry on commit. Do not enqueue a workflow or send a notification.

- [ ] **Step 6: Run lifecycle tests**

Run:

```bash
hogli test products/tasks/backend/tests/test_staged_task_runs.py products/experiments/backend/test/test_facade.py products/subscriptions/backend/pulse/tests/test_orchestration.py products/subscriptions/backend/pulse/tests/test_experiment_drafts.py
```

Expected: ownership fences, lifecycle mapping, and adoption scheduling pass.

- [ ] **Step 7: Commit lifecycle facades and reconciliation**

```bash
git add products/tasks/backend/facade/contracts.py products/tasks/backend/facade/api.py products/tasks/backend/tests/test_staged_task_runs.py products/experiments/backend/facade/contracts.py products/experiments/backend/facade/api.py products/experiments/backend/test/test_facade.py products/subscriptions/backend/pulse/reaper.py products/subscriptions/backend/pulse/outcomes.py products/subscriptions/backend/pulse/tests/test_orchestration.py products/subscriptions/backend/pulse/tests/test_experiment_drafts.py
git commit -m "feat(subscriptions): reconcile Pulse adoption"
```

---

### Task 5: Expose decisions, history, and outcome-first delivery

**Files:**

- Modify: `products/subscriptions/backend/pulse/contracts.py`
- Modify: `products/subscriptions/backend/facade/contracts.py`
- Modify: `products/subscriptions/backend/facade/api.py`
- Modify: `products/subscriptions/backend/facade/pulse.py`
- Modify: `products/subscriptions/backend/presentation/serializers.py`
- Modify: `products/subscriptions/backend/presentation/views.py`
- Modify: `products/subscriptions/backend/routes.py`
- Modify: `products/subscriptions/backend/pulse/delivery_bundle.py`
- Modify: `products/subscriptions/backend/pulse/tests/test_api.py`
- Modify: `products/subscriptions/backend/pulse/tests/test_delivery_bundle.py`
- Regenerate: `products/subscriptions/frontend/generated/api.schemas.ts`
- Regenerate: `products/subscriptions/frontend/generated/api.ts`
- Regenerate: `products/subscriptions/frontend/generated/api.zod.ts`

**Interfaces:**

- Consumes outcome plan, observation, decision, history, and artifact lifecycle state from Tasks 1-4.
- Replaces the acted-on request with `{ "decision": "adopted" | "dismissed" }` at `POST /api/projects/{team_id}/subscriptions/pulse/actions/{action_id}/decision/`.
- Produces `OutcomeDecisionDTO` with plan ID, action ID, adoption/readout states, adopted/decision timestamps, actor, and next readout date.
- Extends history DTOs with recommendation context, prepared/adoption state, and immutable readout cards; never includes `measurement_spec`, replay arguments, raw bodies, or model reasoning.
- Extends bundle JSON with top-level `readouts` before `actions`; `prepared_artifacts` and `operational_details` remain distinct fields.

- [ ] **Step 1: Write failing API decision tests**

Replace acted-on endpoint cases with advice-only adopt, dismiss, manual reversal before measurement, rejection after measurement, rejection for artifact-backed actions, team/authorization fences, and double-submit idempotency. Keep one serializer-level parameterized test for invalid decisions and one DB-backed endpoint wiring case.

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
hogli test products/subscriptions/backend/pulse/tests/test_api.py
```

Expected: the decision route and DTOs are absent.

- [ ] **Step 3: Implement the explicit decision endpoint and history DTOs**

Use `StrictSerializer`, `ChoiceField`, `help_text`, `@validated_request`, and declared response/error schemas. The facade authorizes the subscription and snapshot context, delegates state transitions to `outcomes.py`, records the current user, and never writes legacy acted-on fields.

History returns readouts separately from actions. Recommendation history includes why-now, confidence, effort, metric label/unit/direction, expected bounds, baseline/window, readout delay, adoption state/source/date, and artifact links. Readouts include baseline, observed value/window, deltas, verdict, confidence, failure code, recommendation title, and safe artifact links.

- [ ] **Step 4: Write failing immutable-bundle tests**

Extend delivery-bundle tests to decode the JSON and assert key order and content:

```python
assert list(payload)[:4] == ["version", "run_id", "destination_label", "base_report"]
assert payload["readouts"][0]["verdict"] == "improved"
assert payload["actions"][0]["adoption_state"] == "pending"
assert "measurement_spec" not in encoded.decode()
```

Cover mixed readouts and recommendations, no outcomes, permission-loss inconclusive, retry exhaustion, and unchanged one-bundle idempotency.

- [ ] **Step 5: Render outcome-first immutable bundles**

Query observations by `run_id` before actions. Emit bounded readout payloads, recommendation payloads, prepared artifact payloads, and operational detail without raw measurement replay data. Continue truncating the base report first when the 64 KiB bundle cap is reached.

- [ ] **Step 6: Regenerate and verify OpenAPI clients**

Run:

```bash
hogli build:openapi
hogli test products/subscriptions/backend/pulse/tests/test_api.py products/subscriptions/backend/pulse/tests/test_delivery_bundle.py
```

Expected: generated decision API/types replace acted-on generated symbols and all focused backend tests pass.

- [ ] **Step 7: Commit API and report contracts**

```bash
git add products/subscriptions/backend/pulse/contracts.py products/subscriptions/backend/facade/contracts.py products/subscriptions/backend/facade/api.py products/subscriptions/backend/facade/pulse.py products/subscriptions/backend/presentation/serializers.py products/subscriptions/backend/presentation/views.py products/subscriptions/backend/routes.py products/subscriptions/backend/pulse/delivery_bundle.py products/subscriptions/backend/pulse/tests/test_api.py products/subscriptions/backend/pulse/tests/test_delivery_bundle.py products/subscriptions/frontend/generated/api.schemas.ts products/subscriptions/frontend/generated/api.ts products/subscriptions/frontend/generated/api.zod.ts
git commit -m "feat(subscriptions): report Pulse outcomes"
```

---

### Task 6: Build the guided proactive PM delivery experience

**Files:**

- Modify: `products/subscriptions/frontend/scenes/subscriptionSceneLogic.tsx`
- Modify: `products/subscriptions/frontend/scenes/subscriptionSceneLogic.test.ts`
- Modify: `products/subscriptions/frontend/scenes/SubscriptionScene.tsx`
- Modify: `products/subscriptions/frontend/scenes/components/SubscriptionDeliveryHistory.tsx`
- Modify: `products/subscriptions/frontend/scenes/components/SubscriptionDeliveryHistory.test.tsx`
- Modify: `products/subscriptions/frontend/scenes/components/SubscriptionAiReportDelivery.tsx`
- Modify: `products/subscriptions/frontend/scenes/components/SubscriptionPulseDelivery.tsx`
- Modify: `products/subscriptions/frontend/scenes/components/SubscriptionPulseDelivery.test.tsx`
- Modify: `products/subscriptions/frontend/scenes/components/subscriptionStoryFixtures.ts`
- Modify: `products/subscriptions/frontend/scenes/components/SubscriptionDeliveryHistory.stories.tsx`

**Interfaces:**

- Consumes the generated decision functions and expanded history DTOs from Task 5.
- Kea exposes `decidePulseAction(actionId, decision)`, `pulseDecisionLoadingIds`, `updatePulseOutcomeDecision`, and `finishPulseOutcomeDecision` using generated API types.
- `SubscriptionPulseDelivery` accepts `decisionLoadingIds` and `onDecision(actionId, decision)`.
- The visual hierarchy is readouts, recommendations, prepared artifacts, then operational detail.

- [ ] **Step 1: Write failing Kea decision tests**

Replace acted-on logic tests with cases proving the generated request body is `{ decision: "adopted" }`, repeated dispatches for the same action send one request, the returned plan state updates all copies in history, refetch occurs after success, and failure clears loading state and shows an actionable error.

- [ ] **Step 2: Run the focused logic test and verify RED**

Run:

```bash
hogli test products/subscriptions/frontend/scenes/subscriptionSceneLogic.test.ts
```

Expected: failures identify old acted-on actions and endpoint symbols.

- [ ] **Step 3: Implement decision state in Kea**

Reuse the existing per-action request `Set` guard. Replace the old loading reducer and listener with decision names, call the generated decision endpoint, apply the server DTO, and always clear both the Set entry and loading reducer in `finally`. Use the toast: `Could not update this recommendation. Try again.`

- [ ] **Step 4: Write failing delivery component tests**

Add DOM cases proving:

- readout cards precede recommendation cards;
- improved, flat, regressed, and inconclusive verdict labels render;
- why now, confidence, effort, expected movement, baseline, and planned readout date render;
- verified/open artifacts show Prepared and no Adopt/Dismiss controls;
- merged and launched artifacts show their authoritative state;
- advice-only pending recommendations show Adopt and Dismiss;
- both decision buttons disable and show a loading state during a request; and
- the narrow action row wraps without a fixed viewport-width dependency.

- [ ] **Step 5: Implement the LemonUI visual hierarchy**

Model the expanded surface on the existing `SubscriptionPulseDelivery` density and `SubscriptionAiReportDelivery` detail hierarchy. Use `LemonTag` for verdict/adoption/effort state and `LemonButton` for decisions and links. Keep the main card flat, use token-backed classes only, wrap action/meta rows, and keep build/test evidence inside a visually secondary details block.

Use these visible labels and sentence-case copy:

```text
Outcome readouts
New recommendations
Prepared artifacts
Operational details
Why now
Expected movement
Baseline
Readout in 7 days
Adopt
Dismiss
Prepared
Merged
Launched
Abandoned
```

- [ ] **Step 6: Add visual-regression stories**

Extend fixtures and stories for mixed readouts/recommendations, no due outcomes, permission-loss inconclusive, retry exhaustion, and a narrow container. Use invented `example.com` data and no customer or internal operational content.

- [ ] **Step 7: Run frontend tests, type generation, typecheck, and formatter**

Run:

```bash
hogli test products/subscriptions/frontend/scenes/subscriptionSceneLogic.test.ts products/subscriptions/frontend/scenes/components/SubscriptionPulseDelivery.test.tsx products/subscriptions/frontend/scenes/components/SubscriptionDeliveryHistory.test.tsx
pnpm --filter=@posthog/frontend typegen:file products/subscriptions/frontend/scenes/subscriptionSceneLogic.tsx
pnpm --filter=@posthog/frontend typescript:check
pnpm --filter=@posthog/frontend fix
```

Expected: focused Jest tests pass, inline Kea types are current, TypeScript passes, and formatting introduces no unrelated churn.

- [ ] **Step 8: Commit the guided PM surface**

```bash
git add products/subscriptions/frontend/scenes/subscriptionSceneLogic.tsx products/subscriptions/frontend/scenes/subscriptionSceneLogic.test.ts products/subscriptions/frontend/scenes/SubscriptionScene.tsx products/subscriptions/frontend/scenes/components/SubscriptionDeliveryHistory.tsx products/subscriptions/frontend/scenes/components/SubscriptionDeliveryHistory.test.tsx products/subscriptions/frontend/scenes/components/SubscriptionAiReportDelivery.tsx products/subscriptions/frontend/scenes/components/SubscriptionPulseDelivery.tsx products/subscriptions/frontend/scenes/components/SubscriptionPulseDelivery.test.tsx products/subscriptions/frontend/scenes/components/subscriptionStoryFixtures.ts products/subscriptions/frontend/scenes/components/SubscriptionDeliveryHistory.stories.tsx
git commit -m "feat(subscriptions): show Pulse outcomes"
```

---

### Task 7: Verify the complete loop and capture runtime evidence

**Files:**

- Create locally only: `.qa-frontend/runs/<timestamp>/` screenshots and QA notes
- Update: `docs/internal/proactive-pulse-outcome-loop.md` status and verified behavior only after the checks pass

**Interfaces:**

- Consumes the complete committed implementation and focused test evidence from Tasks 1-6.
- Produces a clean, tested branch suitable for later unstacking along the three architecture boundaries.
- Produces public-safe screenshots of the mixed report, advice decision, prepared artifact, and outcome readout states.
- Produces an evidence-calibrated proactive PM grade based on demonstrated behavior, with gaps separated from verified functionality.

- [ ] **Step 1: Run the complete focused backend suite**

Run:

```bash
hogli test products/subscriptions/backend/pulse/tests products/tasks/backend/tests/test_staged_task_runs.py products/experiments/backend/test/test_facade.py
```

Expected: all Pulse domain, adapter, lifecycle, API, delivery, Tasks, and Experiments facade tests pass.

- [ ] **Step 2: Run static and migration checks**

Run:

```bash
ruff check products/subscriptions/backend products/tasks/backend/facade products/experiments/backend/facade
ruff format --check products/subscriptions/backend products/tasks/backend/facade products/experiments/backend/facade
./manage.py makemigrations subscriptions --dry-run --check
uv run mypy --cache-fine-grained .
hogli ci:preflight --strict
git diff --check
```

Expected: no lint, format, migration drift, mypy, preflight, or whitespace failures.

- [ ] **Step 3: Run the complete focused frontend suite**

Run:

```bash
hogli test products/subscriptions/frontend/scenes
pnpm --filter=@posthog/frontend typegen:check
pnpm --filter=@posthog/frontend typescript:check
pnpm --filter=@posthog/frontend build
```

Expected: scene tests, generated Kea types, TypeScript, and the production frontend build pass.

- [ ] **Step 4: Exercise controlled end-to-end state transitions**

Use synthetic local records and facade fakes to demonstrate one advice adoption, one prepared PR that later becomes merged, one launched experiment, one due claim, and one measured readout. Verify the normal subscription delivery contains one immutable bundle with the readout before new recommendations. Do not contact GitHub, launch a real experiment, or publish any artifact.

- [ ] **Step 5: Render and inspect the affected surface**

Start the local stack or Storybook through the repository tooling. Capture the mixed report and narrow-container stories. Inspect at normal and narrow main-content widths for clipping, wrapping, loading states, control guards, visual hierarchy, and user-facing copy. Store only invented public-safe data.

- [ ] **Step 6: Run focused security and final code review**

Review team scoping, facade ownership, replay allowlists, claim concurrency, raw evidence exclusion, and output size bounds. Route any code defect into the subagent-driven final-review fix wave, rerun its covering tests, then obtain one scoped re-review.

- [ ] **Step 7: Update verified status and commit final fixes**

Change the spec status to `Implemented and locally verified` only if all required checks and visual inspection passed. Commit any review fixes, screenshot story fixtures, and the status update with a conventional commit that describes the actual change.

- [ ] **Step 8: Regrade guided proactive PM capability**

Score evidence-backed performance across: problem discovery, prioritization context, action preparation, adoption tracking, outcome measurement, cross-run learning, safety, and user effort. Separate verified behavior, simulated integration behavior, and remaining production-validation gaps. Provide the screenshots and the grade before starting the PR stack.
