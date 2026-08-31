# Wizard runs

The Wizard is a setup agent distributed as an npm package.
A Wizard run records one execution of that agent inside a user-provided workspace.

## Environments and workspaces

V0 supports two configurations:

| Environment | Workspace                                | Execution                           |
| ----------- | ---------------------------------------- | ----------------------------------- |
| `local`     | Local folder with a `project_name`       | The user's machine                  |
| `cloud`     | GitHub repository in `owner/name` format | A PostHog-provisioned Wizard Worker |

The request uses explicit `environment` and `workspace.type` discriminators.
The backend rejects unsupported combinations before creating a run.

Uploaded archives are not part of V0.
They will use object-storage references rather than archive bytes in Postgres or Temporal payloads.

## Lifecycle

A local run starts in `running` because the local agent creates it after starting.
A cloud run starts in `created` before its Temporal workflow is dispatched.

Valid transitions are:

```text
created -> running
created -> failed
created -> cancelled
running -> completed
running -> failed
running -> cancelled
```

`completed`, `failed`, and `cancelled` are terminal.
Failed runs can include a typed error code.
Successful output is represented by Run Artifacts rather than an outcome field.

## API

Run endpoints are scoped to the project in the URL:

```text
GET   /api/projects/{project_id}/wizard/runs/
POST  /api/projects/{project_id}/wizard/runs/
GET   /api/projects/{project_id}/wizard/runs/{run_id}/
PATCH /api/projects/{project_id}/wizard/runs/{run_id}/
GET   /api/projects/{project_id}/wizard/runs/{run_id}/artifacts/
```

The PATCH request accepts a terminal `status`: `completed`, `failed`, or `cancelled`.
Failed runs can also include an `error_code`.
Local agents can create runs and update runs they created.
Cloud creation requires a signed-in browser session and enabled cloud execution.
Cloud lifecycle updates are owned by the Wizard Worker.

Run lookups, transitions, and artifact access verify the project boundary.
A user cannot update another user's local run.

## Cloud execution

Cloud creation verifies that the project has a GitHub integration with access to the requested repository.
The check runs again when execution starts because access can change while a run is queued.

After the database transaction commits, the backend starts a Temporal workflow with only the project ID and run ID.
The provisioning activity marks the run as `running` before it creates the Wizard Worker.
The handoff activity marks the run as `completed` after it persists the Run Artifacts.
If a worker activity exhausts its retries or the workflow is canceled, one finalization activity records the terminal state.
Sandbox cleanup does not change a completed run if cleanup fails.

The Worker:

1. Resolves short-lived GitHub and Wizard credentials inside the activity.
2. Provisions an isolated sandbox through the generic Tasks sandbox facade.
3. Clones the repository.
4. Runs the headless Wizard against the prepared workspace.
5. Captures a binary Git diff.
6. Creates a signed commit and opens or reuses a pull request when the workspace changed.
7. Destroys the sandbox.

Tokens do not enter Temporal inputs, workflow history, run metadata, or logs.
Wizard owns the Worker command, environment, credentials, resource limits, timeouts, and diff behavior.
Tasks provides only generic repository-token and sandbox helpers through public facades.

## Run Artifacts

V0 stores a non-empty Git diff in object storage.
The database stores its object-storage path, byte size, SHA-256 hash, type, project, and run relationship.
The public API returns artifact metadata and does not return diff bytes through Temporal.

No artifact is created when the workspace has no changes.
For a Git-repository workspace with changes, V0 also stores the pull request URL, number, repository, source branch, and target branch.
Updated archives remain a future artifact type.

## State synchronization

The existing Wizard session endpoint remains active during migration:

```text
POST /api/projects/{project_id}/wizard/sessions/
```

Wizard sessions remain independent from Wizard runs in V0.
They continue to synchronize the setup agent's legacy workflow and skill state without a run ID.

The existing `/api/wizard/cloud_run` onboarding flow remains Tasks-backed until its TaskRun progress and pull-request UI have a replacement based on Wizard runs and Run Artifacts.
