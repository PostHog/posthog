# Billing alerts shared alerting refactor

## Purpose

This document is the implementation and review handoff for billing alerts PRs #66353 and #66355.

It records the verified current architecture, decisions already made, remaining product decision, implementation boundaries, parallel workstreams, test requirements, and branch plan.

Refresh live PR state and master before implementation. The repository source snapshot used for this investigation was master commit `510bb093d3299972c60714eca5f6c4c4466f5860` on 2026-07-16.

Implementation was rebased and revalidated against `origin/master` commit `d13a6fe198d4b694c270372a8d97fa90f6a54c5f` later on 2026-07-16.

## Local implementation status

The approved refactor is implemented locally and has not been pushed.

- Schema worktree: `/Users/will/.codex/worktrees/billing-alerts-schema/posthog`
- Schema branch: `codex/billing-alerts-schema-rebuild`
- Schema head: `154e9a10c70b9e37f184fda503b512c27fa42c24`
- Feature worktree: `/Users/will/.codex/worktrees/billing-alerts-feature/posthog`
- Feature branch: `codex/billing-alerts-feature-rebuild`
- Feature head: `c21f5c6105c22ff2033e95517923f929636b9ffa`
- The feature branch remains stacked on the schema branch so #66353 can stay migration-only and #66355 can stay the feature PR.
- The feature worktree has one deliberately uncommitted, newline-only Kea typegen artifact at `products/ai_observability/frontend/llmGenerationSentimentLazyLoaderLogicType.ts`. It is unrelated to billing alerts and must stay out of this stack.

Implemented changes:

- Rebuilt billing lifecycle evaluation and all control-plane transitions around `common.alerting.state_machine`.
- Replaced billing destination creation, deletion, and dispatch duplication with `products.alerts.backend` APIs.
- Added the Kafka delivery barrier, safe failed-delivery semantics, stale control-plane guards, and retry-safe due filtering.
- Kept the old Temporal notify activity as a locked compatibility path for in-flight branch histories.
- Replaced billing schedule advancement with `common.alerting.scheduling` while keeping billing's due query and Temporal workflow.
- Added project deletion re-homing with the approved code comment, destination cleanup, disablement, and final-team cleanup behavior.
- Restored shared AlertWizard, HogFunctionsList, and Node CDP consumer files to current master. Billing now owns its small presentation helpers.
- Added destination group summaries, duplicate-type protection, destination removal UI, and a Slack execution-project guard.
- Regenerated billing OpenAPI types and MCP types.

Validation completed on the rebased feature tree:

- 54 billing backend tests pass.
- Ruff check and format pass.
- Billing frontend Oxfmt and Oxlint pass.
- Filtered TypeScript output contains no `products/billing_alerts` errors after Kea type generation.
- OpenAPI schema, product API types, MCP types, MCP schemas, and MCP tools regenerate successfully.
- Tach validates the declared `products.alerts` and `products.cdp` boundaries.
- The schema migration analyzer reports safe with score 0; migration dry-run, generated SQL inspection, Ruff, formatting, and diff checks pass.

Known launch boundaries remain unchanged: shared email destinations, quiet hours, weekend skipping, and calendar schedules did not ship and are excluded from this PR stack.

## Guardrails

- Preserve PR #66353 as the migration-only precursor.
- Keep PR #66355 as the surviving feature PR.
- Keep the first release organization-wide.
- Use the shipped shared alerting implementation as the architectural source of truth.
- Adopt the shipped failure semantics: failed checks preserve the last successful firing state.
- Exclude email destinations, quiet hours, and weekend skipping from the first release.
- Use the creator's current project as the initial execution team. If that project is deleted, re-home the alert to another project in the organization, soft-delete its old destinations, and disable it until an admin reconnects destinations and re-enables it.
- Keep billing-specific evaluation, persistence, due-query rules, event history, and Temporal orchestration in `products/billing_alerts`.
- Do not push, close PRs, or alter remote branches until Will has reviewed and approved the implementation.
- When #66355 is eventually updated, ask in its PR description or reviewer notes whether project or country-level billing envelopes should be a follow-up.

