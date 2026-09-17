# Create customer tasks from workflows

In the workflow editor, add **Customer analytics > Create task**. Enter a task name and optionally a description, an account UUID, an assigned project member's user ID, and an ISO 8601 due date. All fields support workflow variables. For **Account** and **Assignee**, choose **Raw** to enter an ID or workflow expression, or **Picker** to select an account or project member using the same pickers as the task modal. Switching modes preserves the current value. A **Get account** step can supply the account UUID in raw mode.

Tasks start with the **Open** status. The created task ID is available as the step's output, including on a retry.
New workflow runs create at most one task per action visit while that task exists.
A retry returns the same task ID without changing the task. A loop that visits the action again creates another task.
An empty or null assignee creates an unassigned task.

New task creation runs with the workflow owner's current customer task permissions.
The owner must be active, retain access to the workflow project and its canonical project, and have editor access to customer tasks.
Account visibility and assignee eligibility match ordinary task creation. A child project's tasks are stored in its canonical parent project.
The customer tasks feature flag must be enabled for the workflow owner.

An authenticated retry returns an existing task's UUID even if the workflow was deleted, the owner's access changed, or the flag was disabled.
The retry must still pass token verification and match the project, workflow, and invocation key.
This response does not grant access to task contents. Requests for new tasks still pass all creation checks.

## Deployment

Task creation reuses `CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRET`, the signing key for account actions.
Configure matching keys in Django and the workflow worker before enabling the action in production.
Both accept comma-separated keys for rotation. The worker signs with the first key, and Django verifies against all keys.
Development and test environments use the matching local default.

New runs record their task key version before execution. Retries and manual reruns preserve that version and the action visit count.
Runs created without a version retain their original run-and-action keys, even if no function state was saved before a worker restart.
Those legacy runs create at most one task per action, including across loop visits.
Start a new workflow run to use per-visit task creation.

Task tokens retain their own `posthog:customer-tasks:create` audience. Account tokens cannot call the task endpoint.
The shared key couples service access and rotation for both surfaces. See [Workflow task signing key](../../products/customer_analytics/backend/COMPROMISES.md#workflow-task-signing-key).
Task creation fails when the shared key is missing. Unlike account actions, it has no fallback to the project secret API token.

The worker calls `POST /api/projects/{team_id}/workflow_customer_tasks/` through `INTERNAL_API_BASE_URL`, with a short-lived service token scoped to the project, workflow, and invocation/action key. The call goes directly to the backend, avoiding login redirects on the public app URL. Redirects and responses without a valid task UUID fail the workflow step. User API credentials and tokens for other actions cannot call this endpoint. No database migration is required.

For local development, set `INTERNAL_API_BASE_URL` to the address where the backend listens. Linux devboxes may bind to the Docker bridge address, such as `http://172.17.0.1:8000`, instead of localhost. Restart the dev processes after changing the local environment.

## Backend ownership

Customer analytics registers the endpoint in `products/customer_analytics/backend/routes.py`.
The HTTP view lives in `products/customer_analytics/backend/presentation/views/workflow_customer_tasks.py` and delegates creation to `backend/facade/workflow_customer_tasks.py` in the same product.
That facade reads the workflow owner ID through `products/workflows/backend/facade/api.py`.
Only Workflows queries the workflow model.
The URL and basename stay unchanged.
The view pins its OpenAPI product attribution to `workflows` but remains excluded from generated API docs.
