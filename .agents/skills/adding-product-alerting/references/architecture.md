# Shared alerting architecture

Use this reference to decide where code belongs before editing it.

## Layer map

| Layer                        | Location                                                     | Owns                                                                                                                                               |
| ---------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pure lifecycle decisions     | `products/alerts_platform/backend/facade/lifecycle.py`       | State transitions, policy decisions, and notification actions                                                                                      |
| Pure scheduling math         | `products/alerts_platform/backend/facade/scheduling.py`      | Shard offsets, cadence and calendar anchors, and schedule restrictions                                                                             |
| Alerts platform door         | `products/alerts_platform/backend/facade/`                   | Platform contracts and enums, configuration reads and writes, ownership handover, source registration hooks, and delivery SLOs                     |
| Alerts platform runtime      | `products/alerts_platform/backend/`                          | Models, the tick and source dispatch, outcome recording, native delivery, destinations, routes, and shadow comparison. Only its facade is imported |
| Insight alert door           | `products/alerts/backend/facade/`                            | Insight alert contracts and event constants, HogFunction destinations, email, and insight alert reads and writes. Other products call it           |
| Insight alert implementation | `products/alerts/backend/logic/`                             | Destination configuration and persistence, internal-event delivery, and email transport. Only the facade calls it                                  |
| Insight alert evaluation     | `products/alerts/backend/evaluation/`                        | Insight query extraction, comparison, and breach formatting. Core still drives it directly                                                         |
| Product adapter              | `products/<name>/backend/`                                   | Domain evaluation, model snapshots, the single mutator, event payloads, allowed destinations, due queries, history, and the platform source        |
| Shared alert creation UI     | `frontend/src/lib/components/Alerting/AlertWizard/`          | Reusable HogFunction destination, trigger, and configuration flow                                                                                  |
| Shared product alert UI      | `products/alerts/frontend/components/`                       | Container-agnostic editor layout, definition primitives, advanced options, destination editor, schedule presentation, and evaluation chart         |
| Product UI                   | `products/<name>/frontend/` or `frontend/src/scenes/<name>/` | Form logic, API calls, product fields, normalized adapters, entry points, detail tables, and wizard configuration                                  |

`products/billing_alerts` is the reference adopter for the backend boundary shape: it holds destination ids and the facade contracts, and never an alerts model or queryset.

`products/logs` is the reference adopter for fixed-cadence scheduling, HogFunction destinations, delivery rollback, product-owned Temporal orchestration, and the shared product alert editor components. It was also the first platform source and the first product to cut over.

Logs and insight alerts both adapt their product state to the shared lifecycle engine. Insight alerts are the reference adopter for calendar anchors, weekend skipping, and email delivery. Both products use shared schedule restrictions for quiet hours. Each product keeps its model, due query, and scheduling persistence. The evaluation package is shared across insight query kinds, but it is not a generic evaluator for unrelated products.

## Boundary

Consumers import `products.alerts.backend.facade.*` and `products.alerts_platform.backend.facade.*`. Core mounts the DRF surface through `routes.*`. Other products that still mount or reuse `presentation.views.*` in process reach past the facade, and hoglint's `public-surface` rule reports those imports.

- Models, querysets and DRF objects never cross either facade in either direction.
- Facade functions take and return contracts, ids, and plain values.
- Consumers hold ids and come back to the facade for anything else.

Core still runs the insight-alert pipeline itself, so its imports of the alert models, the insight evaluation, the insight lifecycle adapter, the investigation episode reader and the Max tool stay open. hoglint's `public-surface` rule reports those imports, and `backend:contract-check` stays off until they are gone. The alert models have a second exit of their own, because products outside core also import them.

## Alerts platform

The platform evaluates and delivers alerts for every source kind on one set of Temporal fleets. `docs/internal/alerts-platform-temporal.md` describes its queues, tick, source dispatch and worker capacity. Read its capacity section before adding a source or raising a pool.

### Sources

A source kind is one product's alerts on the platform, such as insight, logs, metrics or traces. `SourceKind` in `products/alerts_platform/backend/facade/contracts.py` lists them. A source plugs in through:

