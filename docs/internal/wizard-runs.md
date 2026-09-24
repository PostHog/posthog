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
PUT   /api/projects/{project_id}/wizard/runs/{run_id}/tasks/
GET   /api/projects/{project_id}/wizard/runs/{run_id}/tasks/
GET   /api/projects/{project_id}/wizard/runs/{run_id}/stream/
```

Run responses include the creator ID and basic creator details for attribution in project-level run lists.
Use `GET /api/projects/{project_id}/wizard/runs/?status=created,running&limit=5` to fetch the newest active runs; `count` gives the total number of active runs in the project. The `status` filter also accepts any individual run status.
The app-wide sync widget polls this summary and also fetches the five most recently created completed runs with `?status=completed&limit=5`.
It opens one event stream for the displayed active run. Completed runs do not open a stream.
It shows the newest active run by default, or the newest completed run when none are active.
The selector lists up to five active and five completed runs by workspace and status, with the selected run marked and the total active count shown separately.
The Wizard page lists any others. A manual selection stays in place while that run remains in either list, including when it completes.
Its card shows the current task, run stages, elapsed time, environment, and workspace. "Close" hides the current run until the page reloads, while "Don't show this run again" hides that run in this browser. New runs still show the widget, and run details remain on the Wizard page. Recent completed runs remain available after reloading unless dismissed.
The `wizard-run-sync` feature flag switches the authenticated shell from the session sync widget to the run sync widget.

The PATCH request accepts a terminal `status`: `completed`, `failed`, or `cancelled`.
Failed runs can also include an `error_code`.
Local agents can create runs and update runs they created.
The browser does not offer cancellation for local runs because the server cannot stop a local Wizard process. Users stop those runs in their terminal.
These operations accept OAuth tokens with `wizard_run:write`; browser sessions can also create and manage runs.
Run creation uses the existing per-user creation throttle for both environments.
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

The Worker passes the existing run ID to the setup agent through `POSTHOG_WIZARD_RUN_ID`.
The agent uses that ID to publish task snapshots instead of creating another run.
The Worker owns the cloud run's stages and terminal status.

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

### AI gateway URLs

`WIZARD_GATEWAY_URL` is the gateway address returned to the setup agent.
`WIZARD_GATEWAY_MINT_URL` optionally sets a separate address for the backend's token-mint requests and defaults to `WIZARD_GATEWAY_URL` when unset.
For local Docker sandboxes, set `WIZARD_GATEWAY_URL=http://host.docker.internal:8080` and `WIZARD_GATEWAY_MINT_URL=http://localhost:8080` in PostHog's `.env.local`.
Restart the backend after changing these settings.

### Distributed tracing

