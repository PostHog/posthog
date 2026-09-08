# AI query plan visibility

## Summary

AI prompt subscriptions reuse a query plan after a delivery produces a plan that is safe to reuse.
The product currently exposes the executed queries in delivery history, but it does not show whether the subscription will reuse them on its next delivery.

Add a compact, read-only query plan status to AI prompt subscription details.
The status uses an icon and tooltip to explain whether the plan is frozen, absent, or due to regenerate because the query planner changed.
This makes the stability boundary visible without asking users to manage planner versions or query lifecycle.

## Implementation notes

This document is the design as it stood before implementation.
The shipped code diverges in the places below, so read the rest of this document as design history rather than as instructions.

- Placement: the status appears in delivery history beside the `Queries` label. It is not a `Query plan` item in `SubscriptionSummary`, as `User interface` describes.
- Persistence: each AI delivery records its own status in that delivery's `content_snapshot`, and the delivery serializer reads it back. That makes the per-delivery provenance entries in `Non-goals` and `Scope ceiling` out of date.
- Meaning of `planner_updated`: in delivery history it means that delivery already regenerated and froze a plan. The `API design` and `User interface` tables give it a pending sense, which still matches the subscription-level field.
- Icons: implementation reversed the pin guidance in `User interface`. The delivery indicator uses a snowflake for `frozen` and a crossed-out snowflake for `not_frozen`.
- API surface: the derived subscription-level field described here still exists. Implementation added a second, per-delivery field on the delivery serializer, which this document does not describe.

## Goals

- Show whether an AI prompt subscription currently has a valid frozen query plan.
- Explain that frozen query definitions are reused while date ranges, results, and report text still change.
- Show when a stored plan is stale because PostHog updated the query planner.
- Keep planner upgrades automatic.
- Keep the presentation compact and accessible.

## Non-goals

- Freeze or unfreeze controls.
- Per-query frozen states.
- Planner version selection or pinning.
- A persistent update banner or notification.
- A second query viewer that duplicates delivery history.
- Historical plan provenance for each delivery.
- Persisting why a plan is absent after a prompt edit or failed generation.

## Current behavior

`Subscription.ai_query_plan` stores a versioned query plan after a freshly generated plan completes without query or chart failures and every query contains a runtime window placeholder.
Later deliveries reuse that plan without invoking the event selector or planner.

Editing the subscription prompt clears `ai_query_plan`.
A stored plan whose version differs from `AI_QUERY_PLAN_VERSION` is rejected during the next delivery, replanned automatically, and replaced after the new plan succeeds.

`AI_QUERY_PLAN_VERSION` is the explicit compatibility revision for reusable plans.
The status mirrors that runtime invalidation boundary; it does not claim to track every revision of an internally managed LLM prompt.
Managed prompt changes that must invalidate stored plans still require an `AI_QUERY_PLAN_VERSION` bump, as they do today.

Each completed AI delivery already snapshots the prompt, executed HogQL, and per-query outcome for delivery history.
Those diagnostics use concrete date bounds, so they are evidence of what ran rather than a direct representation of the reusable plan template.

## API design

Add a read-only nullable `ai_query_plan_status` field to `SubscriptionSerializer`.
Define its values once in a module-level Django `TextChoices` class and reuse those choices in the serializer schema so generated enum names remain stable and collision-checkable.
The field is `null` for insight and dashboard subscriptions and has one of these values for AI prompt subscriptions:

| Value             | Meaning                                                                                                                                   |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `frozen`          | The stored envelope uses `AI_QUERY_PLAN_VERSION` and contains a valid `QueryPlan`. The next delivery can reuse it.                        |
| `not_frozen`      | No reusable plan is available. This includes a new subscription, a prompt edit, a failed plan, and malformed stored data.                 |
| `planner_updated` | A versioned stored plan exists, but its version differs from `AI_QUERY_PLAN_VERSION`. The next delivery will regenerate it automatically. |

The serializer derives the status at read time.
It does not expose the plan, generated HogQL, planner prompt, or model metadata.
Knowing the lifecycle status does not reveal query-derived project data, so the field can follow the parent subscription's existing read permissions.

The derivation and runtime must use one shared stored-plan validator so `frozen` never promises reuse for a plan the runtime would reject.
The validator accepts only an object envelope with a real integer version, excluding booleans, a valid `QueryPlan`, and valid stored relevant-event data.
The frozen execution path must use the same validator and convert every malformed envelope into `StoredPlanInvalidError`, preserving automatic replanning rather than turning corrupt JSON into a delivery failure.

