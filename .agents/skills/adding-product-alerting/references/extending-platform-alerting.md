# Extend the alerts platform

Use this path when adding a reusable alert capability, option, or advanced behavior. Keep a change product-local when only one product needs it and the shared contract would become speculative.

## 1. Classify the extension

| Capability                                                                       | Primary source of truth                                              | Also inspect                                                                           |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Lifecycle state, notification action, control-plane transition, or policy option | `common/alerting/state_machine.py`                                   | Shared decision tests, every adopter policy and adapter, semgrep rule                  |
| Fixed-cadence, calendar, timezone, or schedule-restriction behavior              | `products/alerts/backend/scheduling.py`                              | Product wrappers, create/update paths, due queries, scheduler interval, DST boundaries |
| Destination type or destination-wide option                                      | `products/alerts/backend/destination_configs.py`                     | HogFunction templates/sub-templates, facade exports, product allowlists, `AlertWizard` |
| HogFunction persistence or delivery semantics                                    | `products/alerts/backend/destinations.py`                            | Worker batching, rollback, delivery metrics, destination tests                         |
| Email transport capability                                                       | `products/alerts/backend/email_notifications.py`                     | Facade export, campaign-key semantics, adopter templates and tests                     |
| Shared insight query evaluation                                                  | `products/alerts/backend/evaluation/`                                | Alert config schema, API validation, query-kind gates, generated API types             |
| Shared alert model or API option                                                 | `products/alerts/backend/models/` and `products/alerts/backend/api/` | Migrations, OpenAPI, frontend logic, MCP schema                                        |
| Wizard trigger, destination, or advanced creation option                         | `frontend/src/lib/components/Alerting/AlertWizard/`                  | HogFunction sub-template compatibility, adopter props, kea tests                       |

If the change crosses rows, update each row deliberately. Do not hide a cross-layer contract in one product adapter.

## 2. Preserve extension rules

### Lifecycle

- Keep `common/alerting/` free of Django and product imports.
- Add policy fields only for observed semantic differences. Give them defaults that preserve every existing adopter.
- Prefer a new pure transition helper over direct model mutation.
- Update the decision table for firing, resolving, snoozing, erroring, breaking, cooldown, and notification edges affected by the change.
- Audit delivery rollback so a new notification action cannot consume an edge before delivery succeeds.

### Scheduling

- Keep scheduling helpers pure Python with no Django or product model imports.
- Keep fixed-grid and calendar contracts explicit instead of branching on product names.
- Make scheduler interval assumptions explicit.
- Preserve deterministic UUID-based sharding and stable steady-state cadence.
- Preserve local wall-clock anchors across DST changes and evaluate restrictions in the team's timezone.
- Test missed intervals, drift healing, cadence changes, DST transitions, overnight windows, and boundary times.
- Keep due eligibility with the product unless a real cross-product model contract exists.

### Destinations and advanced destination options

A new destination type normally requires all of these:

1. Add the enum value, HogFunction template ID, and required fields in `products/alerts/backend/destination_configs.py`.
2. Extend validation and `build_alert_destination_config(...)` without changing existing payloads.
3. Add or update the transport template under `posthog/cdp/templates/<destination>/template_<destination>.py` and its adjacent tests.
4. Add alert-specific template compatibility in `frontend/src/scenes/hog-functions/sub-templates/sub-templates.ts`.
5. Decide which products explicitly allow the destination and update their destination editors or display logic.
6. Add the option to `AlertWizard` only where supported by the relevant sub-template.
7. Cover validation, generated payloads, ownership-safe deletion, CDP template behavior, product rendering, and wizard compatibility.

For an advanced option on an existing destination, decide whether it is transport-wide or product-specific. Transport-wide options belong in typed shared destination data and the shared builder. Product-only wording, event properties, and event-kind behavior remain in `EventKindSpec` and the product adapter.

### Delivery

- Treat event creation, producer flush, and producer acknowledgement as separate phases.
- Do not describe producer acknowledgement as final destination delivery. HogFunction execution and external destination delivery happen downstream.
- Keep batch flushing efficient and bounded.
- Keep helpers non-throwing only where the caller can make an explicit rollback decision from the return value.
- Add metrics and structured failure context for new dispatch phases.
- Verify that partial batch production failure rolls back only affected alerts.

