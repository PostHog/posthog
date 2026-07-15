---
name: adopting-shared-alerting
description: "How PostHog's shared alerting primitives work and how a product adopts them. Use when working on alert lifecycle transitions, notification destinations backed by HogFunctions, fixed-cadence scheduling, the shared AlertWizard, or when a product needs alerting behavior. Covers common/alerting, products/alerts/backend, product adapters, delivery rollback, and the single-mutator rule. Trigger terms: alert state machine, AlertPolicy, CheckInput, EventKindSpec, build_alert_destination_config, due alerts, alert destinations, AlertWizard."
---

# Adopting shared alerting

PostHog follows the Prometheus and Alertmanager split: evaluation stays product-specific, while lifecycle decisions, destination management, and reusable scheduling math are shared. A product supplies the domain verdict and event content. Shared code decides transitions and provides the delivery building blocks.

> [!IMPORTANT]
> There is no self-serve product registry or generic Temporal harness yet. Products still own their evaluator, persistence, due-alert query, check history, and orchestration. Adopt the shared pieces directly, following `products/logs` as the reference.

## Architecture

| Layer                | Location                                            | Responsibility                                                                                     |
| -------------------- | --------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Pure decision logic  | `common/alerting/`                                  | Lifecycle state machine and fixed-cadence scheduling math                                          |
| Shared alert product | `products/alerts/backend/`                          | Destination validation/configuration, HogFunction persistence, and internal-event delivery helpers |
| Product adapter      | `products/<name>/backend/`                          | Model translation, evaluation, due-alert eligibility, event payloads, and orchestration            |
| Shared frontend      | `frontend/src/lib/components/Alerting/AlertWizard/` | Reusable destination, trigger, and configuration flow for HogFunction-based alerts                 |

`common/alerting/` must remain pure Python with no Django or product imports. Django-aware destination code belongs to the alerts product, not the pure layer or a top-level PostHog package.

## Lifecycle state machine

`common/alerting/state_machine.py` contains pure functions over frozen dataclasses.

- `AlertState`: shared lifecycle states, including `FIRING`, `NOT_FIRING`, `SNOOZED`, `ERRORED`, and `BROKEN`. Map legacy persisted strings at the product adapter boundary.
- `AlertPolicy`: per-product behavior such as cooldown gating, re-notification, transient error handling, snooze semantics, and whether broken alerts are terminal or disabled.
- `CheckInput`: the normalized result of one product evaluation. `is_inconclusive=True` preserves state and the failure counter.
- `evaluate_alert_check(...)` and `evaluate_alert_failure(...)`: return an `AlertCheckOutcome`; they never mutate a model.
- `apply_user_reset`, `apply_enable`, `apply_disable`, `apply_snooze`, `apply_unsnooze`, and `apply_threshold_change`: pure control-plane transitions.

Error semantics are load-bearing:

- Failed checks do not clear a firing alert.
- Transient errors are silent and preserve the failure counter unless the policy opts into counting them.
- Error notification happens on the `0 -> 1` failure-counter edge unless the policy enables notification on every failure.
- A notification delivery failure must roll back the transition and must not advance the failure counter. Otherwise the next evaluation can miss the retry edge.

### Single-mutator rule

Every write to an alert model's `state` or `consecutive_failures` must pass through one product-owned adapter function, normally `apply_outcome`. CI enforces the logs implementation through `.semgrep/rules/security/alert-state-must-go-through-state-machine.yaml`. Extend that rule when another product adopts the machine.

Pattern from `products/logs/backend/alert_state_machine.py`:

```python
outcome = evaluate_alert_check(alert.to_snapshot(recent_events_breached=recent_breaches), check_result, now)
update_fields = apply_outcome(alert, outcome)
alert.save(update_fields=update_fields)
```

The product adapter owns model-to-snapshot translation and outcome-to-model mutation. Do not add product fields or persistence behavior to the shared machine.

## Destination configuration and persistence

The shared destination implementation lives in `products/alerts/backend/`.

### `destination_configs.py`

