---
name: debugging-table-access-denied
description: >-
  Debugs a TableAccessDeniedError from an error tracking issue, Slack alert, or user report. Use when investigating why HogQL denied a system or warehouse table and whether the occurrence is a real bug or expected behavior. Trigger terms include TableAccessDeniedError, table_access_denied, and "You don't have access to table".
---

# Debugging "You don't have access to table"

`TableAccessDeniedError` (`posthog/hogql/errors.py`, code `table_access_denied`) means the query referenced a table that access control removed from the HogQL schema.
The mechanism — how and why tables get removed — is documented in [`posthog/hogql/ACCESS_CONTROL.md`](../../../posthog/hogql/ACCESS_CONTROL.md); read it first.

Hints:

- The error proves the table exists and was denied. A nonexistent table raises `Unknown table` instead.
- On an HTTP request this is an expected 4xx, never captured. An error tracking issue means it was raised in a background context — figure out which from the event's query tags (`team_id`, `user_id`, `product`, `celery_task_id`, `temporal.*`).
- A `system.*` name is a system-table decision; a bare name is a warehouse table/view denial.
- No `user_id` on the event usually means a userless `Database.create_for` — it fails closed, and `bypass_warehouse_access_control` does not cover system tables. That's a bug in the calling code.
- Background jobs run as the resource's `created_by`; a creator who left the org is the known benign cause (cache warming, alerts, and exports already suppress capture for it via `creator_access_revoked`).
- Otherwise it's a real access rule (RBAC or entitlement) — see the readme for how a table's access level resolves, and check the `AccessControl` rows for the table's `access_scope`.