### Email

- Keep `send_alert_email(...)` a transport helper, not a product policy engine.
- Preserve caller ownership of recipients, templates, context, and campaign keys.
- Add shared options only when multiple alert types need the same transport behavior.
- Do not weaken retry or deduplication behavior by generating unstable campaign keys inside the helper.

### Shared insight evaluation

`products/alerts/backend/evaluation/` is kind-agnostic within insight alerts. Extend its contract when adding a query kind or comparison behavior:

1. Define the alert config schema and validation.
2. Add or update the extractor that produces `ExtractionResult`.
3. Keep comparison and breach formatting independent from query execution where possible.
4. Register dispatch by query kind without branching in unrelated extractors.
5. Gate unsupported or feature-flagged kinds consistently across create, update, and simulate paths.
6. Regenerate OpenAPI and frontend types after serializer/schema changes.

Do not route unrelated product evaluators through this package solely because it is named `evaluation`.

### Shared product alert frontend

Extend `products/alerts/frontend/components/` only when a second adopter has the same presentation contract.

- Keep shared components container-agnostic and free of product-name branches.
- Accept normalized definition rows, destination view models, evaluation points, thresholds, scheduling state, and enabled counts.
- Keep API calls, form schemas, kea logic, payload construction, product filters, detector configuration, simulations, and history tables in product adapters.
- Prefer small composable definition primitives over one component with optional props for every alert product.
- Preserve pending destination retry behavior, loading states, and submit guards.
- Add or update shared component stories and verify at least one insight and one logs path when changing a shared contract.

Read [frontend-alerting.md](frontend-alerting.md) for the current component map and adoption workflow.

### AlertWizard

- Put business logic in keyed kea logic, not React hooks.
- Keep trigger/destination compatibility derived from HogFunction sub-templates.
- Add reusable UI options only when their backend input contract is shared.
- Keep product-only fields in the product UI and pass the resulting HogFunction inputs into the wizard contract.
- Preserve URL restoration, existing-alert detection, testing, loading, and double-submit behavior.

Read `frontend/src/AGENTS.md` before changing the wizard.

## 3. Expose the shared contract

- Export product-facing Django helpers through `products.alerts.backend.facade.api`.
- Keep worker-only delivery primitives in `products.alerts.backend.destinations` when callers need their detailed result types.
- Update type annotations and help text so OpenAPI and MCP schemas remain useful.
- Update this skill when the ownership boundary, public helper set, or adoption workflow changes.

Do not expose internal helpers merely for convenience. A facade export is a compatibility commitment.

## 4. Prove backward compatibility

Verify both the shared layer and reference adopters:

- Pure lifecycle or scheduling unit tests.
- Destination, delivery, email, or evaluation tests for the changed contract.
- Logs tests for lifecycle, scheduling, HogFunction delivery, and rollback changes.
- Insight alert tests for model/API, evaluation, email, or calendar scheduling changes.
- Shared alert component stories and at least one insight and one logs adopter path for frontend changes.
- `AlertWizard` logic tests and at least one adopter path when the wizard contract changes.
- OpenAPI generation and frontend typecheck for API contract changes.
- The alert-state semgrep rule when lifecycle mutation paths change.

Invoke the matching mandatory skills before editing their areas:

| Change                                                    | Skill                           |
| --------------------------------------------------------- | ------------------------------- |
| Serializer or viewset                                     | `/improving-drf-endpoints`      |
| Django model or migration                                 | `/django-migrations`            |
| Frontend handwritten API usage or generated type adoption | `/adopting-generated-api-types` |
| Tests                                                     | `/writing-tests`                |
| MCP tools or `tools.yaml`                                 | `/implementing-mcp-tools`       |
| AlertWizard or product kea logic                          | `/writing-kea-logics`           |

## 5. Reject the wrong abstraction

Stop and keep the change product-owned when:

- No second use case exists.
- The option leaks product model fields into `common/alerting/`.
- A generic helper would need product-name branches.
- A destination option changes only one event kind's content.
- A shared due query would require one product's state names or tenant model.
- A wizard option has no shared HogFunction input contract.

The platform should grow from proven adopter needs, not from guessed future flexibility.
