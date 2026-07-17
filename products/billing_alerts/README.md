# Billing alerts

Billing alerts are organization-scoped and use `execution_team_id` only as the Team that owns HogFunction execution.

`backend:contract-check` is intentionally off for now. Core still imports the product's Temporal registration surface for worker and schedule setup, so product lint treats this as a legacy interface leak. Keep the narrow `tach.toml` interface in place, and enable the contract check once Temporal registration moves behind a fully isolated product boundary.

The UI still mounts from the organization Billing tab and reuses billing access/context from `frontend/src/scenes/billing/billingLogic`, so that shared billing surface should get product-local contracts before the Billing tab itself moves.

Scheduled evaluation follows the shared alert delivery barrier: evaluate and produce every alert in the activity batch, flush once, acknowledge each producer result, then persist each lifecycle outcome in a short transaction.

The product-local creation flow is intentional. The shared `AlertWizard` creates one HogFunction from one sub-template, while billing atomically creates a four-event destination group for firing, resolved, errored, and broken notifications through the shared backend destination builders. Billing can adopt the shared wizard once it supports backend-managed destination groups.
