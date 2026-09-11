# Manage Customer analytics tasks through MCP

Enable `customer-analytics-customer-tasks` for the caller, then reconnect the MCP client to discover the task tools.
Read operations require `customer_task:read`; writes require `customer_task:write`.
Existing project membership, task permissions, and linked-account visibility apply.

| Tool                             | Operation                                                                                    |
| -------------------------------- | -------------------------------------------------------------------------------------------- |
| `customer-tasks-create`          | Create a task with a name and optional description, account, assignee, deadline, and status. |
| `customer-tasks-list`            | Search and filter tasks, with limit/offset pagination.                                       |
| `customer-tasks-retrieve`        | Retrieve a task by UUID.                                                                     |
| `customer-tasks-partial-update`  | Change selected fields, including assignment and status.                                     |
| `customer-tasks-archive-create`  | Remove a task from active lists while preserving its history.                                |
| `customer-tasks-restore-create`  | Restore an archived task.                                                                    |
| `customer-tasks-activities-list` | Read the task's change history.                                                              |

`account_id` is a Customer analytics account UUID. `assigned_to_id` is a PostHog project member's user ID.
`due_at` accepts an ISO 8601 timestamp. Pass null when updating to clear an account, assignee, description, or deadline.
Omitted update fields remain unchanged. Restore an archived task before editing it.
Completed and canceled tasks must return to `open` before moving to another status.

For SQL reads, query `system.customer_tasks`. It includes archived tasks; add `archived_at IS NULL` for active tasks.
Direct SQL reads enforce task permissions and linked-account visibility, but do not require the task feature flag.
Users with task-only grants can query granted tasks without account links.
Tasks linked to accounts remain hidden until the caller can read those accounts.
Data Modeling can materialize this table through its system-table allowlist.
Refreshes include the project's tasks without per-user task or account restrictions. Warehouse-view permissions protect the materialized result.
The task API and MCP tools still require the feature flag.
Task activity history remains available through the API so historical account details can be redacted.
