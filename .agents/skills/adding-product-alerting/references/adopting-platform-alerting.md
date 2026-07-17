# Add platform alerting to a product

Use this path when a product needs alerting. Compose the existing platform before adding shared abstractions.

## Contents

- [1. Define the product contract](#1-define-the-product-contract)
- [2. Add product persistence and isolation](#2-add-product-persistence-and-isolation)
- [3. Build the lifecycle adapter](#3-build-the-lifecycle-adapter)
- [4. Define notification content and destinations](#4-define-notification-content-and-destinations)
- [5. Make delivery transactional with lifecycle state](#5-make-delivery-transactional-with-lifecycle-state)
- [6. Add scheduling and due selection](#6-add-scheduling-and-due-selection)
- [7. Add product orchestration](#7-add-product-orchestration)
- [8. Add the frontend](#8-add-the-frontend)
- [9. Verify the boundaries](#9-verify-the-boundaries)

## 1. Define the product contract

Write down the product-specific inputs before coding:

- What data is evaluated and what constitutes breached, clear, inconclusive, transient error, and permanent error?
- Which lifecycle states and control-plane actions are user-visible?
- Is evaluation fixed-cadence or calendar-aligned?
- Which notification event kinds exist, such as firing, resolved, errored, or broken?
- Which destination types are allowed?
- Does the product need HogFunction delivery, email, or both?
- What fields belong in check history and detail pages?

Do not add a new `AlertPolicy` option merely because the product might need it. First confirm an existing policy cannot express the behavior and that the difference is intentional.

## 2. Add product persistence and isolation

The product owns its alert configuration and check-history models.

- Every tenant-data model needs `team_id` and fail-closed scoping.
- Store the fields required to construct `AlertSnapshot`, plus product evaluation and scheduling fields.
- Keep writes that must agree in a narrow `transaction.atomic()` block.
- Do not perform notification delivery inside the transaction.

Invoke `/django-migrations` for model changes.

## 3. Build the lifecycle adapter

Create one product state-machine module, following `products/logs/backend/alert_state_machine.py`.

1. Select or define the product's `AlertPolicy`.
2. Convert the model and recent history into the shared snapshot.
3. Convert the domain evaluation into `CheckInput`.
4. Call `evaluate_alert_check(...)` or `evaluate_alert_failure(...)`.
5. Apply every shared outcome through one product-owned `apply_outcome` function.
6. Route control-plane actions through the shared helpers and the same mutator.
7. Extend the alert-state semgrep rule to cover the product backend and exclude only its mutator and tests.

Do not mutate `state` or `consecutive_failures` elsewhere.

## 4. Define notification content and destinations

Create a thin product module like `products/logs/backend/alert_destinations.py`.

- Define one `EventKindSpec` per notification action.
- Keep event IDs and properties stable because HogFunctions filter and render from them.
- Include every template property in the internal event payload.
- Define the product's allowed `DestinationType` values explicitly.
- Validate, build, create, and delete destination HogFunctions through `products.alerts.backend.facade.api`.
- Scope deletion with the team, alert ID, and allowed event IDs.

Shared support for a destination does not opt the product into it.

## 5. Make delivery transactional with lifecycle state

For HogFunction destinations:

1. Evaluate alerts and retain each pre-check snapshot or outcome needed for rollback.
2. Produce internal events and retain each `ProduceResult`.
3. Flush once after producing the batch.
4. Check producer acknowledgement for each result with `alert_internal_event_delivered(...)`.
5. Restore delivery-dependent outcomes for unacknowledged results before persistence.
6. Persist acknowledged outcomes, check history, and product scheduling according to the product contract.

Producer acknowledgement does not confirm downstream HogFunction execution or final destination delivery. Logs is the reference for reevaluating on the next cadence after an internal event is not acknowledged.

For email, call `send_alert_email(...)` through the facade. The product must choose authorized recipients, a stable campaign key, subject, template, and context. Decide explicitly whether an email failure blocks a lifecycle transition or is recorded separately.

## 6. Add scheduling and due selection

Import the product-facing scheduling contract directly from its implementation module:

```python
from products.alerts.backend.scheduling import (
    CalendarInterval,
    advance_next_check_at,
    compute_shard_offset_seconds,
    is_utc_datetime_blocked,
    is_weekend,
    next_calendar_check_time,
    parse_blocked_windows_tuples,
    scan_next_unblocked_utc,
    to_calendar_interval,
    validate_and_normalize_schedule_restriction,
)
```

For fixed-minute checks:

- Reuse `compute_shard_offset_seconds(...)` and `advance_next_check_at(...)`.
- Wrap the shard function if the product scheduler interval differs from the shared default.
- Keep one stable shard calculation across create, update, and evaluation paths.
- Implement and test a product-specific due predicate with team scoping, enabled state, broken state, snooze state, and `next_check_at` behavior.

For calendar-aligned checks:

- Convert product interval values with `to_calendar_interval(...)`, then use `next_calendar_check_time(...)` with the team's IANA timezone.
- Validate stored quiet-hour payloads with `validate_and_normalize_schedule_restriction(...)` and parse them with `parse_blocked_windows_tuples(...)`.
- Use `scan_next_unblocked_utc(...)`, `is_utc_datetime_blocked(...)`, and `is_weekend(...)` instead of recreating timezone or DST logic.
- Keep model access, API error translation, bounded-retry logging, and `next_check_at` persistence in the product adapter.

## 7. Add product orchestration

The product owns its evaluator, history, due query, batching, Temporal or Celery orchestration, retries, and metrics.

Avoid large Temporal payloads. Pass alert IDs and references, then load data inside activities. Keep notification dispatch out of database transactions.

## 8. Add the frontend

Use the shared `AlertWizard` when the product creates HogFunction-backed alerts.

- Configure a unique `logicKey`.
- Supply supported sub-template IDs, triggers, and destinations.
- Add product-specific configuration outside the shared wizard when it is not a reusable HogFunction input.
- Keep the traditional HogFunction editor as the advanced fallback when the product already supports it.
- Ensure every network-backed action has loading and double-submit protection.

A product may skip `AlertWizard` if it has no HogFunction destinations.

## 9. Verify the boundaries

Add the lowest-level tests that cover real regressions:

- Shared state-machine decision cases used by the product.
- Product snapshot and single-mutator behavior.
- Destination validation, generated configs, ownership-safe deletion, and event property completeness.
- Delivery success, enqueue failure, flush failure, and rollback before save.
- Due predicate and cadence/shard behavior.
- API schemas and tenant isolation.
- Wizard logic and product entry points when frontend alert creation is added.

Invoke `/writing-tests` when adding or substantially changing tests. Also invoke `/improving-drf-endpoints` for serializer or viewset changes, `/adopting-generated-api-types` when frontend API types are involved, and `/writing-kea-logics` when adding or changing alert kea logic.