## Verified PR state

### Shared alerting stack

| PR | Status | Shipped result |
| --- | --- | --- |
| #68936 | Merged | Pure lifecycle machine in `common/alerting/state_machine.py`, logs adapter, and the lifecycle single-mutator Semgrep rule. |
| #68937 | Merged | Destination configuration and persistence in `products/alerts/backend/`. |
| #68938 | Merged | Fixed-minute scheduling math in `common/alerting/scheduling.py`. Due queries and Temporal workflows remain product-owned. |
| #68939 | Merged | Existing HogFunction-first `AlertWizard` moved to `frontend/src/lib/components/Alerting/AlertWizard/`. |
| #68940 | Open draft | Updated adoption documentation only. It is useful context and is not a code dependency. |
| #68961 | Closed unmerged | Calendar scheduling, quiet hours, intervals, and weekend skipping are absent from master. |
| #70580 | Closed unmerged | Shared email destinations are absent from master. |

The original #67959, #67961, #67962, and #67963 were replaced by #68936 through #68939.

Original insight adoption PR #67964 closed without merging. Current insight alerts do not use the shared lifecycle machine.

### PR #66353

Current role: billing-alert product shell and schema.

- Open against `master`.
- Head branch: `will/billing-alerts-migration`.
- 6 commits at investigation time.
- Contains `BillingAlertConfiguration`, `BillingAlertEvent`, the initial migration, settings, product registration, and dependency declarations.
- No equivalent billing-alert model or migration exists on master.
- The shared platform intentionally has no generic alert configuration model or persistence layer.

Conclusion: keep #66353. Rebase or re-cut it onto current master while preserving its PR number.

### PR #66355

Current role: complete organization-scoped billing-alert feature.

- Open against `will/billing-alerts-migration`.
- Head branch: `will/billing-alerts-feature`.
- 6 feature commits at investigation time, plus the 6 commits inherited from #66353.
- Contains billing evaluation, lifecycle logic, scheduled checks, destinations, API, frontend, feature gating, and generated API/MCP artifacts.
- The feature branch predates the final locations and API shapes shipped by #68936 through #68939.

Conclusion: rebuild #66355 around the shipped shared primitives while preserving its billing-specific evaluator, persistence, orchestration, API, and UI.

## Shipped architecture and boundaries

### Pure lifecycle

Location: `common/alerting/state_machine.py`

Use:

- `AlertState`
- `NotificationAction`
- `AlertPolicy`
- `AlertSnapshot`
- `CheckInput`
- `AlertCheckOutcome`
- `ControlPlaneOutcome`
- `evaluate_alert_check`
- `evaluate_alert_failure`
- `apply_user_reset`
- `apply_enable`
- `apply_disable`
- `apply_snooze`
- `apply_unsnooze`
- `apply_threshold_change`

The shared functions are pure. They do not import Django or mutate product models.

The current shared error contract is binding for this refactor:

- A failed check preserves an existing firing episode.
- Error health is represented by `consecutive_failures` and error events.
- The alert reaches `BROKEN` at the configured failure threshold.
- A delivery failure must preserve the prior state and must not advance the failure counter.

### Shared destination product

Locations:

- `products/alerts/backend/destination_configs.py`
- `products/alerts/backend/destinations.py`
- `products/alerts/backend/facade/api.py`

Product API code should import configuration and persistence operations through the facade:

- `validate_destination_data`
- `build_alert_destination_config`
- `create_alert_destination_hog_functions`
- `soft_delete_alert_destinations`
- `soft_delete_all_alert_destinations`

Worker code should import delivery operations directly from `products.alerts.backend.destinations`:

- `produce_alert_internal_event`
- `flush_alert_internal_events`
- `alert_internal_event_delivered`

