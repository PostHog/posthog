---
name: adding-product-alerting
description: >
  Recommended repo-engineering guide when adding alerting to a PostHog product or
  extending the shared alerts platform. Routes lifecycle state machines,
  AlertPolicy, destinations, HogFunction dispatch, email, fixed-cadence and calendar
  scheduling, insight evaluation, the AlertWizard, and shared alert editor components. Use for product alert implementations,
  shared destination types, lifecycle or scheduling options, advanced alert settings,
  and platform alert infrastructure. Not for configuring alerts in an existing product.
---

# Adding and extending product alerting

> [!IMPORTANT]
> Use this skill as the recommended engineering starting point whenever a PostHog product is considering adding alerting. Start here before creating a product-local alert framework.

This skill covers two jobs:

1. Add platform alerting to a product by composing the shared lifecycle, destination, delivery, scheduling, email, and frontend primitives.
2. Extend the alerts platform when a reusable capability, option, or advanced behavior belongs in shared infrastructure.

## Route first

| Request                                                                                                                                      | Path         | Read                                                                                       |
| -------------------------------------------------------------------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------ |
| Add alerting to a product                                                                                                                    | Adopt        | [adopting-platform-alerting.md](references/adopting-platform-alerting.md)                  |
| Build or extend a product alert editor, destination UI, advanced options, or evaluation history                                              | Frontend     | [frontend-alerting.md](references/frontend-alerting.md)                                    |
| Add a lifecycle rule, destination type, delivery behavior, schedule primitive, email capability, wizard option, or shared evaluation feature | Extend       | [extending-platform-alerting.md](references/extending-platform-alerting.md)                |
| Change behavior for one existing product                                                                                                     | Adopt first  | Keep it product-owned unless the behavior is reusable and backed by a real second use case |
| Understand ownership or choose the correct layer                                                                                             | Architecture | [architecture.md](references/architecture.md)                                              |
| Configure or author an existing logs or error tracking alert                                                                                 | Out of scope | Use `authoring-log-alerts` or `authoring-error-tracking-alerts`                            |
| Add real-time in-app notifications                                                                                                           | Out of scope | Use `sending-notifications`                                                                |

## Platform invariants

Both paths must preserve these rules:

1. **Evaluation stays domain-specific.** Products decide whether their data breached. The shared lifecycle consumes normalized `CheckInput`.
2. **One lifecycle machine.** Reuse `common/alerting/state_machine.py`; express real product differences through `AlertPolicy`, not forks.
3. **One product mutator.** Every persisted `state` or `consecutive_failures` write goes through the product adapter's `apply_outcome`.
4. **Dispatch and persistence agree.** For HogFunction notifications, do not persist a notification-dependent transition until the internal-event producer acknowledges the event. Restore the pre-check outcome when production fails. This acknowledgement does not confirm downstream destination execution.
5. **Destinations are allowlisted.** Shared support does not automatically expose a destination in every product.
6. **Scheduling math is shared, eligibility is product-owned.** Reuse fixed-cadence, calendar-anchor, timezone, and schedule-restriction helpers from `products/alerts/backend/scheduling.py`. Keep model-specific due predicates and persistence with the adopter.
7. **Shared code has no product branches.** `common/alerting/` stays pure Python. Reusable Django behavior belongs in `products/alerts/backend/`.
8. **Frontend data is normalized at the product boundary.** Shared editor components render normalized definitions, destinations, advanced options, schedules, and history. Product API calls, payloads, and evaluation-specific fields stay in the product adapter.
9. **Defaults remain backward compatible.** New platform options must preserve existing adopters until they explicitly opt in.

## Current limits

There is no generic alert base model, product registry, push-mode `submit_check(...)`, generic scheduler runner, or generic Temporal harness. Do not invent a parallel framework around those missing pieces. For non-insight products, keep evaluation, persistence, due queries, history, and orchestration in the product until a shared contract lands.

## Reference appendix

| Topic                                                     | Reference                                                                   |
| --------------------------------------------------------- | --------------------------------------------------------------------------- |
| Layer ownership, public contracts, and reference adopters | [architecture.md](references/architecture.md)                               |
| Add alerting to a product                                 | [adopting-platform-alerting.md](references/adopting-platform-alerting.md)   |
| Extend shared alert infrastructure                        | [extending-platform-alerting.md](references/extending-platform-alerting.md) |
| Build the product alert frontend                          | [frontend-alerting.md](references/frontend-alerting.md)                     |
