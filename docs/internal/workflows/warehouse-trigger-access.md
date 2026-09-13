# Warehouse row trigger access

Saving a workflow that names a warehouse table or view requires the requesting user to have read access to that object.
This includes drafts with a selected table and activation of existing workflows.
An incomplete draft can omit the table name, but it cannot receive rows.
Archiving a workflow remains possible after access is removed.
API keys and OAuth tokens also need the corresponding `warehouse_table:read` or `warehouse_view:read` scope; the matching write scope or full access also suffices.

Before creating warehouse-triggered runs, the worker checks the workflow creator's current access to the event's actual source table or view.
Django resolves objects within the event's project and applies the same object, source, and project access checks used for warehouse reads.
A missing or inactive creator, removed project access, deleted source, or revoked object access prevents delivery.
The materialization-status notification trigger is separate from these full-row triggers.

The worker groups authorization requests by project, source kind, and source name, with at most 500 workflow IDs per request.
Authorization results last only for that batch.
Permission changes apply to subsequent batches; they do not retract rows already queued or delivered.
If authorization fails or the response is invalid, the batch fails before workflow invocations are queued so the consumer can retry it.

## Deployment

The worker calls `POST /api/projects/{team_id}/workflow_warehouse_access/` with a short-lived, project-scoped service JWT.
This route accepts only the dedicated service credential and returns workflow IDs, never row contents.

Provision `WORKFLOW_WAREHOUSE_ACCESS_JWT_SECRET` in Django and the CDP workers before deploying the worker change.
Use a distinct key in each environment, including separate keys for US and EU.
Deploy the Django route before the workers that call it.
An unconfigured key or unavailable route prevents warehouse workflow delivery and leaves batches retrying.

The setting accepts comma-separated keys, newest first.
For rotation, first deploy the new and old keys to both services, then remove the old key after existing tokens expire.
Development and test environments use a shared development-only default.