The shipped destination types are Slack, Discord, webhook, and Microsoft Teams. Billing will expose Slack, webhook, and Microsoft Teams for the first release.

Deletion requires `team_id`, `alert_id`, and billing's complete allowed event-ID set.

### Fixed-cadence scheduling

Location: `common/alerting/scheduling.py`

Use:

- `compute_shard_offset_seconds`
- `advance_next_check_at`

Billing owns its due-alert query and Temporal orchestration.

Convert `check_interval_hours` to minutes and use `schedule_interval_seconds=3600` for deterministic sharding across the hourly sweep.

### Shared frontend

Location: `frontend/src/lib/components/Alerting/AlertWizard/`

The current wizard creates one HogFunction directly through `api.hogFunctions.create()` and invokes `onAlertCreated` afterward.

Billing creation requires one `BillingAlertConfiguration` plus HogFunctions for four lifecycle event kinds. Keep `BillingAlertWizard` product-owned. Remove branch changes to the shared AlertWizard and `HogFunctionsList`.

The branch's `AlertingChoiceCard`, `AlertingListToolbar`, `AlertingTable`, and `AlertingWizardLayout` components did not ship. Keep any small presentation helpers inside the billing product unless a separate shared frontend extraction is approved.

## Billing-specific adapter

### Lifecycle adapter

Create or reshape `products/billing_alerts/backend/alert_state_machine.py` as the only billing lifecycle adapter.

Responsibilities:

- Define the billing `AlertPolicy` locally.
- Translate `BillingAlertConfiguration` into shared `AlertSnapshot`.
- Translate billing evaluation results into `CheckInput`.
- Call the shared lifecycle functions.
- Map `NotificationAction` to `BillingAlertEvent.Kind`.
- Expose one `apply_outcome()` function as the only mutator of `state` and `consecutive_failures`.
- Apply `outcome.disable` to `enabled`.
- Route serializer and API control-plane changes through the shared `apply_*` functions.
- Extend `.semgrep/rules/security/alert-state-must-go-through-state-machine.yaml` to billing paths.

Billing policy:

```python
AlertPolicy(
    broken_is_terminal=False,
    transient_errors_count_toward_broken=True,
    notify_error_on_every_failure=True,
    cooldown_gates_initial_fire=False,
    cooldown_gates_resolve=False,
    renotify_while_firing=True,
    clear_check_ends_snooze=True,
    disable_when_broken=True,
)
```

Keep `ERRORED` readable as a persisted legacy value. New failed checks should preserve the prior successful configuration state and create `BillingAlertEvent.Kind.ERRORED` events.

### Evaluation adapter

Keep the existing billing evaluator behavior:

- Organization-wide spend or usage totals.
- Relative increase, absolute value, and absolute increase thresholds.
- Minimum-value guard.
- Baseline window.
- Evaluation delay.
- Inconclusive results for missing current or baseline data.
- Query grouping by organization, metric, baseline window, and evaluation delay.

Project, country, product, and usage-category filters are outside the first-release scope.

### Destination adapter

Keep billing-owned definitions for:

- Internal event IDs.
- `EventKindSpec` content.
- Billing properties and links.
- Allowed public destination types.
- Allowed event IDs.
- Product-local destination-type listing for API responses.

Delete duplicated validation, rendering, creation, deletion, and dispatch implementations.

Remove `billing_alert_destination_ids` and the billing-specific Node CDP consumer path. Shared HogFunctions already select notifications by event ID and `alert_id`.

### Scheduling adapter

Keep a product-local `due_billing_alerts_q()` with the existing eligibility contract:

- Alert is enabled.
- `next_check_at` is due or null.
- State is not `BROKEN`.
- `snooze_until` is null or expired.
- Oldest due alerts are selected first, with nulls first.
- A sweep selects at most 500 alerts.

Use shared advancement and sharding for `next_check_at`.

### Temporal orchestration

Preserve these identifiers:

