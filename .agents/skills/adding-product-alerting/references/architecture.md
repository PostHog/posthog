# Shared alerting architecture

Use this reference to decide where code belongs before editing it.

## Layer map

| Layer                              | Location                                                     | Owns                                                                                                                                  |
| ---------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| Pure lifecycle and cadence math    | `common/alerting/`                                           | State transitions, policy decisions, notification actions, fixed-minute cadence and sharding                                          |
| Shared Django alert infrastructure | `products/alerts/backend/`                                   | Destination configuration and persistence, internal-event delivery, email transport, insight alert models/API, and insight evaluation |
| Product adapter                    | `products/<name>/backend/`                                   | Domain evaluation, model snapshots, the single mutator, event payloads, allowed destinations, due queries, history, and orchestration |
| Shared alert creation UI           | `frontend/src/lib/components/Alerting/AlertWizard/`          | Reusable HogFunction destination, trigger, and configuration flow                                                                     |
| Product UI                         | `products/<name>/frontend/` or `frontend/src/scenes/<name>/` | Alert settings, product-specific fields, entry points, detail pages, and wizard configuration                                         |

`products/logs` is the reference adopter for the shared lifecycle, fixed-cadence scheduling, HogFunction destinations, delivery rollback, and product-owned Temporal orchestration.

Insight alerts are the reference for email delivery and calendar scheduling. Their model, API, and query evaluation live in `products/alerts/backend/` and `posthog/tasks/alerts/`. The evaluation package is shared across insight query kinds, but it is not a generic evaluator for unrelated products.

## Lifecycle contract

`common/alerting/state_machine.py` is pure Python.

- `CheckInput` normalizes one product evaluation.
- `AlertSnapshot` contains only fields needed for lifecycle decisions.
- `AlertPolicy` represents deliberate differences between adopters. Its defaults are existing behavior, not a menu of speculative options.
- `evaluate_alert_check(...)` and `evaluate_alert_failure(...)` return `AlertCheckOutcome` without persistence.
- Control-plane helpers such as `apply_enable`, `apply_disable`, `apply_snooze`, and `apply_threshold_change` return `ControlPlaneOutcome`.
- `NotificationAction` tells the product which event to deliver.

The product converts its model to a snapshot and applies the outcome through one local `apply_outcome` function. Extend `.semgrep/rules/security/alert-state-must-go-through-state-machine.yaml` when another product adopts this contract.

Error behavior is load-bearing:

- Failed checks do not clear an already firing alert.
- Inconclusive checks preserve state and failure count.
- Transient errors are silent unless the policy opts into counting them.
- Error notification normally occurs on the first failure edge.
- Delivery failure must not consume a lifecycle or failure-counter edge that should be retried.

## Destination contract

Product-facing destination setup is exported from `products.alerts.backend.facade.api`:

- `validate_destination_data`
- `build_alert_destination_config`
- `create_alert_destination_hog_functions`
- `soft_delete_alert_destinations`
- `soft_delete_all_alert_destinations`
- `send_alert_email`

`EventKindSpec` describes destination-neutral content for one event kind. The shared builder converts it into Slack, Discord, webhook, or Microsoft Teams HogFunction payloads. Products own event IDs, event properties, wording, actions, and their allowed destination list.

Deletion is fail-closed. Always scope it with `team_id`, `alert_id`, and the product's allowed event IDs.

## Delivery contract

HogFunction notification workers use `products.alerts.backend.destinations` directly:

1. `produce_alert_internal_event(...)` returns a `ProduceResult` or `None`.
2. `flush_alert_internal_events(...)` flushes the shared producer. Batch workers should flush once per produced batch.
3. `alert_internal_event_delivered(...)` checks whether the producer acknowledged each internal event after the flush.
4. The product persists notification-dependent lifecycle changes only for acknowledged internal events.

This acknowledgement confirms production to the internal-event transport, not downstream HogFunction execution or final Slack, Discord, webhook, or Microsoft Teams delivery. The helpers log and capture producer failures. The product owns rollback, retry timing, schedule advancement, and check-history semantics.

Email callers use `send_alert_email(...)` through the facade. The caller owns recipients, authorization, subject, template, context, error handling, and a stable `campaign_key` for the required retry and deduplication behavior.

## Scheduling contract

`common/alerting/scheduling.py` supports fixed-minute cadences:

- `compute_shard_offset_seconds(...)` deterministically assigns a UUID-keyed alert to scheduler ticks.
- `advance_next_check_at(...)` advances from the prior schedule, skips missed intervals, snaps to the midnight-anchored cadence grid, and applies the shard offset.

Use the scheduler's real interval when computing shards. Use the same shard function when creating, updating, and advancing an alert.

Due eligibility stays product-specific because model fields, states, snooze behavior, and tenant constraints differ. Calendar behavior such as team-local anchors, schedule restrictions, and weekend skipping remains separate from fixed-grid scheduling.

## Frontend contract

`AlertWizard` is a shared HogFunction creation flow, not a lifecycle engine.

Adopters provide keyed `alertWizardLogic` props with supported sub-template IDs, `WizardTrigger[]`, `WizardDestination[]`, and optional URL/preset behavior. Compatibility comes from HogFunction sub-templates. Backend destination support alone does not make an option available in the wizard.

Keep product business logic in kea. Follow `frontend/src/AGENTS.md`, use generated API types, and guard network submissions from double clicks.
