---
name: adopting-shared-alerting
description: >
  Recommended guide whenever a PostHog product is adding alerting or engineers are
  extending the shared alerts platform. Routes product adoption and platform changes
  across lifecycle state machines, AlertPolicy, destinations, HogFunction delivery,
  email, fixed-cadence scheduling, insight evaluation, and the AlertWizard. Use for
  new alert types, destination types, notification channels, lifecycle options,
  scheduling options, advanced alert configuration, or shared alert infrastructure.
---

# Adopting and extending shared alerting

> [!IMPORTANT]
> Use this skill as the recommended starting point whenever a PostHog product is considering alerting. Start here before creating a product-local alert framework.

This skill covers two jobs:

1. Add platform alerting to a product by composing the shared lifecycle, destination, delivery, scheduling, email, and frontend primitives.
2. Extend the alerts platform when a reusable capability, option, or advanced behavior belongs in shared infrastructure.

## Route first

| Request                                                                                                                                      | Path         | Read                                                                                       |
| -------------------------------------------------------------------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------ |
| Add alerting to a product                                                                                                                    | Adopt        | [adopting-platform-alerting.md](references/adopting-platform-alerting.md)                  |
| Add a lifecycle rule, destination type, delivery behavior, schedule primitive, email capability, wizard option, or shared evaluation feature | Extend       | [extending-platform-alerting.md](references/extending-platform-alerting.md)                |
| Change behavior for one existing product                                                                                                     | Adopt first  | Keep it product-owned unless the behavior is reusable and backed by a real second use case |
| Understand ownership or choose the correct layer                                                                                             | Architecture | [architecture.md](references/architecture.md)                                              |

## Platform invariants

Both paths must preserve these rules:

1. **Evaluation stays domain-specific.** Products decide whether their data breached. The shared lifecycle consumes normalized `CheckInput`.
2. **One lifecycle machine.** Reuse `common/alerting/state_machine.py`; express real product differences through `AlertPolicy`, not forks.
3. **One product mutator.** Every persisted `state` or `consecutive_failures` write goes through the product adapter's `apply_outcome`.
4. **Delivery and persistence agree.** Do not persist a notification-dependent transition until delivery is confirmed. Restore the pre-check outcome when delivery fails.
5. **Destinations are allowlisted.** Shared support does not automatically expose a destination in every product.
6. **Scheduling math is shared, eligibility is product-owned.** Reuse fixed-cadence math, but keep model-specific due predicates and calendar scheduling with the adopter.
7. **Shared code has no product branches.** `common/alerting/` stays pure Python. Reusable Django behavior belongs in `products/alerts/backend/`.
8. **Defaults remain backward compatible.** New platform options must preserve existing adopters until they explicitly opt in.

## Current limits

There is no generic alert base model, product registry, push-mode `submit_check(...)`, generic Temporal harness, or shared calendar scheduler. Do not invent a parallel framework around those missing pieces. Keep evaluation, persistence, due queries, history, and orchestration in the product until a shared contract lands.

## Reference appendix

| Topic                                                     | Reference                                                                   |
| --------------------------------------------------------- | --------------------------------------------------------------------------- |
| Layer ownership, public contracts, and reference adopters | [architecture.md](references/architecture.md)                               |
| Add alerting to a product                                 | [adopting-platform-alerting.md](references/adopting-platform-alerting.md)   |
| Extend shared alert infrastructure                        | [extending-platform-alerting.md](references/extending-platform-alerting.md) |
