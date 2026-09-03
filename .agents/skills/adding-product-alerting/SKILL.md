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
2. **One lifecycle machine.** Reuse `products/alerts/backend/state_machine.py`; express real product differences through `AlertPolicy`, not forks.
3. **One product mutator.** Every persisted `state` or `consecutive_failures` write goes through the product adapter's `apply_outcome`.
4. **Dispatch and persistence agree.** For HogFunction notifications, do not persist a notification-dependent transition until the internal-event producer acknowledges the event. Restore the pre-check outcome when production fails. This acknowledgement does not confirm downstream destination execution.
5. **Destinations are allowlisted.** Shared support does not automatically expose a destination in every product.
6. **Scheduling math is shared, eligibility is product-owned.** Reuse fixed-cadence, calendar-anchor, timezone, and schedule-restriction helpers from `products/alerts/backend/scheduling.py`. Keep model-specific due predicates and persistence with the adopter.
7. **Shared code has no product branches.** The lifecycle module stays pure Python. Reusable Django behavior belongs elsewhere in `products/alerts/backend/`.
8. **Frontend data is normalized at the product boundary.** Shared editor components render normalized definitions, destinations, advanced options, schedules, and history. Product API calls, payloads, and evaluation-specific fields stay in the product adapter.
9. **Defaults remain backward compatible.** New platform options must preserve existing adopters until they explicitly opt in.
10. **Configuration, routing, and delivery are one contract.** A supported destination must persist, remain visible, be selected when its alert fires, and reach its delivery worker. Do not test only one of these steps.

## Review shared changes as one alert system

When a change touches shared alerting, review every contract that can consume it, not only the product that motivated
the change. Start with the reference adopters and inspect the affected dimensions:

- **Lifecycle:** product adapters, control-plane actions, persisted state, and notification edges.
- **Delivery and destinations:** event producers and consumers, acknowledgement and rollback behavior, templates, and
  product and generic management APIs.
- **Scheduling:** create and update paths, due eligibility, retries, cadence, quiet hours, and timezone behavior.
- **Authorization:** product, project, and organization boundaries at destination creation, management, and dispatch.
- **Frontend and API contracts:** generated clients, pending-destination retries, existing-destination visibility, and
  every UI that uses the shared data.
- **Classification and eligibility:** every producer and consumer that classifies an event, template, destination, or
  alert type. A new restriction can block creation in one path and delivery in another.

For event, destination, query, or authorization changes, map all matching products and clients by exact event IDs,
template IDs, model types, generic APIs, UIs, and regex or prefix matches. A new product can own its destination
lifecycle while another product still intentionally uses a generic HogFunction path.

When generic access violates an ownership or authorization boundary, restrict it immediately. Preserve generic access
only for explicitly safe, supported paths, and migrate those paths to product-owned APIs deliberately. Add
public-interface tests for the new ownership boundary and every existing path that remains supported.

## Treat alerting as an end-to-end system

Alerting crosses several boundaries. A destination can be valid in the UI, rejected by an API, saved but hidden, or
saved and never invoked. A unit test at one boundary does not prove the next boundary works.

For each supported alert source and destination type, test this path through public interfaces:

1. Create or update the destination through every supported management API.
2. Read the alert back and confirm the destination is visible.
3. Trigger the alert and confirm routing selects the destination.
4. Confirm the delivery worker accepts the notification or records a clear failure.

Use a test transport or a mock external endpoint for the final step. Do not depend on a real customer destination.
Add a focused test whenever a shared filter, allowlist, event ID, template ID, or ownership rule changes.

Keep one explicit compatibility matrix for supported source, event, destination, and management-path combinations. A
single source of truth should drive related allowlists where practical. If separate allowlists are required, name the
supported combinations and test them. Never treat an empty match as success without recording why it was empty.

Instrument the lifecycle at each boundary: configuration accepted or rejected, destination selected, event produced,
worker matched, delivery attempted, and delivery outcome. Include a correlation ID and stable source and destination
dimensions. Alert on a sustained mismatch between adjacent stages. This finds silent drops even when individual
components report no errors.

Run isolated synthetic checks for high-value supported paths after deployment and at a regular interval. A synthetic
check must prove the whole path, not only that a producer accepted an event.

## Current limits

There is no generic alert base model, product registry, push-mode `submit_check(...)`, generic scheduler runner, or generic Temporal harness. Do not invent a parallel framework around those missing pieces. For non-insight products, keep evaluation, persistence, due queries, history, and orchestration in the product until a shared contract lands.

## Reference appendix

| Topic                                                     | Reference                                                                   |
| --------------------------------------------------------- | --------------------------------------------------------------------------- |
| Layer ownership, public contracts, and reference adopters | [architecture.md](references/architecture.md)                               |
| Add alerting to a product                                 | [adopting-platform-alerting.md](references/adopting-platform-alerting.md)   |
| Extend shared alert infrastructure                        | [extending-platform-alerting.md](references/extending-platform-alerting.md) |
| Build the product alert frontend                          | [frontend-alerting.md](references/frontend-alerting.md)                     |
