---
name: adopting-shared-alerting
description: How PostHog's shared alerting primitives work and how a product plugs into them. Use when working on alert lifecycle (firing/resolved/snoozed/broken transitions), alert notification destinations (Slack/Teams/webhook HogFunctions), alert check scheduling, or when a product (logs, insights, billing, error tracking, AI obs) needs alerting behavior. Covers common/alerting (pure decision logic), posthog/alerting (Django glue), and the single-mutator rule. Trigger terms: alert state machine, AlertPolicy, apply_outcome, CheckInput, EventKindSpec, due_alerts_q, alert destinations, alert lifecycle.
---

# Adopting shared alerting

PostHog is consolidating alert lifecycle onto a shared platform, following the Prometheus/Alertmanager split: **evaluation is domain-specific per product; lifecycle decisions, notification delivery, and scheduling are shared.** A product supplies "did this check breach?"; the platform owns "so is the alert now firing, should we notify, when do we check next."

> [!IMPORTANT]
> This skill documents what has landed so far: the shared primitives and the rules for using them. The **self-serve adoption flow** (register a product spec, provide an evaluator returning `CheckInput`, wire a Temporal harness with push/`submit_check`) is not built yet — it arrives in later phases. Until then, adopt the primitives directly the way `products/logs` does, and treat cross-product orchestration as bespoke per product.

## The three layers

| Layer               | Location                   | May import                            | Holds                                                                       |
| ------------------- | -------------------------- | ------------------------------------- | --------------------------------------------------------------------------- |
| Pure decision logic | `common/alerting/`         | no Django, no product code            | state machine, destination config builders, grid scheduling math            |
| Django glue         | `posthog/alerting/`        | Django, HogFunction, ORM              | HogFunction create/delete/dispatch, the due-alerts query                    |
| Product-owned       | `products/<name>/backend/` | its own models + the two layers above | evaluation, domain config/thresholds, check history, the thin state adapter |

`common/alerting/` is tach-enforced pure Python (`tach.toml` module `common.alerting`). It is tracked debt per [common/CLAUDE.md](../../../common/CLAUDE.md) — the graduation target is a standalone `packages/` leaf once enough products adopt it and the back-edges into app code are gone. Name that target in any PR that grows this area.

## Layer 1 — `common/alerting/state_machine.py`

The heart of the platform. Pure functions over frozen dataclasses, zero I/O.

- `AlertState` — `FIRING` / `NOT_FIRING` / `SNOOZED` / plus internal transition states. (Insight alerts persist legacy `"Firing"`/`"Not firing"` strings — those get mapped at the product adapter boundary, not here.)
- `AlertPolicy` — a frozen dataclass of per-product behavior flags: cooldown gating, re-notify-while-firing, error escalation, snooze semantics, broken handling. A product expresses its semantics as a policy **instead of forking the machine.** `LOGS_ALERT_POLICY = AlertPolicy()` is all-defaults.
- `CheckInput` — what a product's evaluation produces for one check: breached or not, plus `is_inconclusive` for not-yet-settled data (an inconclusive verdict preserves `consecutive_failures` rather than resetting).
- `evaluate_alert_check(snapshot, check_input, policy)` / `evaluate_alert_failure(...)` — the decision functions. They return an `AlertCheckOutcome` (new state + whether to notify); they do **not** mutate anything.

Error semantics to know before adopting: failed checks never move firing state (CloudWatch's INSUFFICIENT_DATA doesn't clear ALARM — a FIRING alert rides through a failed check), transient errors skip the cycle entirely (no notification, no counter change), and the error notification fires on the 0 → 1 `consecutive_failures` edge rather than on a state transition. If your dispatch layer rolls back state after a failed notification enqueue, roll back the failure counter with it or the retry stays silent.

- `apply_user_reset` / `apply_enable` / `apply_disable` / `apply_snooze` / `apply_unsnooze` / `apply_threshold_change` — control-plane transitions, each returning a `ControlPlaneOutcome`.

### The single-mutator rule (enforced)