1. An evaluation workflow that takes `SourceEvaluationInputs`, reads its data, decides, and returns. The platform's own activity records the outcomes, so a source never writes platform state itself.
2. A `SourceBinding` in `SOURCE_BINDINGS` (`products/alerts_platform/backend/temporal/sources.py`), naming the workflow, its queue, its evaluation timeout and its discovery limit.
3. Its workflows and activities in the worker registration for that queue.
4. A `SourceConfigSpec`, which may carry a rollout flag.
5. Hooks registered at app ready, keyed by `SourceKind`. `register_source_describer` and `register_source_config` are the minimum. Optional hooks add alert creation, viewing, recipients, subscriber access, images, legacy events, legacy webhook bodies and config drift checks. `products/alerts/backend/apps.py` and `products/logs/backend/apps.py` show the full set.

### Ownership and cutover

A product's own alert row and its platform copy share one `owner`: `source` or `platform`. The owner is the only stack that evaluates, delivers and writes the alert. `legacy_configuration_id` links the copy to the source row.

- Ownership changes through `take_ownership` and `give_back_ownership` in the platform facade, which write the copy. The caller writes `owner` and `owner_changed_at` on its own row in the same transaction. For insight, `hand_over` and `roll_back_team` in `products/alerts/backend/platform_cutover.py` do this for the cutover and rollback commands and for new alerts.
- An edit to a platform-owned alert goes through the source's API and is mirrored into the copy. `products/alerts/backend/platform_ownership.py` holds the insight version.
- A new alert in a team that has cut over starts on the platform. Behind a flag, an insight alert can be created with no source row at all.
- After a cutover, the source stack keeps evaluating the moved alerts for a shadow week without delivering, so the two stacks can be compared.

### Destinations and delivery

Where an alert's destinations live is a rule per alert kind, not a field on the configuration: `source_configs.keeps_platform_destinations` reads it from the kind's registration (`native.platform_destinations`).

- For a kind whose source keeps HogFunctions, the alert still sends through them. A platform-owned alert on the `HOG_FUNCTION` delivery path has the source emit the internal events its own stack emitted, so customers receive exactly what they received before the cutover.
- For a kind that keeps platform destinations, `AlertDestination` rows hold them, and the platform's own transports send each type natively. Team-wide `AlertReceiver` and `AlertRoute` rows match alerts by label.

The HogFunction destination and delivery contracts below serve alerts whose destinations have not moved to the platform.

## Frontend contract

Shared product alert UI lives in `products/alerts/frontend/components/`. It is presentation infrastructure, not a frontend product registry.

- `AlertEditor`, `AlertEditorFormDetails`, and `AlertEditorSection` provide the container-agnostic form shell.
- `AlertDefinition*` components provide composable definition, schedule, next-evaluation, and timezone presentation.
- `AlertAdvancedOptions` owns shared collapse and enabled-count behavior.
- `QuietHoursFields` renders shared quiet-hour inputs from a normalized restriction, cadence, and project timezone.
- `AlertNotificationDestinationEditor` renders normalized saved and pending destinations.
- `AlertEvaluationHistoryChart` renders normalized evaluation points and current thresholds.

Products own keyed kea logic, API calls, form schemas, source/filter controls, supported destination types, HogFunction payloads, threshold conversion, enabled-count calculation, and history tables. Keep modals, scene widths, and embedded-section sizing in the product surface.

`AlertWizard` remains the shared HogFunction creation flow. Adopters provide keyed `alertWizardLogic` props with supported sub-template IDs, `WizardTrigger[]`, `WizardDestination[]`, and optional URL or preset behavior. Backend destination support alone does not make an option available in the wizard.

Read [frontend-alerting.md](frontend-alerting.md) before adding or extending a product alert frontend. Follow `frontend/src/AGENTS.md`, use generated API types, and guard network submissions from double clicks.

## Lifecycle contract

`products/alerts_platform/backend/facade/lifecycle.py` is pure Python.

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

Product-facing HogFunction destination setup lives in `products.alerts.backend.facade.destinations`. Read that module for the full surface. An adopter starts from:

- `validate_destination_data`
- `destination_handles_event_kind`
- `build_alert_destination_config`
- `create_alert_destination_hog_functions`
- `soft_delete_alert_destinations`

The module also holds the destination limits. The insight-alert event and destination-type constants live in `products.alerts.backend.facade.contracts`.

`send_alert_email` lives in `products.alerts.backend.facade.email`. The data types the functions above take and return, such as `EventKindSpec`, `DestinationType` and `AlertDestinationValidationError`, live in `products.alerts_platform.backend.facade.contracts`.

`create_alert_destination_hog_functions` returns the ids of the hog functions it created. It
does not return model rows, so the caller keeps ids and asks for anything else through
another facade read.