Classify a well-formed integer version mismatch as `planner_updated` before validating the old plan body because an older plan can legitimately use an older schema.
A missing, boolean, non-integer, or malformed version is `not_frozen`.
For a current version, any invalid plan or relevant-event data is also `not_frozen`.

Regenerate OpenAPI and generated frontend contracts after adding the serializer field.

## User interface

Show a `Query plan` item in `SubscriptionSummary` only when `resource_type` is `ai_prompt`.
Its value is a focusable status icon wrapped in a tooltip:

| Status            | Icon              | Tooltip                                                                                                                                                                                                                                          |
| ----------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `frozen`          | Filled pin        | **Frozen query plan.** PostHog will reuse these query definitions for each delivery. Date ranges, results, and the written report will still update. PostHog generates a new plan when you edit the prompt or when the query planner is updated. |
| `not_frozen`      | Muted outline pin | **Query plan not frozen.** No reusable plan is available yet. PostHog will freeze the plan when it can be safely reused.                                                                                                                         |
| `planner_updated` | Refresh           | **Query plan will be regenerated.** The query planner changed. The next successful delivery will freeze a new plan.                                                                                                                              |

Use the existing `IconPinFilled`, `IconPin`, `IconRefresh`, and LemonUI `Tooltip` components.
Do not use a lock icon because it suggests access control.
Do not use a snowflake image because PostHog already uses that mark for the Snowflake integration.

The icon must be keyboard-focusable and have an accessible label that communicates the same state without requiring the tooltip.
The status remains a single plan-level indicator because freezing is all-or-nothing today.

Rename the delivery detail heading `Generated queries` to `Queries`.
The queries may have been reused from a frozen plan, so the current heading can imply that the planner generated them for that delivery.
Do not repeat the subscription's current status inside historical delivery rows because it may no longer describe those deliveries.

## State transitions

1. A new AI prompt subscription returns `not_frozen`.
2. A fully successful delivery persists a current plan and the status becomes `frozen`.
3. A prompt edit clears the plan and the status becomes `not_frozen`.
4. An `AI_QUERY_PLAN_VERSION` increase leaves the old envelope stored, and the status becomes `planner_updated`.
5. The next delivery automatically replans. A successful replacement returns the status to `frozen`.
6. If regeneration does not produce a freezable plan, the stored stale envelope remains and the status stays `planner_updated` for another automatic attempt.

## Error and compatibility behavior

- The status is informational and never blocks delivery.
- Unknown or unavailable status values render no query-plan item rather than breaking the subscription detail page or leaving an empty value behind during a rolling deploy.
- Malformed stored data is presented as `not_frozen` and is converted into the runtime's recoverable invalid-plan error so the delivery replans automatically.
- Existing subscriptions require no data migration because status is derived from `ai_query_plan`.
- Existing planner upgrade behavior remains unchanged.
- Derivation performs no database queries. Full schema validation runs only for current-version AI plans and remains bounded by the existing query-plan step limit.

## Testing

Backend tests should cover:

- `null` for non-AI subscriptions.
- `not_frozen` with no plan.
- `frozen` for a current, schema-valid plan.
- `planner_updated` for a valid integer version mismatch.
- `not_frozen` for malformed envelopes, boolean or non-integer versions, malformed current-version plans, and malformed relevant-event data.
- The shared validator returns the same classification that the frozen execution path enforces.
- Non-object and malformed envelopes raise `StoredPlanInvalidError` on the frozen path so the report pipeline replans instead of failing.
- Prompt edits clearing the plan and returning `not_frozen`.

Frontend tests should cover:

- Each status selects the correct icon and accessible label.
- Each tooltip explains the matching lifecycle state.
- The query plan item appears only for AI prompt subscriptions.
- An unknown or absent status fails closed without rendering a misleading icon.
- Delivery details use the `Queries` heading.

Visual verification should render the AI subscription detail at normal and narrow scene widths and confirm that the added summary item does not clip or cause horizontal scrolling.

## Scope ceiling

Ship only the derived API status, compact subscription-level icon and tooltip, heading correction, generated contracts, focused tests, and visual verification.
Defer controls, plan identifiers, per-delivery provenance, persisted invalidation reasons, and version-management UI until usage demonstrates a need.

## Adversarial review resolutions

- Centralize validation and classification so the UI cannot drift from execution semantics.
- Treat corrupt envelope types, boolean versions, and malformed relevant-event data as recoverable invalid plans.
- Describe freezing as safe reuse rather than query success alone because chart rendering and window placeholders are also freeze gates.
- Scope `planner_updated` to the explicit compatibility revision already used by the runtime instead of implying provenance that is not persisted.
