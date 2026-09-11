# Create tasks and start runs

`POST /api/projects/{team_id}/tasks/` creates a task without starting a run by default.
Set `start_run` to `true` to create the task and start its first background run in one request.
This mode uses the `tasks-mcp-agent-run-start` feature flag and the internal-project restriction.
Sandbox tokens cannot start another cloud run.
This restriction also applies to warm creation, warm activation, warm resumes, and cloud resumes.
PostHog Desktop access, runtime access, and usage limits still apply.
Repository-backed report discussions also require Desktop access.

The response has status `201` and contains the task and its `latest_run`.
If task creation succeeds but run creation or dispatch fails, the response also contains `run_error`.
Keep the task ID and inspect its runs before you retry.
Do not repeat task creation to recover from a run failure.

`branch` selects the base branch for the first run.
Optional run hints can be `null`.
Pi runs reject ACP runtime, model, reasoning-effort, and permission-mode hints.
The combined request rejects `pending_user_artifact_ids` before it creates a task.
It also rejects signal-report tasks before creation so caller-selected origins cannot grant full MCP permissions.
Create these tasks without `start_run`, then start them through the report workflow.
To attach files, first create the task, then upload the files, then start its run.

`POST /api/projects/{team_id}/tasks/{task_id}/run/` starts a run for an existing task.
Its response includes `run_error` if workflow dispatch fails.
A resumed run keeps its previous base branch and agent source.
A request cannot select a different base branch for the restored snapshot.
The bootstrap endpoint, `POST .../tasks/{task_id}/runs/`, does not accept the agent source.
Agent-sourced runs use the read-only MCP permission preset.
Run state updates cannot change or remove the run source or base branch.

## MCP tools

- `tasks-create` creates an idle task. It does not accept run-start inputs.
- `tasks-create-and-run` creates a task and starts its first run.
- `tasks-run-create` starts a run for an existing task.

The two run-start tools require the agent-run feature flag.
They are not available to sandbox tokens.
These operations are not idempotent. If a response is lost, inspect the task and its runs before you retry.
