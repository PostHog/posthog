# Create tasks and start runs

`POST /api/projects/{team_id}/tasks/` creates a task without starting a run by default.
Set `start_run` to `true` to create the task and start its first background run in one request.
This mode uses the `tasks-mcp-agent-run-start` feature flag and the internal-project restriction.
A sandbox token can start a background agent run through `start_run` or the task `run` endpoint, within these rules:

- The token must be bound to a run of a task that the token's user created. Otherwise the response is `403` with code `no_actor`.
- A run that a sandbox started cannot start more runs, and neither can a resume of that run. A sandbox also cannot start a run of its own task. These cases return `403` with code `nested`.
- Every other gate runs as the token's user: the internal project, the `tasks-mcp-agent-run-start` feature flag, Desktop access, usage limits, and task visibility.
- One parent run can start up to 10 runs. A start that fails gives its slot back. Past the cap, the response is `429` with code `agent_run_fanout_cap`.
- Each user has hourly and daily limits on runs that sandboxes start. Past them, the response is `429` with code `agent_run_rate_limited`.
- The new run is always a background run. Its state records `agent_parent_task_id` and `agent_parent_run_id`, and callers cannot change or remove them.

Sandbox tokens still cannot start runs through warm creation, warm activation, warm resumes, cloud resumes, or the endpoints under `/tasks/{task_id}/runs/`.
Requests through a PostHog connection keep the sandbox origin and the same run restrictions.
The origin marker does not grant sandbox access.
PostHog Desktop access, runtime access, and usage limits still apply.
PostHog Code's per-user gateway caps are disabled by default and apply only to configured users when enabled.
Repository-backed report discussions also require Desktop access.
Opening Ask AI on a Self-driving inbox report warms a task sandbox for the discussion.

The response has status `201` and contains the task and its `latest_run`.
If task creation succeeds but run creation or dispatch fails, the response also contains `run_error`.
Keep the task ID and inspect its runs before you retry.
Do not repeat task creation to recover from a run failure.
If a database read fails after dispatch, the response still includes the created run.

`branch` selects the base branch for the first run.
Optional run hints can be `null`.
Pi runs reject ACP runtime, model, reasoning-effort, and permission-mode hints.
The combined request rejects `pending_user_artifact_ids` before it creates a task.
It also rejects inaccessible sandbox environments and custom images before task creation.
Custom images must be ready.
It also rejects signal-report tasks before creation so caller-selected origins cannot grant full MCP permissions.
Create these tasks without `start_run`, then start them through the report workflow.
To attach files, first create the task, then upload the files, then start its run.

`POST /api/projects/{team_id}/tasks/{task_id}/run/` starts a run for an existing task.
Its response includes `run_error` if workflow dispatch fails.
A resumed run keeps its previous base branch and agent source.
The server stores the base branch in `pr_base_branch`, including `null` for the repository default.
Resumes use only this protected value, not the editable run branch or `state.branch`.
Older runs without a stored base branch use the repository default.
Cloud resumes of agent-sourced runs require the agent-run feature flag and the internal-project restriction.
Warm resumes of agent-sourced runs return an empty response without creating a sandbox.
Agent-sourced runs do not reuse warm sandboxes.
A request may send the previous base branch or a branch that run worked on; any other branch is refused.
The bootstrap endpoint, `POST .../tasks/{task_id}/runs/`, does not accept the agent source.
Agent-sourced runs use the read-only MCP permission preset.
Run state updates cannot change or remove the run source or base branch.
The Slack actor fields `interaction_origin`, `slack_actor_user_id`, and `slack_actor_slack_user_id` are server-owned and cannot be changed, removed, or appended through run state updates.
The `state` field must be a JSON object.

Run responses omit internal cost accounting, including gateway request IDs.

GitHub credentials that require user action fail the run without retrying. Fresh runs and resumed sandboxes preserve the actionable error, and Temporal does not report these expected failures to error tracking.

Sandbox GitHub tokens are scoped to the repositories requested by the run. When GitHub rejects a repository scope, the run refreshes installation access and resolves renamed repositories by their GitHub ID. Public repositories outside the installation can be cloned anonymously; private or missing repositories require the user to check repository access. Public-only access results are cached for five minutes before checking again. GitHub outages and connection failures remain retryable, including failures during token refresh.

Without an authenticated GitHub token, the agent can still read public repositories and repository files already in its workspace. It asks the user to connect GitHub when the work requires unavailable private repository or publishing access.

## Model selection

Task runs accept `gpt-6.1-sol` with the `codex` runtime adapter and `low`, `medium`, `high`, `xhigh`, or `max` reasoning effort.
The bundled Codex 0.164.0 runtime supports this model with ChatGPT subscription billing.
The task model catalog supplies the web and Desktop pickers with the model name, reasoning levels, and public price comparison.
The gateway must list the model for the task's product before the picker offers it.
Adding the model does not change the default model or the capability slider.

## Event delivery