Every write to an alert model's `state` / `consecutive_failures` must go through **one** product module — the state adapter — via its `apply_outcome`. Nothing else may assign those fields. This is enforced in CI by `.semgrep/rules/security/alert-state-must-go-through-state-machine.yaml`; add your product's include/exclude paths there when you adopt.

Pattern (from `products/logs/backend/alert_state_machine.py`):

```python
# The product adapter bakes its policy in; the shared machine takes it as a kwarg.
outcome = evaluate_alert_check(alert.to_snapshot(recent_events_breached=recent_breaches), check_result, now)
update_fields = apply_outcome(alert, outcome)  # the ONLY function that writes state / consecutive_failures
alert.save(update_fields=update_fields)
```

The adapter owns the product-shaped translation (model → `AlertSnapshot`, and outcome → model mutation). The shared machine stays product-agnostic.

## Layer 1 — `common/alerting/destinations.py`

Pure builders for alert notification destinations, delivered as HogFunctions.

- `EventKindSpec` — describes an alert-event kind (labels, message text) so Slack/Teams/webhook bodies render consistently.
- `build_slack_destination_config` / `build_webhook_destination_config` / `build_teams_destination_config` — return an `AlertDestinationConfig` (the serializer payload plus the team it belongs to, carried alongside so it never enters serializer input).
- `destination_filter(alert_id, event_id)`, `slack_blocks`, `teams_text`, `clip_hog_function_name` — helpers.

## Layer 1 — `common/alerting/scheduling.py`

Grid-cadence scheduling math (used by logs; billing will use it too):

- `advance_next_check_at(...)` — next check time on a fixed cadence grid.
- `compute_shard_offset_seconds(...)` — spreads checks across a window so they don't stampede.

> [!NOTE]
> Two scheduling models coexist deliberately. **Grid** (this file) is for products that check on a fixed cadence. **Calendar** anchoring (interval enum + quiet hours + weekend skip, used by insight alerts) has not been extracted into `common/alerting/` yet — it still lives in `posthog/tasks/alerts/`. Pick one when you adopt; do not mix.

## Layer 2 — `posthog/alerting/`

Django-aware glue that the pure layer can't hold:

- `destinations.py`: `create_alert_destination_hog_functions` (takes `AlertDestinationConfig`s), `soft_delete_alert_destinations`, `soft_delete_all_alert_destinations`, `produce_alert_internal_event`. This is where HogFunctions are actually created/deleted (via serializer) and where the internal alert event is produced onto the bus.
- `scheduling.py`: `due_alerts_q(now, *, broken_state, snoozed_state=None)` — builds the `Q` predicate for "which alerts are due for a check now," parameterized by the product's state field names (products differ: `snoozed_until` vs `snooze_until`). Tested directly in `products/logs/backend/test/test_due_alerts_q.py`.

## Adopting today (the logs pattern)

`products/logs/backend/` is the reference adopter. To wire a product to the primitives now:

1. Define your `AlertPolicy` (start from defaults; only set flags where your semantics differ).
2. Write one state adapter module (`alert_state_machine.py`-style) exposing `apply_outcome` as the single mutator, plus `to_snapshot()` on your model.
3. Route notification create/delete/dispatch through `posthog/alerting/destinations.py`.
4. Build your due-alerts query with `posthog/alerting/scheduling.py:due_alerts_q`, passing your state field names.
5. Add your product's paths to the semgrep single-mutator rule.
6. Keep evaluation, thresholds, check-history models, and your Temporal workflow in your product — they consume the primitives, they don't move.

## What's coming (not yet available)

- A config contract (`AlertConfigLike` Protocol + abstract base model) so new products get the shape for free.
- A generic Temporal harness with a product registry and two trigger modes: scheduled sweep (grid or calendar) and **push** (`submit_check(product, alert_id, CheckInput)`) for event-driven products.
- Insight alerts moving onto the shared machine; calendar scheduling extracted into `common/alerting/`.

When those land, this skill gains the full "register a product and write only an evaluator" walkthrough. Until then, follow the logs pattern above.