Cloud runs use the shared OpenTelemetry instrumentation described in the [distributed tracing guide](https://posthog.com/docs/distributed-tracing).
The request's trace context passes through the Temporal client's headers into the workflow and its activities.
The worker enables Temporal's replay-safe tracing plugin for `WIZARD_TASK_QUEUE` when `OTEL_SERVICE_NAME` is configured.
The plugin records workflow and activity durations, including separate activity attempts.

Wizard spans add the following detail to the trace waterfall:

| Span prefix          | Operations                                                                                                               |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `wizard.run`         | Creation, dispatch, cancellation                                                                                         |
| `wizard.worker`      | Credential creation, provisioning, CPU sampler startup, usage measurement                                                |
| `wizard.sandbox`     | Sandbox creation and destruction                                                                                         |
| `wizard.repository`  | Access checks, credentials, clone, remote cleanup, staging, diff capture, handoff reading, commit, pull request creation |
| `wizard.package`     | Local source archive, upload, build                                                                                      |
| `wizard.cli.execute` | The sandbox command that installs and runs the setup agent                                                               |
| `wizard.artifacts`   | Diff persistence                                                                                                         |

Find a run using the `wizard.run_id` attribute on its creation, dispatch, and activity spans, then open the full trace.
These spans also carry `team_id`.
Clone spans include `process.exit.code`; diff persistence spans include `wizard.diff.size_bytes`.
Custom Wizard spans record error types and error status without recording exception messages, command output, repository contents, or credentials.
Every Wizard activity replaces failure messages with a fixed message before Temporal records the failure.
The replacement preserves the error type and retry settings, but drops details and exception chains so automatic Temporal spans cannot export sandbox output.
Cancellation exceptions keep their cancellation semantics.

The CLI runs in a separate sandbox process and is distributed from another repository.
Its internal agent steps are represented by the duration of `wizard.cli.execute`; they do not emit child spans from this instrumentation.
Recovery dispatches that start outside the original request can produce another trace, correlated by `wizard.run_id`.

Configure `OTEL_SERVICE_NAME` and the existing OTLP collector endpoint on both the web service and the Wizard Worker.
The shared Python exporter sends gRPC to the collector; configure that collector to forward traces to PostHog's HTTP `/i/v1/traces` endpoint with its project token.
The [Python installation guide](https://posthog.com/docs/distributed-tracing/installation/python) describes the HTTP exporter configuration for direct clients.
Check web-service sampling when validating a run: a parent trace that is not sampled also suppresses its child spans.
For a controlled validation environment, use `OTEL_TRACES_SAMPLER=always_on`, create a cloud run, and confirm its activity spans and cleanup appear in one trace.

### Worker deployment

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

The setup agent sends its complete task snapshot to `PUT /api/projects/{project_id}/wizard/runs/{run_id}/tasks/`:

```json
{ "tasks": [{ "name": "Install SDK", "status": "running" }] }
```

The endpoint requires an OAuth token with `wizard_run:write` for the user who created the run.
Add `wizard_run:write` to the Wizard OAuth application's scope ceiling before switching the agent to these endpoints.
Agents that read snapshots also need `wizard_run:read`.
Existing tokens need these grants through renewed authorization; the backend does not widen them automatically.
It returns `204` with no body.
Both local and cloud agents write to their assigned run ID.
Task names must be unique within the snapshot and remain stable between updates: renaming a task creates a new task identity.
Each snapshot replaces the stored list, preserves its order, and removes omitted tasks.
An empty list clears the snapshot.
A snapshot accepts up to 100 tasks, with names up to 255 characters.
Task statuses are `created`, `running`, `completed`, and `failed`.
Multiple tasks may run at once, and a snapshot does not need to contain a running task.
Task statuses do not change the run's lifecycle status.

`GET /api/projects/{project_id}/wizard/runs/{run_id}/tasks/` returns the full list as `{"tasks": [...]}` without pagination.
Browser sessions and tokens with `wizard_run:read` can read the list within their project.
Each task includes `name`, `status`, `created_at`, `started_at`, `completed_at`, `failed_at`, and `error_message`.
The server preserves the first-observed timestamp for each state while the task remains in the snapshot.
A task first received as completed has no known start time, so `started_at` remains null.
The input does not include failure details; `error_message` remains null.
Timestamps use the server clock and are returned as ISO 8601 strings.
Snapshots are reconciled under a row lock so concurrent updates preserve recorded timestamps.
The server applies snapshots in arrival order; clients must await each update before sending the next.

The run's `stream/` endpoint requires a browser session and emits an initial state followed by updates after committed task, status, or stage changes.
Each SSE `data` event contains `tasks`, `status`, `stage`, `error_code`, `error_message`, `updated_at`, `started_at`, and `finished_at`.
Immutable run fields such as `id` are omitted.
Redis notifications are scoped by project and run ID, and each notification reloads the committed state.
Fanout is best effort: reconnecting reads the latest state, and GET remains available if a notification is missed.
The stream sends heartbeat comments and rotates after 15 minutes with `event: end` and `data: reconnect`.
It uses the existing `onboarding-wizard-sync-killswitch` flag; an enabled flag returns `204` so EventSource stops reconnecting.
Use EventSource rather than the generated fetch wrapper to consume the stream.

The existing Wizard session endpoint remains active during migration:

```text
POST /api/projects/{project_id}/wizard/sessions/
```

Wizard sessions remain independent from Wizard runs in V0.
They continue to synchronize the setup agent's legacy workflow and skill state without a run ID.

The existing `/api/wizard/cloud_run` onboarding flow remains Tasks-backed until its TaskRun progress and pull-request UI have a replacement based on Wizard runs and Run Artifacts.