- Schedule ID: `schedule-due-billing-alert-checks-schedule`
- Sweep workflow: `schedule-due-billing-alert-checks`
- Batch workflow: `check-billing-alert-batch`
- Existing activity names and input types where possible.
- Existing batch size of 50.

Refactor the evaluation activity into the same logical phases used by logs alerting:

1. Fetch and group billing data.
2. Evaluate each alert.
3. Compute the shared outcome.
4. Produce any notification event.
5. Flush and verify Kafka delivery.
6. Replace delivery-dependent outcomes with their safe committed outcome when delivery fails.
7. Persist lifecycle fields, history, schedule fields, and `last_notified_at`.

For new executions, the evaluation activity can finish delivery and return no event IDs. Retain `notify_billing_alert_events_activity` temporarily as an idempotent compatibility path for branch-created workflow histories that return event IDs.

The synchronous `check_now` endpoint must call the same per-alert evaluation, delivery, and persistence pipeline.

## Execution-team decision

### Why an execution team exists

A billing alert evaluates organization-wide billing data. Its Slack, webhook, and Microsoft Teams destinations are HogFunctions, and every HogFunction belongs to one PostHog project. Internal events also require a project `team_id`.

`BillingAlertConfiguration.team` is therefore infrastructure ownership for destinations and event delivery. It does not limit which organization's billing data is evaluated.

### Current branch behavior

On creation, the branch:

1. Uses the creator's current project when it belongs to the organization.
2. Falls back to the organization's lowest-ID project.
3. Exposes `execution_team_id` as read-only, so the user never chooses it.

The FK uses `on_delete=models.CASCADE` and `db_constraint=False`.

Deleting the selected project through normal Django deletion can delete the alert. A direct database deletion has no FK constraint to enforce cleanup. Either result is surprising for an organization-wide alert.

### Accepted behavior

Will approved re-homing and disabling the alert when its execution project is deleted.

Implementation contract:

- Use the creator's current project when it belongs to the organization.
- Fall back to the organization's lowest-ID project at creation.
- When that project is deleted, choose another project in the organization, soft-delete the old destinations, reassign the alert, and disable it.
- Preserve configuration and history.
- Require an admin to recreate destinations and re-enable the alert.
- If no replacement project exists because the organization itself is being deleted, allow the normal organization-deletion cleanup path to remove the alert.
- Add deterministic tests for re-homing, destination cleanup, disablement, and organization deletion.

### Required code comment

Place a short comment beside the project-deletion handler. The comment must explain the scope mismatch and why destinations are removed instead of moved.

Use this wording unless the final code structure makes a small adjustment clearer:

```python
# Billing alerts evaluate organization-wide data, but HogFunction destinations are team-scoped.
# Re-home and disable the alert here because team-specific integrations cannot be moved safely.
```

Keep the comment beside the behavior it protects. Do not put change history, PR numbers, or agent context in the code comment.

## Delivery and persistence rules

A transition that requires notification is committed only after Kafka acknowledges the internal event.

On failed delivery:

- Preserve the prior lifecycle state.
- Do not advance the failure counter.
- Do not update `last_notified_at`.
- Do not disable a BROKEN alert.
- Let the next scheduled evaluation retry the lifecycle edge.

For failed FIRE or RESOLVE delivery, avoid writing a transition event that claims the transition committed.

For an evaluation error, retain error audit evidence with the committed state. Keep the failure counter at its safe pre-delivery value so the notification edge remains retryable.

## Migration plan for #66353

1. Refresh from current master while preserving the PR number.
2. Run the repository's Django migration skill before changing the migration.
3. Refresh the migration dependency.
4. Reconcile model code and migration state.
5. Resolve the execution-team deletion behavior.
6. Verify indexes, conditional constraints, and `db_constraint=False` behavior.
7. Run migration generation, SQL inspection, fresh migration, and migration-risk checks.
8. Merge and allow the migration to deploy before merging #66355.

## Feature plan for #66355

