# Wizard runs

The Wizard is a setup agent distributed as an npm package.
A Wizard run records one execution of that agent inside a user-provided workspace.

## Concurrent creation

Cloud run creation holds a PostgreSQL transaction advisory lock for the project and user.
The lock covers the active-run check, rolling hourly and daily limits, and run insertion.
Concurrent requests for the same project and user wait until the first transaction commits or rolls back.
The lock does not lock the `Team` row or serialize different users or projects.
Local runs do not take this lock. Cloud dispatch starts after commit.

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

Run responses include the creator ID and basic creator details for attribution in project-level run lists.

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
5. Replaces the Git index with publishable changes and captures a binary Git diff.
6. Creates a signed commit and opens or reuses a pull request when the workspace changed.
7. Destroys the sandbox.

The publish step excludes ignored files, private environment files, agent instruction files, skills, common credentials, private keys, and new generated directories.
It includes generated directories that the repository already tracks.

Tokens do not enter Temporal inputs, workflow history, run metadata, or logs.
Wizard owns the Worker command, environment, credentials, resource limits, timeouts, and diff behavior.
Tasks provides only generic repository-token and sandbox helpers through public facades.

## Analytics compatibility

Cloud lifecycle events keep their existing names and deterministic event UUIDs.
They add the legacy properties `run_surface`, `project_id`, `version`, and `command`.
The existing `environment`, `team_id`, `wizard_version`, and `wizard_run_id` properties remain available.
`event_source` distinguishes `wizard_run_service` events from `wizard_ui` events.

The pinned Wizard CLI reads `POSTHOG_TASK_RUN_ID` and attaches it as `task_run_id` to its events.
Cloud workers pass the Wizard run ID through this existing variable.
Cloud service and UI events also include this `task_run_id` alias, so these events can join the CLI events.
The alias does not refer to a Tasks record. No `POSTHOG_TASK_ID` is supplied.
Local runs do not get the cloud alias.
The CLI keeps its separate, process-level `run_id`.

The CLI remains the only source of `setup wizard finished`.
Its `status` values remain `success`, `error`, and `cancelled`.
Service completion events describe the full cloud lifecycle, including failures before CLI startup and failures during repository publication.
Do not add the CLI and service completion events together when counting runs.

The UI records library opens, successful command copies, create requests and outcomes, retry selections, run views, and diff opens.
It also records confirmed cancellation requests and outcomes.
Polling does not create more view events. Clipboard failures do not count as command copies.
Use `wizard run create requested` and `wizard run create failed` to measure request failures, including limit responses.
Use `wizard_run_id` to join successful creation to existing lifecycle events, `wizard pull request created`, and `wizard run diff opened`.
Events omit repository names, paths, full shell commands, diff contents, tokens, and raw error messages.

## Deployment configuration

The production rollout depends on the [Wizard Worker chart](https://github.com/PostHog/charts/pull/14662) and [cloud infrastructure](https://github.com/PostHog/posthog-cloud-infra/pull/10081) changes.
The chart must run a worker that polls `wizard-task-queue` before cloud run creation is enabled.
`WIZARD_RUN_ARTIFACTS_S3_BUCKET` must identify the provisioned artifact bucket.
`WIZARD_RUN_CREATE_THROTTLE_RATE` and `WIZARD_RUN_READ_THROTTLE_RATE` can override the default API limits.
`LOCAL_WIZARD_ROOT` only enables local source uploads when Django runs in debug mode.

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
