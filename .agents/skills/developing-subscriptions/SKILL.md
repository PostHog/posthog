---
name: developing-subscriptions
description: >
  Guides PostHog engineers through subscription product changes. Use when changing
  subscription resource types, destinations, schedules, delivery workflows, retry or
  automatic disable behavior, permissions, limits, AI summaries, AI prompt reports,
  delivery history, subscription APIs, MCP tools, or subscription management UI.
  Not for configuring an existing subscription through MCP.
---

# Developing subscriptions

Use this skill for a change to the Subscriptions product or its delivery system.

Use the published `managing-subscriptions` skill to configure an existing subscription through MCP.
Use `adding-product-alerting` when delivery depends on a threshold, anomaly, breach, or recovery state.

## 1. Route the request

| Request | Primary path |
| --- | --- |
| Resource type, destination, schedule, delivery, lifecycle, or limits | This skill |
| Subscription API, permissions, MCP tools, or delivery history | This skill |
| Subscription creation or management UI | This skill |
| AI prompt report planning or output | This skill and `integrating-with-posthog-ai` |
| Threshold, anomaly, breach, recovery, or quiet hours | `adding-product-alerting` |
| Configure an existing subscription through MCP | Published `managing-subscriptions` |

Before implementation, name each affected boundary:

- Configuration and validation
- Persistence and schedule calculation
- Workflow queue and retry behavior
- Asset export or AI report generation
- Destination delivery
- Delivery history and failure notifications
- API, MCP, and frontend clients
- Billing, limits, and permissions

## 2. Define feature intake and acceptance criteria

Do this before implementation for a new subscription feature.
Skip it for a narrow bug fix with an existing contract.

1. State the user problem, intended actor, and explicit non-goals.
2. State whether delivery uses a fixed schedule or a condition.
3. State the supported resource types and destinations.
4. State the default behavior for creation, updates, tests, pause, resume, expiration, and deletion.
5. State which actions can send a real message and where the product asks for approval.
6. State the project, organization, resource, and API scope requirements for reads and mutations.
7. State behavior for old rows, missing owners, removed resources, invalid destinations, and exhausted schedules.
8. State retry, deduplication, terminal state, and automatic disable behavior.
9. State the plan limits, organization-wide limits, and billable AI behavior.
10. State the acceptance criteria for success, partial recipient failure, permanent failure, and uncertain delivery.
11. State the event or metric that shows adoption, delivery failure, and regression.
12. Check whether the API, MCP tools, generated types, product docs, and published skill need updates.

## 3. Define the change contract

State these decisions before implementation:

1. Name the persisted fields and the source of truth for each field.
2. Define create, update, test, scheduled, pause, resume, expiration, and delete behavior.
3. Define whether the operation is idempotent and how retries prevent duplicate messages.
4. Define the schedule anchor, time zone, recurrence rule, and next delivery calculation.
5. Define which failures retry and which failures disable the subscription.
6. Define how delivery records distinguish queued, completed, failed, skipped, and partial outcomes.
7. Define how email, Slack, and Microsoft Teams differ across validation, storage, display, and delivery.
8. Define how the API hides credentials, recipient details, upstream errors, and query diagnostics.
9. Define behavior when AI credits, AI approval, or active-summary capacity changes after setup.
10. Define compatibility for the frontend, API, MCP schema, workers, and Temporal workflows during deployment.

For a new API operation, add an MCP tool for each supported action.
Exclude an action only with a documented reason.
Record the required OAuth scopes.

## 4. Implement across boundaries

1. Keep serializer validation, model behavior, generated types, MCP schemas, and frontend forms consistent.
2. Keep each subscription and delivery record scoped to the current team.
3. Treat every test delivery and update-triggered delivery as a real external side effect.
4. Keep external calls outside database transactions.
5. Pass large exports and report content by reference across Temporal activity boundaries.
6. Preserve safe destination labels. Never return or log a Microsoft Teams webhook URL.
7. Keep retry and deduplication rules explicit at each queue and workflow boundary.
8. Record enough delivery state to separate configuration success from external delivery success.
9. Preserve old rows and in-flight workflows during staged deployment.
10. Add meaningful product events for user actions and delivery outcomes. Do not capture recipients, prompts, report content, or credentials.

## 5. Test the complete path

Cover each affected path through public interfaces:

- Create, read, update, pause, resume, test, expire, and delete
- Insight, dashboard, and AI prompt resources
- Email, Slack, and Microsoft Teams destinations
- Immediate, scheduled, retried, skipped, failed, and partially successful delivery
- Duplicate requests, concurrent tests, workflow retries, and uncertain responses
- Missing owner, removed source, disconnected integration, revoked permission, and invalid webhook
- Free-plan limits, organization-wide summary limits, AI approval, and exhausted AI credits
- API scopes, resource access, secret masking, and delivery history redaction
- Old frontend with new backend and old worker with new workflow payloads
- MCP schema and generated types after serializer changes

Do not treat API acceptance or workflow queueing as delivery success.
Use a mock destination or test transport for external delivery checks.

## 6. Code map

| Concern | Start here |
| --- | --- |
| API, serializers, validation, delivery history | `ee/api/subscription.py` |
| Subscription and delivery models | `products/exports/backend/models/subscription.py` |
| Delivery workflows and activities | `products/exports/backend/temporal/subscriptions/` |
| Destination delivery and automatic disable behavior | `ee/tasks/subscriptions/` |
| Management UI and frontend logic | `products/subscriptions/frontend/` |
| MCP tool definitions | `products/subscriptions/mcp/tools.yaml` |
| API behavior tests | `ee/api/test/test_subscription.py` |
| Destination delivery tests | `ee/tasks/test/subscriptions/` |
| Workflow tests | `posthog/temporal/tests/test_subscriptions_workflows.py` |
| Published operational guidance | `products/subscriptions/skills/managing-subscriptions/` |

## Companion skills

| Skill | Use when |
| --- | --- |
| `improving-drf-endpoints` | Change the subscription viewset, serializer, or OpenAPI contract |
| `django-migrations` | Change subscription or delivery persistence |
| `adopting-generated-api-types` | Consume changed generated API types |
| `writing-kea-logics` | Change subscription Kea logic |
| `integrating-with-posthog-ai` | Change AI prompt planning or report generation |
| `adding-product-alerting` | Add condition-based delivery or shared alert infrastructure |
| `writing-tests` | Select the lowest-cost regression test |
| `writing-user-facing-copy` | Change UI, error, notification, or documentation text |
