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
The shared key couples service access and rotation for both surfaces. See [Workflow task signing key](../../../products/customer_analytics/backend/COMPROMISES.md#workflow-task-signing-key).
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

## Task digest content and links

Task digests read the assignee's current tasks, deadlines, and permissions when built.
Only active, assigned tasks with open or in-progress status appear.
Task and linked-account access restrictions apply to both the listed tasks and the overdue count.

**Due today** covers the full current date in the project timezone.
The email lists up to 10 tasks, shows the total beside the section heading, and shows the remaining count below the list.
The remaining count links to active tasks assigned to the email recipient with the **Today** due-date filter.
**Due this week** covers tomorrow through Friday of the current workweek; Friday and weekend digests do not include next week.
An overdue task has a deadline before the current instant, so tasks due earlier today also contribute to the overdue count.
Empty digests are skipped, but an overdue count alone is enough to send one.

Task links open the task editor using `task_id`.
The overdue link selects `status=open`, `assignee=me`, `archive=active`, and `due=overdue` on the Tasks tab.
Explicit URL filters replace locally saved filters, and the overdue cutoff is evaluated when the view loads.
The notification settings link opens the personal task digest settings.
Content generation does not schedule or send email; delivery is controlled separately.

## Task digest preferences

In **Settings > Customer analytics > Notifications**, each user can enable task digest emails and choose a send time and a cadence of **Weekdays** or **Every day**.
The time uses the project timezone shown beside the control.
The time dropdown offers half-hour choices and preserves any previously saved custom time.
Preferences are disabled by default and apply only to the current user in the project.
Use **Save** to persist changes; a failed save keeps the draft available to retry.
The same Notifications section contains the existing event stream settings, and existing event stream settings links still open it.
Task digest controls require the customer tasks feature; event stream controls retain their existing feature access.

The user-config API stores preferences in `UserCustomerAnalyticsConfig.properties.task_digest`, with `enabled`, `send_time` (`HH:MM`), and `cadence` (`weekdays` or `every_day`).
`GET` and `PATCH /api/projects/{project_id}/user_customer_analytics_config/@me/` expose this object alongside `pinned_properties`.
Omitted fields retain their stored values, including fields within `task_digest`.
Missing preferences return disabled, 09:00, and weekdays without changing other stored settings.
Scheduling and email delivery are implemented separately.

Users can configure their own digest from **Email digest** in the Tasks page header.
The modal uses the same preferences form as customer analytics notification settings.
Opening the modal records `customer analytics task digest opened`; successful saves record `customer analytics task digest preferences saved` with a `source` of `tasks` or `settings`.

## Task digest delivery

The `customer-analytics-task-digest` feature flag controls scheduled digest emails independently of Tasks and the event stream.
Enable it only for the initial rollout's recipients after verifying delivery in staging.
Disabling it stops both new scheduled sends and worker retries.

Every five minutes, the scheduler reads opted-in users in batches of 100 and enqueues users whose selected time has passed in the project timezone.
Each worker rereads preferences, membership, task permissions, and current assignments before rendering the digest.
Weekday cadence excludes Saturday and Sunday; every-day cadence includes them.
Daylight-saving changes follow the project timezone: a nonexistent time moves forward by the clock change, and a repeated time produces one digest for that local date.
Delayed work can catch up during that date, but does not send an older date's digest.

Digests use the checked-in `email/customer_task_digest.html` template through SMTP.
Configure `EMAIL_ENABLED`, the SMTP host, port, authentication, TLS settings, sender, timeout, and `SITE_URL` before enabling the flag.
Customer.io configuration alone is insufficient; there is no Customer.io template dependency for this email.
Missing SMTP configuration records a failed occurrence instead of reporting success.

The worker sends synchronously and checks `MessagingRecord.sent_at` for provider acceptance.
The campaign key contains the project ID, user ID, and local digest date.
Confirmed sends are skipped by repeated scheduler runs and worker retries.
`MessagingRecord.campaign_count` caps this occurrence at four attempts; permanent rejection marks the remaining attempts unavailable.
Temporary SMTP failures retry with backoff. A provider accepting a message does not prove inbox delivery, and a process failure between acceptance and committing the record can still duplicate a message.

`customer_analytics.task_digest.delivery` records acceptance, temporary failure, retry exhaustion, permanent rejection, and missing configuration.
`customer_analytics.task_digest.send_delay` measures the delay from the configured time to acceptance.
These metrics have no task content, account names, or recipient email labels.
Before a limited rollout, use test users in staging to verify a received email, current permission and opt-out checks, duplicate suppression, and the flag's kill switch.
No production verification is implied by local tests.