- `DestinationType`: Slack, Discord, webhook, and Microsoft Teams.
- `validate_destination_data(...)`: validates a product's allowed destination types and required fields.
- `EventKindSpec`: declares the content for one event kind. Use `details` for label/value rows, `intro_lines` for prose, and `additional_actions` for buttons after the required primary action.
- `build_alert_destination_config(...)`: builds one `AlertDestinationConfig` for one event kind and destination. The config carries its `team` beside the serializer payload so tenant context never enters request data.

Products should define a thin event-content module like `products/logs/backend/alert_destinations.py`. Keep event IDs, headers, webhook bodies, URLs, and allowed destination types there. Do not fork Slack, Teams, Discord, or webhook rendering.

### `destinations.py` and `facade/api.py`

Use `products.alerts.backend.facade.api` from product APIs for:

- `validate_destination_data`
- `build_alert_destination_config`
- `create_alert_destination_hog_functions`
- `soft_delete_alert_destinations`
- `soft_delete_all_alert_destinations`

Deletion is intentionally strict. Always pass `team_id`, `alert_id`, and the product's allowed event IDs. By-ID deletion also validates every HogFunction ID belongs to that alert before deleting anything.

Worker dispatch uses `produce_alert_internal_event`, `flush_alert_internal_events`, and `alert_internal_event_delivered` from `products.alerts.backend.destinations`. Kafka enqueue is not delivery. Flush and verify the produce result before persisting a transition that depends on notification delivery.

Discord support in the shared layer does not mean every product must expose Discord. The product's allowed destination types remain the public contract.

## Scheduling

`common/alerting/scheduling.py` shares fixed-minute cadence math:

- `compute_shard_offset_seconds(...)`: deterministically spreads alerts across scheduler ticks.
- `advance_next_check_at(...)`: advances and snaps `next_check_at` to the cadence grid.

Due-alert eligibility is product-specific. Logs keeps `due_alerts_q(...)` in `products/logs/backend/alert_utils.py` because enabled fields, state names, snooze fields, and tenancy constraints can differ. Reuse the math, but write and test the predicate against your product model.

Calendar scheduling for insight alerts, including local-time anchors, quiet hours, and weekend skipping, still lives under `posthog/tasks/alerts/`. Do not mix calendar and fixed-grid scheduling in one adopter.

## Shared AlertWizard

`frontend/src/lib/components/Alerting/AlertWizard/` provides the shared flow for event-triggered HogFunction alerts. It is separate from the backend lifecycle state machine.

Adopters provide `AlertWizardLogicProps`:

- A unique `logicKey`.
- Supported HogFunction `subTemplateIds`.
- Product-specific `WizardTrigger[]` and `WizardDestination[]` definitions.
- Optional URL-sync controls, preset trigger, preset health kinds, and creation callback.

Mount the keyed `alertWizardLogic` with `BindLogic`, then render `AlertWizard`. Keep the traditional HogFunction editor as the advanced fallback. Follow the health alerts and error tracking integrations for configuration and entry-point patterns.

The wizard only offers compatible destination/trigger pairs defined by HogFunction sub-templates. A destination appearing in backend shared code does not make it available in the wizard until the relevant sub-template supports it.

## Adoption checklist

1. Define the product's `AlertPolicy`; use defaults unless a documented semantic differs.
2. Add one product state adapter and route every lifecycle write through `apply_outcome`.
3. Define `EventKindSpec`s, allowed destination types, and the product's internal event properties.
4. Validate, create, and delete destinations through the alerts product facade.
5. Treat notification delivery and state persistence as one logical operation; roll back delivery-dependent outcomes on failure.
6. Reuse fixed-cadence math or keep the product's calendar model, then implement a product-specific due-alert query.
7. Keep evaluation, check history, model persistence, and Temporal orchestration in the product.
8. If the product uses HogFunction alerts in the UI, configure and mount the shared `AlertWizard` rather than copying it.
9. Extend the single-mutator semgrep rule and add focused tests at each product-owned boundary.

## Not available yet

- A shared alert configuration protocol or base model.
- A generic product registry and Temporal harness.
- Push-mode `submit_check(product, alert_id, CheckInput)` orchestration.
- Shared calendar scheduling primitives.

Until these exist, do not invent a parallel framework. Compose the landed primitives and keep product-specific behavior at the adapter boundary.
