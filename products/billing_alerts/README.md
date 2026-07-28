# Billing alerts

Billing alerts are organization-scoped and use `execution_team_id` only as the Team that owns HogFunction execution.

`backend:contract-check` is intentionally off for now. Core still imports the product's Temporal registration surface for worker and schedule setup, so product lint treats this as a legacy interface leak. Keep the narrow `tach.toml` interface in place, and enable the contract check once Temporal registration moves behind a fully isolated product boundary.

The UI still mounts from the organization Billing tab and reuses billing access/context from `frontend/src/scenes/billing/billingLogic`, so that shared billing surface should get product-local contracts before the Billing tab itself moves.
