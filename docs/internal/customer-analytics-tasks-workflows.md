# Create customer tasks from workflows

In the workflow editor, add **Customer analytics > Create task**. Enter a task name and optionally a description, an account UUID, an assigned project member's user ID, and an ISO 8601 due date. All fields support workflow variables. For **Account** and **Assignee**, choose **Raw** to enter an ID or workflow expression, or **Picker** to select an account or project member using the same pickers as the task modal. Switching modes preserves the current value. A **Get account** step can supply the account UUID in raw mode.

Tasks start with the **Open** status. The created task ID is available as the step's output, including on a retry. Each invocation and action creates at most one task while that task exists; separate actions and workflow runs create separate tasks. Retrying does not overwrite an existing task.

Creation runs with the workflow owner's current customer task permissions. The owner must remain active, retain access to the workflow project and its canonical project, and have editor access to customer tasks. Account visibility and assignee eligibility match ordinary task creation. A child project's tasks are stored in its canonical parent project. The customer tasks feature flag must be enabled for the workflow owner.

## Deployment

Provision the same dedicated `CUSTOMER_TASKS_CREATE_JWT_SECRET` in Django and the workflow worker before enabling the action in production. Django accepts comma-separated verification keys for rotation; the worker signs with its configured key. Development and test environments use the matching local default. The action fails closed when its signing key is missing.

The worker calls `POST /api/projects/{team_id}/workflow_customer_tasks/` through `INTERNAL_API_BASE_URL`, with a short-lived service token scoped to the project, workflow, and invocation/action key. The call goes directly to the backend, avoiding login redirects on the public app URL. Redirects and responses without a valid task UUID fail the workflow step. User API credentials and tokens for other actions cannot call this endpoint. No database migration is required.

For local development, set `INTERNAL_API_BASE_URL` to the address where the backend listens. Linux devboxes may bind to the Docker bridge address, such as `http://172.17.0.1:8000`, instead of localhost. Restart the dev processes after changing the local environment.
