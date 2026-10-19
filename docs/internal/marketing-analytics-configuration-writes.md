# Marketing configuration writes

Marketing settings PATCH requests send only the setting being changed. Updating filters or attribution settings must not resend an old conversion-goal list.

The configuration serializer refreshes the marketing configuration under a row lock before applying a partial update. This preserves fields changed by concurrent goal operations and source mappings. It does not lock the parent project row.

Explicit conversion-goal list updates still replace the list. This change does not merge simultaneous edits to the same goal list or change the API schema.

The marketing configuration cache belongs to each `Team` instance. New project reads load saved goals even when an earlier request read an empty configuration.

Validation covers a stale settings instance saved after goal creation, a project read after goal creation, and a frontend filter update that omits goals from its payload.

The conversion-goals list also returns the exact saved `conversion_goals`, `filter_test_accounts`, and `base_currency`, alongside its existing performance summaries.
The endpoint refreshes the configuration before reading it so callers can verify a recent write without fetching the full project object.

## Warehouse conversion attribution

The attribution table and conversion paths query runners accept configured `DataWarehouseNode` goals.
They use the same goal format as the configuration API; this does not add a separate goal model or enable the warehouse goal picker in the attribution UI.

Map a source table or saved view into the following fields:

| Goal field                       | Meaning                                                                                                                                                                                  |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id_field`                       | A stable ID for one conversion. Repeated identical rows count once; conflicting rows for an ID fail the query.                                                                           |
| `timestamp_field`                | When the conversion occurred. The selected date range applies to this field.                                                                                                             |
| `distinct_id_field`              | A PostHog distinct ID. Existing aliases resolve to the same person before attribution.                                                                                                   |
| `math_property`                  | The amount for `sum` math, in currency units rather than cents. Negative amounts reduce attributed value.                                                                                |
| `math_property_revenue_currency` | An optional fixed currency or source column. Conversion uses the project base currency and the conversion date. An absent or empty currency follows the existing base-currency fallback. |

For the ID, timestamp and distinct ID mappings, a nonempty entry in `schema_map` takes precedence over the corresponding top-level field.
Warehouse columns supply the goal's `properties` and `fixedProperties` filters.
Use a saved view for joins, unit conversion, status rules or nested fields that need transformation.
The view can use the warehouse's existing materialization support; Marketing does not create or refresh a separate materialized view.

Source rows do not need UTM columns for these attribution queries: touchpoints come from the person's sessions.
This does not change Ad performance's existing direct warehouse attribution or its UTM requirements.
Rows without a resolvable person or eligible touchpoint remain in the total and count as unattributed.
Only rows in the selected conversion date range are validated for duplicate IDs and finite amounts.
Rows without a timestamp cannot fall inside that range and are not included.

The source must use person identity; an external customer or organization ID needs an explicit mapping to PostHog distinct IDs in the source view.
Organization attribution is not implemented by this mapping.
The first backend version supports total, unique-user and sum math, with the existing repeat-conversion and attribution-window behavior.
Unique mode keeps the first conversion within the selected range, not the first conversion ever.
Configured test-account filters and query-level property filters are rejected for warehouse goals, rather than applied only to sessions.
Filter the source explicitly and disable test-account filtering for that query until equivalent person-filter support is implemented.
The existing per-person caps still apply, so high-volume attribution remains approximate beyond those caps.

## Preview an unsaved conversion goal

`POST /api/projects/{project_id}/marketing_analytics/conversion_goals/preview` evaluates a goal without adding or changing a configured goal.
It requires `marketing_analytics:read`, project access, and the existing marketing setup or dashboard feature gate.
The endpoint is limited to 10 requests per user per minute.
It uses attribution-table semantics with channel breakdown; Ad performance uses a different attribution path.

For example, an event goal can be previewed with this body:

```json
{
  "goal": {
    "kind": "EventsNode",
    "event": "purchase_completed",
    "conversion_goal_name": "Paid purchases",
    "schema_map": {},
    "math": "sum",
    "math_property": "amount",
    "math_property_revenue_currency": { "property": "currency" },
    "counts_as_revenue": true
  },
  "date_from": "2026-09-01T00:00:00Z",
  "date_to": "2026-09-07T23:59:59Z",
  "filter_test_accounts": false
}
```

Dates are inclusive and the conversion period must be greater than zero and at most 31 days.
The response echoes the resolved dates and settings.
Optional `lookback_window_days`, `allow_multiple_conversions_per_visitor`, and `filter_test_accounts` follow the report/project defaults when omitted.
`exclude_direct_traffic` and `exclude_unattributed` default to false and filter the eligible session touchpoints.
The preview's goal ID is a temporary placeholder, not a saved goal ID or an apply token.

The first version supports events, actions, warehouse tables, and saved views with total, unique-user, or sum aggregation.
Revenue goals must use sum with an amount field.
Group aggregation and monetary multipliers are rejected; transform values in the source first.
The warehouse filtering and identity limits described above still apply.
The preview and both journey-attribution reports use the shared currency expression, including event and action revenue.

The response reports total, evaluated, attributed, and unattributed conversion counts and values.
It calculates coverage before dimension pagination, so a limited report page cannot lower the preview's totals.
Count-only goals have null monetary/value fields.
Revenue values use the project base currency.
The existing event amount fallback turns missing or nonnumeric event amounts into zero; the response warns about that behavior.

Per-person conversion limits can leave some conversions unevaluated.
In that case, the response keeps the full conversion count, marks the result approximate, and returns null for total and unattributed value instead of presenting a partial sum as the total.
`evaluated_value` and `attributed_value` describe the evaluated subset.
Reaching the touchpoint limit also marks attribution as potentially approximate.
Execution has a 30-second ClickHouse budget and a 1 GB read budget, with overflow configured to fail instead of returning partial results.

`checks_not_performed` explicitly identifies missing source-quality profiling, timestamp checks outside the selected range, native-currency breakdown, currency-code and exchange-rate validation, identity-match coverage, sync freshness, and business-definition validation.
It also lists transaction uniqueness and first-ever customer validation.
Event/action sums warn that transaction properties do not deduplicate payments. Customer goals warn that the preview neither establishes first-ever customers nor counts unique accounts.
`observed_at` is the preview completion time, not a source sync timestamp.
This summary preview does not certify that a source represents revenue or that a goal is ready to apply.
It does not create a view, materialize data, or persist preview evidence.

The generated `marketing-analytics-preview-conversion-goal` MCP tool exposes this read-only endpoint behind `marketing-analytics-conversion-setup-ai` with the `marketing_analytics:read` scope.
The backend also requires that flag and either Marketing analytics Setup or the new dashboard to be enabled.
The tool accepts the existing goal union, preserves action IDs and goal filters, and returns the same limitations as the API.

## Conversion setup and AI recommendations

The assisted Setup cards, AI context, draft review, and preview tool are gated by `marketing-analytics-conversion-setup-ai`, which is off when absent or disabled.
Enable it for selected people or organizations alongside `marketing-analytics-mcp` and the scene AI integration flags to test the full workflow.
Turning it off unmounts the assistant integration; manual goal configuration and the existing goal CRUD API remain available.
The eval harness enables the preview tool only in its local development/test MCP process.

The current setup plan produces deterministic suggestions from diagnostics and candidate events.
Candidate ranking uses activity and UTM coverage; those signals do not establish whether an event represents revenue or a new customer.
The setup plan links to goal configuration when those classifications are missing, rather than proposing a write against the highest-volume goal.
Candidate evidence reports UTM percentages on the same 0–100 scale as the candidate service.

The assisted workflow must feed the existing Setup suggestions with a source reference, draft goal, explanation, measured preview evidence, unresolved questions, and a next action.
The `setting-up-marketing-conversions` product skill provides the initial on-demand agent workflow through MCP.
It starts with the setup plan and saved goals, uses the event shortlist and existing action metadata, then previews a draft before recommending it.
Action discovery uses `system.actions`; the event shortlist itself still only returns events.
It distinguishes discovery ranking from business meaning and carries preview limitations into the recommendation.
The guided flow uses preview-bound application and an idempotent receipt, as described below. Existing manual CRUD operations remain available.
Setup's suggested-setup and conversion-goal sections offer an explicit AI review when the scene's AI integration is enabled.
The last preview call in the foreground turn offers a draft for review. The page re-previews it in the current project before displaying editable controls.
Drafts remain in memory and are scoped by project. Incoming drafts do not overwrite edits; editing invalidates the previous preview and confirmation.
Saving requires a preview, confirmation of the relevant business and source checks, and project admin access.
The UI checks for existing names, prevents concurrent saves, then verifies the full saved definition. An ambiguous response retries the same preview reference, which cannot create a duplicate goal.
Async responses are scoped to the original mounted editor and preview so returning to Setup cannot apply a different unconfirmed draft.
Persisted recommendation cards remain available in Setup. The on-demand AI conversation can supply an additional draft, and the editor reviews one draft at a time.

The remaining backend contract should support this sequence for the integrated setup experience:

1. Discover accessible events, tables, views and their schemas within the current project.
2. Describe the business outcome and propose a source, column mappings and filters. Record the revenue definition, currency units, refund rules and whether identity means a person or an organization.
3. Preview a bounded period using the same source compiler as attribution. Return row and distinct conversion counts, duplicate and invalid-row counts, revenue totals, identity coverage, attribution coverage and data freshness. Mark sampled or incomplete evidence explicitly.
4. Produce a recommendation with its evidence, unresolved questions and proposed goal configuration. Distinguish confidence in the mapping from confidence in the business definition.
5. Apply the validated configuration through existing goal operations, then verify the saved goal produces the previewed result. Source connection and credential setup continue through the warehouse tools.

The read-only summary preview above implements the initial query-validation step locally.
Richer source-quality profiling, warehouse discovery, and release-quality AI evaluation gates remain planned work. Preview-bound event/action application is implemented below.
A recommendation must account for missing permissions and failed data checks instead of presenting a partial scan as a complete assessment.
Evaluate recommendations against synthetic event, invoice, refund and CRM cases, including common distractions such as frequent logins, monetary-looking IDs, recurring revenue snapshots and multiple sources representing the same payment.
Materialization should depend on measured query cost and freshness requirements; it does not establish that the goal's business definition is correct.

## Persisted conversion recommendations

With `marketing-analytics-conversion-setup-ai` enabled, `GET conversion_recommendations` returns the latest run and the latest completed results.
Reading results never starts an analysis.
`POST conversion_recommendations/start` with `refresh: false` starts a 30-day analysis only when the project has no run.
After that, only an explicit `refresh: true` requests another analysis, using 14 days.
An in-flight run is reused across tabs and users, and results from the previous completed run remain visible while it runs or if it fails.
Runs that exceed five minutes become failed; they are not retried automatically.
Project administrators can request analysis; ordinary project readers can review accessible results.
The service rechecks the requesting user's access before querying and before saving results.
Generation requires explicit organization AI data-processing approval and the rollout flag. Both are checked when starting, in the worker, immediately before the provider request, and before persisting results.
The read response includes `can_generate` and a nullable `generation_disabled_reason`; missing consent does not start automatic analysis or prevent reading previously accessible results.

Discovery uses at most 20 custom events and 20 existing actions, excludes configured test accounts from event counts, and sends bounded metadata and aggregate counts to the configured Go AI gateway.
It does not send event rows, person identifiers, or property values.
The internal `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY` configuration must be available to the analytics Celery worker.
The shared gateway credential owns spend; the project and requesting user are attached as telemetry.
No Python gateway fallback is added.
A missing gateway or queue produces a recoverable error and preserves previous results.
Recommendations do not create goals or assert that business definitions have been verified.
Leads, demo requests, signups, and activation milestones use conversion intent. Customer intent requires metadata identifying first-time acquisition; a generic payment alone does not establish acquisition.
Repeated known source references preserve the first proposal. An unknown source reference fails the run rather than creating an invented definition.
The dashboard notice can be dismissed during every state. Dismissal is scoped to the user and project and does not remove the results from Setup.

## Apply a validated event or action goal

A successful event/action preview returns a user- and project-scoped `preview_ref` and a 15-minute `expires_at`.
`POST conversion_goals/apply` accepts that reference, the exact previewed `goal`, and `definition_confirmed: true`.
It requires project-admin access and the AI setup flag.
The server rejects edited definitions, expired evidence, changed action definitions, and changed relevant project configuration with a conflict response.
The preview's business and source limitations still require user review; the reference certifies the evaluated definition, not the meaning of the source.

The config row and evidence row are locked together when applying.
A retry of the same reference returns the same saved goal, including after the original response was lost.
It cannot create another goal, even after the preview expires.
If that saved goal was subsequently edited or deleted, the retry returns a conflict instead of restoring it.
Warehouse previews remain read-only and return a null reference until warehouse source-version validation is supported.
Existing manual create/update/delete operations remain available.

Expired, unused preview evidence is reclaimed in batches of up to 500 when a new preview is recorded.
Applied receipts are retained for safe retries; an inactive project can retain unused expired evidence until its next preview.