1. Rebase or rebuild on the refreshed #66353.
2. Remove stale shared paths, Node destination targeting, shared frontend refactors, and generated churn.
3. Add lifecycle contract tests and the billing adapter.
4. Route control-plane changes through the shared lifecycle helpers.
5. Adopt shared destination configuration and persistence.
6. Move dispatch and Kafka acknowledgement ahead of delivery-dependent persistence.
7. Adopt shared fixed-cadence scheduling math.
8. Preserve Temporal workflow compatibility.
9. Restore the billing API and product-owned frontend.
10. Regenerate OpenAPI, frontend types, MCP artifacts, and snapshots.
11. Run backend, Temporal, frontend, lint, type, generated-code, and Visual Review checks.
12. Present the completed local diff to Will for review before pushing.

## Parallel implementation workstreams

These workstreams can proceed in parallel after the execution-team decision is recorded and #66353 has a refreshed base.

### Workstream A: Schema and model contract

Primary files:

- `products/billing_alerts/backend/models.py`
- `products/billing_alerts/backend/migrations/0001_initial.py`
- Product registration and dependency files.

Deliverables:

- Refreshed migration dependency.
- Approved execution-team re-home and disable contract.
- Matching migration and model state.
- Migration tests and risk checks.

### Workstream B: Lifecycle and evaluator

Primary files:

- Billing lifecycle adapter.
- Billing evaluator integration.
- Lifecycle and evaluator tests.
- Semgrep rule.

Deliverables:

- Billing policy contract.
- Shared `CheckInput` and `AlertCheckOutcome` flow.
- Single legal lifecycle mutator.
- Control-plane transitions.

### Workstream C: Destinations and delivery

Primary files:

- Billing destination event specifications.
- Billing facade destination methods.
- Billing notification or dispatch code.
- Node CDP consumer cleanup.
- Destination and delivery tests.

Deliverables:

- Shared destination creation and deletion.
- Shared Kafka production, flush, and acknowledgement.
- Delivery-safe lifecycle persistence contract.

### Workstream D: Scheduling and Temporal

Primary files:

- Billing Temporal activities.
- Billing Temporal workflows.
- Billing schedule registration.
- Temporal and scheduling tests.

Deliverables:

- Product-local due query.
- Shared cadence advancement and hourly sharding.
- Preserved workflow identifiers.
- Compatibility path for old event-ID activity results.

### Workstream E: API and frontend

Primary files:

- Billing serializers and views.
- Billing product frontend.
- Generated OpenAPI, TypeScript, and MCP artifacts after backend contracts stabilize.

Deliverables:

- Organization-wide billing alert UX.
- Product-owned wizard.
- Correct destination and lifecycle API shapes.
- Loading guards, generated types, and Visual Review updates.

### Integration ownership

One integration owner should resolve shared files and final sequencing:

- `products/billing_alerts/backend/facade/api.py`
- `products/billing_alerts/backend/models.py`
- Temporal activity result contracts.
- Generated artifacts.
- `tach.toml`, product registration, and frontend constants.

Agents should avoid editing generated artifacts until backend API contracts are stable.

## Required tests

### Lifecycle

- Parameterize every non-default billing policy flag.
- Initial firing, continued firing, cooldown re-notification, and resolution.
- Snooze, manual check during snooze, and snooze expiry.
- Inconclusive evaluation preserves state and failures.
- Transient and permanent failures both count for billing.
- A failure preserves an existing firing state.
- BROKEN after five failures.
- Auto-disable occurs only when the BROKEN notification is delivered.
- Delivery failure preserves state and the failure-counter retry edge.
- Enable, disable, threshold change, snooze, unsnooze, and reset use `apply_outcome`.
- Semgrep rejects direct billing state and failure-counter writes.

### Evaluator

- Spend and usage metrics.
- Relative increase, absolute value, and absolute increase.
- Minimum-value guard.
- Baseline and evaluation-delay windows.
- Missing current or baseline data.
- Grouped billing requests.
- Organization isolation.

### Destinations