Cloud runs send live events through event ingest. Clients can replay only events mirrored into the backend stream.
Presence-gated runs do not mirror events while no reader is attached.
Reload the run's session logs to recover agent output.
Refetch the run for its current state because run-state and progress frames are not in those logs.
When available, sandbox provisioning records the installed agent package version in run state for terminal analytics events.
Failures before sandbox creation have no agent version.
When event ingest is enabled, the agent server does not also retain events for a disconnected SSE client.
An attached SSE client still receives live events.
Runs without event ingest buffer events until an SSE client attaches.
The Claude adapter forwards partial tool inputs without retaining each intermediate snapshot in session history.
Budget-steer notifications remain in the event stream.
The standalone agent-proxy asks the authenticated Django callback to queue each steer for analytics and retries a failed dispatch.
Direct Django ingest queues the same work without a callback, so analytics delivery does not delay later stream events.
A Celery task captures the event and retries upload failures up to five times with backoff.
Both paths preserve the event timestamp and derive the analytics event ID from the run and event sequence.
If an older payload has no timestamp, Django stores its first received time for retries and replays.
Successful captures are recorded for the event ingest token's lifetime so completed work is skipped on replay.

Interactive permission requests and questions can send a mobile push notification to the run's creator.
Event ingest, the agent-proxy callback and the sandbox relay share a notification gate keyed by run and permission request ID.
The gate retains each request for 24 hours after its push is successfully enqueued, so reconnecting does not repeat that notification.
This also applies when implementation or research work routes the push through report notifications.
Enqueue failures and transaction rollbacks leave only the short cooldown, allowing a later callback or relay replay to retry.
Requests share a 30-second per-run cooldown, applied before allocating a request deduplication key.
The push dispatcher also shares its per-run cooldown with turn-end awaiting-input notifications.
Permission request IDs must be non-empty and no longer than 200 characters.

## Run summaries

`PATCH /api/projects/{team_id}/tasks/{task_id}/runs/{run_id}/set_summary/` replaces the run's progress summary.
Send a JSON object with a `summary` string of 1 to 1,500 characters after trimming whitespace.
The endpoint requires permission to control the task. A task-bound sandbox token can update only its own task.
The update does not complete the run or change its structured `output`.
Cloud agent runs write the summary through the `task_summary_update` local tool; local Desktop sessions do not have the tool.
The tool belongs to the sandbox harness, so an agent calls it as `mcp__posthog-code-tools__task_summary_update`.
It is not in the PostHog MCP catalog, so tool discovery through the `mcp__posthog__exec` dispatcher never returns it.
Generic run-state updates cannot change the summary or its inherited value.

A resumed run uses its source run's summary until it saves a new summary.
Task details, paginated task lists, and task summaries include the effective `task_summary`.
Workflow summaries are visible only to the task owner or its authorized sandbox agent.
Shared workflow stream events always set `task_summary` to `null`.
Other task streams include the effective summary.

## MCP tools

- `tasks-create` creates an idle task. It does not accept run-start inputs.
- `tasks-create-and-run` creates a task and starts its first run.
- `tasks-run-create` starts a run for an existing task.

The two run-start tools require the agent-run feature flag.
Sandbox tokens can use them only within the sandbox rules above.
These operations are not idempotent. If a response is lost, inspect the task and its runs before you retry.

## Mobile notifications and task pickup

Use `X-PostHog-Client-Platform: mobile` to identify mobile requests.
Tasks created on mobile can send task notifications.
A successful mobile run start, resume, user message, or permission response also enables notifications for that user.
Reads, presence updates, configuration changes, and failed actions do not enable notifications.
This choice persists when the user returns to the web app.

Continuing a task on mobile stops that user's automatic Slack mentions and proactive private-thread updates.
Shared replies and answers to direct Slack requests remain available.
This includes replies that restart a completed task.
Other participants keep their notifications.

Task notifications cover run results, input requests, replies, handoffs, and verified PR merges or closes.
Active task presence suppresses notifications on those devices.
The server prevents duplicate PR outcome notifications.

Report notifications cover new reports, work updates, and PR review or outcome updates, regardless of task origin.
Active presence in the report's implementation or research task suppresses its work-update notifications across that user's devices.
Report discussions use task notification preferences.
Reports with `output_destinations.inbox: false` do not send notifications.
Report notifications require `posthog-code-mobile-push`.
Ordinary task notifications do not require this flag.

`PATCH /api/users/@me/` sets four booleans under `notification_settings`:

| Key                                  | Controls                 |
| ------------------------------------ | ------------------------ |
| `mobile_push_enabled`                | All mobile notifications |
| `mobile_push_tasks_enabled`          | Chat and task updates    |
| `mobile_push_reports_enabled`        | New reports              |
| `mobile_push_report_updates_enabled` | Report updates           |

All four default to `true`.
The delivery worker checks that the account is active, along with current preferences and access, before it sends a queued notification.
Task notifications require current viewer access to the task resource when queued and when delivered.
