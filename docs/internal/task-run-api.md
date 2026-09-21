# Create tasks and start runs

`POST /api/projects/{team_id}/tasks/` creates a task without starting a run by default.
Set `start_run` to `true` to create the task and start its first background run in one request.
This mode uses the `tasks-mcp-agent-run-start` feature flag and the internal-project restriction.
Sandbox tokens cannot start another cloud run.
This restriction also applies to warm creation, warm activation, warm resumes, and cloud resumes.
Requests through a PostHog connection keep the sandbox origin and the same run restrictions.
The origin marker does not grant sandbox access.
PostHog Desktop access, runtime access, and usage limits still apply.
Repository-backed report discussions also require Desktop access.

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
The `state` field must be a JSON object.

## Event delivery

Cloud runs send live events through event ingest. Clients can replay only events mirrored into the backend stream.
Presence-gated runs do not mirror events while no reader is attached.
Reload the run's session logs to recover agent output.
Refetch the run for its current state because run-state and progress frames are not in those logs.
When event ingest is enabled, the agent server does not also retain events for a disconnected SSE client.
An attached SSE client still receives live events.
Runs without event ingest buffer events until an SSE client attaches.
The Claude adapter forwards partial tool inputs without retaining each intermediate snapshot in session history.

## Run summaries

`PATCH /api/projects/{team_id}/tasks/{task_id}/runs/{run_id}/set_summary/` replaces the run's progress summary.
Send a JSON object with a `summary` string of 1 to 1,500 characters after trimming whitespace.
The endpoint requires permission to control the task. A task-bound sandbox token can update only its own task.
The update does not complete the run or change its structured `output`.
Cloud agent runs write the summary through the `task_summary_update` local tool; local Desktop sessions do not have the tool.
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
They are not available to sandbox tokens.
These operations are not idempotent. If a response is lost, inspect the task and its runs before you retry.