- Slack, webhook, and Microsoft Teams for all four event kinds.
- Required fields and rejected types.
- Cross-alert and cross-team deletion rejection.
- Atomic destination creation.
- Worker reload after transaction commit.
- Delete one and delete all.
- Kafka enqueue, flush, and acknowledgement failures.
- Idempotent compatibility retries.
- No-destination behavior.
- Absence of the billing-specific Node targeting property.

### Scheduling and Temporal

- Hours-to-minutes conversion.
- Hourly sharding.
- Canonical cadence advancement and missed-cycle catch-up.
- Due, null, future, disabled, broken, and snoozed rows.
- 500-alert sweep cap and 50-alert child batches.
- Existing workflow and activity identifiers.
- Replay of histories that contain event-ID results.
- Manual `check_now` uses the same commit rules.

### API and frontend

- Organization owner and admin permissions.
- Cross-organization isolation.
- Execution-team creation and deletion behavior.
- Wizard validation and destination creation.
- Double-submission guards.
- List actions, state badges, history, and feature gate.
- Generated OpenAPI and frontend types.
- Visual Review changes.

### Migration

- `makemigrations --check`.
- `sqlmigrate` inspection.
- Migration-risk analysis against current master.
- Fresh install and migrate-forward.
- Model-to-migration state comparison.
- Index and conditional-constraint verification.

## Main risks

- Any development or preview database that already applied an earlier form of billing alert migration `0001_initial` must be reset or audited before using the rebuilt branch. Production has never applied it.
- `db_constraint=False` leaves execution-team cleanup to the approved application-level re-home and disable handler.
- Temporal workflow histories can outlive a deploy.
- Kafka enqueue is buffered and requires flush plus delivery verification.
- Delivery remains at least once across process death after Kafka acknowledgement and before the database commit. Lifecycle state remains safe, but a notification can be duplicated in that narrow crash window.
- Shared error semantics change the branch's visible configuration state after failures.
- Canonical scheduling changes timing relative to alert creation.
- Generated artifacts will conflict if produced before API contracts settle.
- The evaluator remains organization-wide and does not satisfy project or country-level envelopes.

## Final branch structure

1. #66353 remains the migration-only precursor.
2. #66355 remains the feature PR stacked on #66353.
3. Shared email destination support belongs in a separate platform PR.
4. Calendar scheduling belongs in a separate follow-up if it becomes a product requirement.

## Future #66355 PR question

Include this question when the branch is eventually pushed after Will's approval:

> This first release evaluates billing alerts across the whole organization. Should project, country, product, or usage-category envelopes be handled in a focused follow-up?

## Sources

- https://github.com/PostHog/posthog/pull/66353
- https://github.com/PostHog/posthog/pull/66355
- https://github.com/PostHog/posthog/pull/68936
- https://github.com/PostHog/posthog/pull/68937
- https://github.com/PostHog/posthog/pull/68938
- https://github.com/PostHog/posthog/pull/68939
- https://github.com/PostHog/posthog/pull/68940
- https://github.com/PostHog/posthog/blob/510bb093d3299972c60714eca5f6c4c4466f5860/common/alerting/state_machine.py
- https://github.com/PostHog/posthog/blob/510bb093d3299972c60714eca5f6c4c4466f5860/common/alerting/scheduling.py
- https://github.com/PostHog/posthog/blob/510bb093d3299972c60714eca5f6c4c4466f5860/products/alerts/backend/destination_configs.py
- https://github.com/PostHog/posthog/blob/510bb093d3299972c60714eca5f6c4c4466f5860/products/alerts/backend/destinations.py
- https://github.com/PostHog/posthog/blob/510bb093d3299972c60714eca5f6c4c4466f5860/products/logs/backend/alert_state_machine.py
- https://github.com/PostHog/posthog/blob/510bb093d3299972c60714eca5f6c4c4466f5860/frontend/src/lib/components/Alerting/AlertWizard/alertWizardLogic.ts