`EventKindSpec` describes destination-neutral content for one event kind. The shared builder converts it into a HogFunction payload through an internal registry where each destination type owns its template ID, required fields, input building, read-back, and read redaction. Adding a destination type means adding one entry there. Products own event IDs, event properties, wording, actions, and their allowed destination list.

Not every destination type has something to send for every event kind. An incident manager such as PagerDuty follows only the kinds that trigger or resolve an incident, which a product marks with `EventKindSpec.incident_action`. Every other destination type follows only the kinds without it. Filter a product's event kinds with `destination_handles_event_kind` before building configs; `build_alert_destination_config` raises for a kind the destination type does not handle.

An incident manager needs a resolve for every trigger, or the incident it opened stays open and absorbs the next trigger on the same deduplication key. So the incident kinds follow the firing state, not the notification: emit one on every transition into and out of firing, even when cooldown suppresses the notification. Logs alerts do this with `$logs_alert_incident_opened` and `$logs_alert_incident_closed`, read from `incident_edge` in `products/logs/backend/alert_state_machine.py`.

An edit can also move a firing group from one incident manager to another: a change to an alert's own destinations or labels, or to the team's routes and receivers. `hand_over_after_commit` in `products/alerts_platform/backend/logic/destination_handoff.py` sends the resolve to the incident manager that lost the group and the trigger to the one that gained it, once the edit commits. Resolves go from the edit's own request, up to 20 per edit, because the destination they go to may already be gone. Triggers, and any resolves past that limit, go through a delivery workflow.

A destination type whose configuration is a credential, such as the PagerDuty integration key, stores it as a secret template input. The read path merges `encrypted_inputs` back before it reads a config, so grouping and duplicate detection see the real value while `redact_destination_data` keeps it out of API responses.

Validation failures raise `AlertDestinationValidationError`, a plain exception with a message and an optional field name. The adopter's view translates it into its own framework's validation error, because the facade has no HTTP layer of its own. `as_drf_validation_error` in `posthog.exceptions` does that translation for a DRF view.

Deletion is fail-closed. Always scope it with `team_id`, `alert_id`, and the product's allowed event IDs.
`create_alert_destination_hog_functions` refuses any destination in the call that the alert already has, so call it with the alert row locked.

## Delivery contract

HogFunction notification workers use `products.alerts.backend.facade.destinations`:

1. `produce_alert_internal_event(...)` returns a `ProduceResult` or `None`.
2. `flush_alert_internal_events(...)` flushes the shared producer. Batch workers should flush once per produced batch.
3. `alert_internal_event_delivered(...)` checks whether the producer acknowledged each internal event after the flush.
4. The product persists notification-dependent lifecycle changes only for acknowledged internal events.

This acknowledgement confirms production to the internal-event transport, not downstream HogFunction execution or final Slack, Discord, webhook, or Microsoft Teams delivery. The helpers log and capture producer failures. The product owns rollback, retry timing, schedule advancement, and check-history semantics.

Wrap the delivery step in `alert_delivery_slo(...)` from `products.alerts_platform.backend.facade.delivery_slo`. Logs' Temporal activities are the reference.

Email callers use `send_alert_email(...)` from `products.alerts.backend.facade.email`. The caller owns recipients, authorization, subject, template, context, error handling, and a stable `campaign_key` for the required retry and deduplication behavior.

## Scheduling contract

`products/alerts_platform/backend/facade/scheduling.py` is pure Python and owns reusable scheduling math:

- `compute_shard_offset_seconds(...)` deterministically assigns a UUID-keyed alert to scheduler ticks.
- `advance_next_check_at(...)` advances from the prior schedule, skips missed intervals, snaps to the midnight-anchored cadence grid, and applies the shard offset.
- `CalendarInterval` and `to_calendar_interval(...)` define the product-facing interval contract.
- `next_calendar_check_time(...)` computes fixed-cadence or team-local daily, weekly, and monthly anchors while preserving wall-clock behavior across DST changes.
- `validate_and_normalize_schedule_restriction(...)` and `parse_blocked_windows_tuples(...)` validate product payloads and produce the pure blocked-window contract.
- `scan_next_unblocked_utc(...)`, `is_utc_datetime_blocked(...)`, and `is_weekend(...)` apply timezone-aware restrictions without importing Django models.

Use the scheduler's real interval when computing shards. Use the same shard function when creating, updating, and advancing an alert.

Products translate their enums and stored payloads into the shared contract. Due eligibility, schedule persistence, retry behavior, and orchestration stay product-specific because model fields, states, snooze behavior, and tenant constraints differ.
