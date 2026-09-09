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
Task activity history remains available through the API so historical account details can be redacted.
