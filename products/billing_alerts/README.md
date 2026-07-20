# Billing alerts

Billing alerts are organization-scoped and use `execution_team_id` only as the Team that owns HogFunction execution.

`backend:contract-check` is intentionally off for now. Core still imports the product's Temporal registration surface for worker and schedule setup, so product lint treats this as a legacy interface leak. Keep the narrow `tach.toml` interface in place, and enable the contract check once Temporal registration moves behind a fully isolated product boundary.

Scheduled evaluation follows the shared alert delivery barrier: evaluate and produce every alert in the activity batch, flush once, acknowledge each producer result, then persist each lifecycle outcome in a short transaction.

Billing follows the Logs alerting pattern: billing owns its evaluation rules, persistence adapter, and lifecycle message definitions. The shared alerting infrastructure handles lifecycle decisions, scheduling, grouped destination persistence, and event delivery.

The MCP server exposes atomic create and partial-update tools for billing alert configuration. They use the existing organization write scope and retain the API's organization Admin or Owner permission check.

The Billing tab uses the shared alert editor, destination editor, advanced options, next-evaluation status, and evaluation-history chart from `products/alerts`. Billing supplies its own form, threshold labels, value formatting, API calls, and notification destination payloads.
