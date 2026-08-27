# Cloud runs: local setup guide

## Quickstart

1. Create a personal dev GitHub App (see [GitHub App](#github-app) below)
2. Run `python manage.py setup_background_agents`
3. Run `hogli start`
4. Open Tasks in PostHog and create a task

The setup command is idempotent — re-run it anytime. It writes the dev JWT keys
to your `.env`, creates the Array OAuth application, enables the `tasks` feature
flag for every team, and builds the agent skills bundle.

> To trigger runs from Slack (`@PostHog <task>`) instead of the UI, set up a dev Slack
> workspace and app once this guide is working — see
> [slack-local-setup-guide.md](./slack-local-setup-guide.md).

## GitHub App

Each engineer needs their own GitHub App. The setup command will print these
instructions and offer to open the creation page in your browser, but for
reference:

> **Shortcut:** `python manage.py create_github_app` automates everything below
> via GitHub's [App Manifest flow](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest).
> It opens the browser with the manifest pre-filled; on the single "Create
> GitHub App" click it writes the four `GITHUB_APP_*` values straight to your
> `.env` and verifies the key works. Add `--org <name>` to create it under an
> organization. The manual steps below remain the fallback / reference.

| Permission    | Access       | Purpose                                   |
| ------------- | ------------ | ----------------------------------------- |
| Contents      | Read & Write | Read files, create branches, push commits |
| Pull requests | Read & Write | Create and update PRs                     |
| Metadata      | Read         | Required for all GitHub Apps              |

Optional: Issues (R/W), Workflows (R/W).

Steps:

1. GitHub → Settings → Developer Settings → GitHub Apps → New GitHub App
2. Set the **Setup URL** (NOT the Callback or Homepage URL) to
   `http://localhost:8010/integrations/github/callback`
3. Set a **Callback URL** — `http://localhost:8010/complete/github-link/`
   works for the personal user-link flow used by Code. Any URL under your
   localhost is fine; the value just has to be a valid URL since it's
   required when creating the App.
4. Set the permissions above
5. Under "Identifying and authorizing users", check **Request user authorization (OAuth) during installation** — required for the personal user-link flow
6. Generate a **client secret** under "Client secrets" on the App page —
   this is required (added a couple of releases back). If your local setup
   stopped working recently, this is most likely what's missing.
7. Generate a private key
8. Install the app on your test repositories by going to `http://localhost:8010/project/1/integrations/github` and installing the GitHub Integration
9. Add to your `.env`:

```bash
# The OAuth Client ID (starts with Iv1 or Iv23) — NOT the numeric App ID.
# Both fields are visible on the GitHub App settings page; the App ID is the
# small grey number at the top, the Client ID is the labelled field below.
GITHUB_APP_CLIENT_ID=Iv1.xxxxxxxxxxxxxxxx
GITHUB_APP_CLIENT_SECRET=your_client_secret
GITHUB_APP_SLUG=your-app-slug
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
```

The app slug is the URL-friendly name in your App URL
(`github.com/apps/your-app-slug`). Literal `\n` characters in the private key are
fine — they get converted to newlines.

## Temporal worker

Temporal and the temporal-django-worker start automatically via phrocs when you
run `hogli start`.

The `process-task` workflow defined in
`products/tasks/backend/temporal/process_task/workflow.py` provisions a sandbox,
starts an agent inside it, and waits for the agent to finish. The workflow
orchestrates these activities:

1. **get_task_processing_context** — Loads the TaskRun from the database,
   validates the GitHub integration and repository, and builds a
   `TaskProcessingContext` carrying all the IDs needed by later activities
2. **get_sandbox_for_repository** — Creates an OAuth access token, provisions a
   Docker sandbox (reusing a snapshot if one exists), clones the repository, and
   stores the sandbox URL in `TaskRun.state`
3. **start_agent_server** — Runs `npx agent-server` inside the sandbox and polls
   `/health` until it responds
4. **wait_condition** — The workflow blocks with a 30-minute inactivity timeout,
   extended by `heartbeat` signals from the agent. Exits on a `complete_task`
   signal or when no heartbeat arrives within 30 minutes
5. **cleanup_sandbox** — Destroys the sandbox container (always runs, even on
   failure)

The activities live in
`products/tasks/backend/temporal/process_task/activities/`.

## Running via the UI

This is very minimal at the moment, but the tasks page can be used to see what
is happening with a background cloud run and for debugging. You can also use PostHog Desktop to do this rather than the debug UI.

1. Navigate to Tasks in PostHog (requires the `tasks` feature flag) by visiting `/tasks` (it will not show up in the sidebar)
2. Create a task with a title, description, and repository (format: `owner/repo`)
3. Click "Run task"
4. Watch logs stream in the session view

## Testing with local agent packages (you only need to do this if you are making changes to the agent package, otherwise ignore this)

To test changes to `@posthog/agent` before publishing:

### Modal credentials

Both `MODAL_DOCKER` and `modal` providers require a Modal API token.
Look up **"Modal Development Token"** in 1Password and add the values to your `.env`:

```bash
MODAL_TOKEN_ID=<token_id>
MODAL_TOKEN_SECRET=<token_secret>
```

> **Docker sandboxes derive the LLM gateway from `SITE_URL`.** It reaches the sandbox as
> `POSTHOG_API_URL`, and `getCloudTaskGatewayUrl` maps only `localhost` and
> `host.docker.internal` to the local gateway on 3308. Any other host — an ngrok domain set for
> Slack or webhook testing, for instance — falls through to the production gateway, which a local
> run token cannot authenticate against. The failure is silent: the agent boots, sends its first
> prompt, and idles until its inactivity window closes it, with nothing in the gateway or agent
> logs. If `SITE_URL` is not localhost, set
> `SANDBOX_LLM_GATEWAY_URL=http://host.docker.internal:3308` as well.

### Tunnel gateway, API, and MCP

If you run in a docker sandbox you don't need to do this. If you are testing with Modal sandboxes, since they run in the cloud and can't reach `localhost` directly,
you'll need to expose the Django API, LLM gateway, and MCP server publicly. We use [Tailscale Funnel](https://tailscale.com/kb/1223/funnel).

The eval harness sets Funnel up and tears it down automatically on a Modal run, so for evals you don't need to do any of this by hand — it only needs the daemon running and Funnel enabled (below). This section is for driving a Modal sandbox manually (e.g. from a task run).

First, install Tailscale, start the daemon, and sign in:

```bash
tailscale up
```

Then enable Funnel for the tailnet and this node in the [admin console](https://login.tailscale.com/admin/acls) (grant the `funnel` node attribute) and make sure HTTPS certificates are enabled for the tailnet. Funnel only serves three public ports — `443`, `8443`, and `10000` — which is exactly enough for the three services. Point each one at the corresponding local port:

```bash
tailscale funnel --bg --https=443 8000    # Django API
tailscale funnel --bg --https=8443 3308   # LLM gateway
tailscale funnel --bg --https=10000 8787  # MCP server
```

Find your node's public hostname (the MagicDNS name) with `tailscale status --json | jq -r .Self.DNSName`, then set the resulting URLs in your `.env` (the `443` service drops the port):

```bash
SANDBOX_API_URL=https://<node>.<tailnet>.ts.net
SANDBOX_LLM_GATEWAY_URL=https://<node>.<tailnet>.ts.net:8443
SANDBOX_MCP_URL=https://<node>.<tailnet>.ts.net:10000/mcp
```

Funnel exposes these services to anyone on the internet who learns the URL, so turn the mappings off when you're done: `tailscale funnel --https=443 off` (and likewise for `8443` and `10000`).

`SANDBOX_MCP_URL` overrides the `host.docker.internal` default (which only resolves from local Docker sandboxes, not Modal). Without it, sandbox agents can't reach the MCP server and lose access to the PostHog `execute-sql`, query, and tool-calling stack.

### Agent run telemetry (optional)

To ship agent-server run metadata to PostHog Logs, set both of the first two; the third additionally produces one APM trace per run (root `task_run` span, a `turn` span per prompt, a `tool_call:<kind>` span per tool call) with trace/span ids stamped on the log records:

```bash
SANDBOX_AGENT_OTEL_LOGS_URL=http://localhost:8000/i/v1/logs  # or https://us.i.posthog.com/i/v1/logs
SANDBOX_AGENT_OTEL_LOGS_TOKEN=<project API key of the telemetry project>
SANDBOX_AGENT_OTEL_TRACES_URL=http://localhost:8000/i/v1/traces  # optional, enables APM spans
```

In cloud, emission is additionally gated per run by the `tasks-agent-run-otel-telemetry` feature flag (org-targeted, stamped into run state at dispatch; it also gates the scout run-log mirror). `DEBUG` bypasses the flag, so locally these settings are the only switch. They're injected into the sandbox as `POSTHOG_AGENT_OTEL_LOGS_URL`/`_TOKEN`/`POSTHOG_AGENT_OTEL_TRACES_URL` (deliberately not standard `OTEL_*` names, so OTel SDKs in user code don't auto-export into the telemetry project).
The agent-server exports run/turn/tool lifecycle metadata (never message content or tool arguments), tagged with `run_id`/`task_id`/`team_id`/`user_id`/`distinct_id` resource attributes and `service.name=posthog-code-agent`.
Telemetry stays off when either of the first two vars is unset.
For local Docker sandboxes the localhost URLs are rewritten to `host.docker.internal` automatically; local ingestion requires the `capture-logs` service to be running.

### MCP server `.env`

`MODAL_DOCKER` (and the local Docker provider) both depend on the MCP server running at `localhost:8787`. The server reads its config from `services/mcp/.env` — without it, things like `POSTHOG_API_BASE_URL`, the UI-apps token, and analytics keys are missing and the server will either refuse to start or return broken responses to the sandbox.

```bash
cd services/mcp && cp .env.example .env
```

Then fill in the secrets. `POSTHOG_UI_APPS_TOKEN` and `POSTHOG_ANALYTICS_API_KEY` are public PostHog `phc_*` project keys — for local dev you can paste the same key you use for analytics, or leave them as the placeholder (analytics calls will no-op). Restart the `mcp` phrocs process after changing `.env`.

### Local agent packages

Cloud tasks use the published `@posthog/agent` package by default. Set `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` only when you need to test local agent changes.

For local Docker, the worker builds the packages inside the sandbox image. The first build installs the workspace dependencies. Later source changes reuse those dependencies from the Docker build cache.

```bash
# In your .env:
SANDBOX_PROVIDER=docker
# The desktop source lives in this repo at products/desktop
LOCAL_POSTHOG_CODE_MONOREPO_ROOT=./products/desktop
```

Restart the temporal worker after changing `.env`.

For local Modal, set `SANDBOX_PROVIDER=MODAL_DOCKER`, build the packages, and restart the temporal worker:

```bash
pnpm --dir products/desktop --filter @posthog/agent... build
```

### Sandbox providers

| Provider          | `.env` value                    | When to use                                                                                                                                                                                                                                                                                                                                           |
| ----------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `modal` (default) | `SANDBOX_PROVIDER=modal`        | Production. Uses the published `@posthog/agent` npm package from the GHCR image.                                                                                                                                                                                                                                                                      |
| `MODAL_DOCKER`    | `SANDBOX_PROVIDER=MODAL_DOCKER` | **Local development with Modal.** Same as `modal` but uses a separate Modal app (`posthog-sandbox-modal-docker-*`) so local image builds don't pollute the production app cache. When `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` is set, each local package's external runtime dependencies are installed and its compiled output is overlaid onto the image. |
| `docker`          | `SANDBOX_PROVIDER=docker`       | Local-only Docker containers (`DEBUG=True` required). No Modal account needed. Uses the published agent by default and builds local agent packages when `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` is set. This is the recommended option for local development.                                                                                              |

### Modal apps

Every sandbox is booked against a Modal app, which is what groups it in the Modal dashboard and attributes its cost.
The app is picked from the template first, and from `SandboxConfig.workload` when the template has no app of its own.

| App                            | Owned by                                                                                      |
| ------------------------------ | --------------------------------------------------------------------------------------------- |
| `posthog-sandbox-default`      | Everything not claimed below — user-created tasks, loops, onboarding, image builds            |
| `posthog-sandbox-self-driving` | The self-driving fleet: Signals report research and repo selection, Signals scouts, ReviewHog |
| `posthog-sandbox-notebook`     | `NOTEBOOK_BASE` template                                                                      |
| `posthog-sandbox-streamlit`    | `STREAMLIT_BASE` template                                                                     |

Self-driving membership is derived from the task's `origin_product` (`SELF_DRIVING_ORIGIN_PRODUCTS` in
`logic/services/sandbox.py`), so a product joins the fleet by adding its origin there — no caller changes.
The split is for metering only: same image, same resources, same isolation, and images and snapshots are
workspace-scoped in Modal, so a self-driving box still restores a snapshot baked under the default app.

Each name above is a class attribute on `ModalSandbox`, and the `MODAL_DOCKER` and `MODAL_EVALS` providers
override all four (`posthog-sandbox-modal-docker-*`, `posthog-sandbox-evals`), so local and eval runs never land
in a production app. A new app name has to be a class attribute for that to keep holding.

### Sandbox templates

Each sandbox is created from a template that determines its base image and capabilities.

| Template        | Image                                      | Description                                                                                                                                                    |
| --------------- | ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DEFAULT_BASE`  | `ghcr.io/posthog/posthog-sandbox-base`     | Standard sandbox template (default).                                                                                                                           |
| `NOTEBOOK_BASE` | `ghcr.io/posthog/posthog-sandbox-notebook` | Template for notebook functionality.                                                                                                                           |
| `VM_BASE`       | `ghcr.io/posthog/posthog-sandbox-vm`       | Docker-in-Docker capable. Layers Docker engine, compose v2, and buildx on the base image. Includes an idempotent `start-dockerd` helper for on-demand dockerd. |

`VM_BASE` uses the Modal VM runtime (real Linux kernel) instead of gVisor because `dockerd` cannot run under gVisor. When a sandbox is created with `template=SandboxTemplate.VM_BASE`, `ModalSandbox.create` automatically sets `experimental_options={"vm_runtime": True}`.

### Optional: local repository mounts (Docker only)

If you already have a repository checked out locally, you can skip cloning by
bind-mounting it into the Docker sandbox:

```bash
# Format: org/repo:/local/path,org2/repo2:~/other/path
SANDBOX_REPO_MOUNT_MAP=PostHog/posthog:~/Developer/posthog
```

When configured, matching repositories are mounted read-write from your host
into the container, and `clone_repository` becomes a no-op for those
repositories.

> **Note:** This only works with `SANDBOX_PROVIDER=docker`.

### Task-run log mirroring to PostHog Logs (dogfooding)

Task-run log entries (the JSONL appended to object storage via `TaskRun.append_log`) are also mirrored into the PostHog Logs product,
so runs can be browsed and sampled in the Logs UI instead of fetching S3 blobs.

In production there is no transport of its own: entries are emitted as structured stdout log lines (`event=task_run_log`),
and the per-cluster OTel collector that already ships all container stdout into the region's internal PostHog project picks them up.
The collector parses each JSON key into a queryable attribute and turns the emitted `request_id` (the run uuid) into a trace id,
so one run groups as a trace and can be pulled up with an attribute filter on `task_run_id`.

```bash
# Which task origins to mirror (comma-separated). Defaults to signals scouts and user-created tasks.
# Set empty to disable.
TASK_RUN_LOGS_MIRROR_ORIGIN_PRODUCTS=signals_scout,user_created
```

The mirror also has a **direct OTLP leg** that ships each batch straight to a logs ingest endpoint:

```bash
TASK_RUN_LOGS_MIRROR_OTLP_URL=http://localhost:8000/i/v1/logs  # prod: https://us.i.posthog.com/i/v1/logs
TASK_RUN_LOGS_MIRROR_OTLP_TOKEN=<project API key of the internal logs project>
```

The token pins the destination: scout runs execute for customer teams,
but their mirrored transcripts must only ever land in — and bill — PostHog's own internal logs project, never the customer's.
Records arrive under `service.name=task-run-log-mirror` with the run uuid as the trace id.

Locally the direct leg is the only delivery path: `append_log` runs in the host Django process,
and the dev collector (`otel-collector-config.dev.yaml`) only tails docker-compose container stdout,
so without these settings the mirrored lines only show up in the Django phrocs pane.

Mirroring failures are logged and never break the run's log write.

### How `MODAL_DOCKER` works

When both `SANDBOX_PROVIDER=MODAL_DOCKER` and `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` are set:

1. The selected sandbox Dockerfile is built in a temporary context
2. External runtime dependencies from local `packages/agent`, `packages/shared`, and `packages/git` manifests that are missing from the published image are installed at `/scripts`; required system compatibility packages such as musl for Codex are installed with them, while `workspace:*` dependencies continue to resolve through the overlaid packages
3. Each local package's built `dist/` directory is mounted over the published package's compiled output
4. The image runs in a separate Modal app (`posthog-sandbox-modal-docker-default`) so it doesn't affect production
5. The first build takes a few minutes; subsequent builds reuse Modal's layer cache

After changing agent-server code, rebuild and restart the worker:

```bash
cd products/desktop/packages/agent && pnpm build
```

> **Note:** The build context is cached for the lifetime of the worker process (`lru_cache`).
> You must restart the temporal worker to pick up new local package changes.

## Troubleshooting

| Problem                                                                                                      | Solution                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Docker not running                                                                                           | Start Docker Desktop or the Docker daemon                                                                                                                                                                                                                                                                                                                                                                              |
| Temporal not reachable                                                                                       | Ensure Temporal is running on `127.0.0.1:7233`. Check with `temporal server start-dev`                                                                                                                                                                                                                                                                                                                                 |
| Feature flag not enabled                                                                                     | Re-run `python manage.py setup_background_agents` to (re-)create the `tasks` flag at 100% rollout                                                                                                                                                                                                                                                                                                                      |
| Array OAuth app missing                                                                                      | Re-run `python manage.py setup_background_agents`                                                                                                                                                                                                                                                                                                                                                                      |
| `PostHog AI app not found for region ...`                                                                    | The PostHog AI OAuth app is missing. Run `python manage.py setup_tasks_oauth`, which creates both the Array and PostHog AI dev apps. Deploys run it from `bin/migrate`; it no-ops in the US/EU regions                                                                                                                                                                                                                 |
| GitHub token expired                                                                                         | Tokens from GitHub App installations expire after ~1 hour. Re-run the task to get a fresh token                                                                                                                                                                                                                                                                                                                        |
| "Task workflow execution blocked"                                                                            | The `tasks` feature flag is not enabled for this user/org                                                                                                                                                                                                                                                                                                                                                              |
| Sandbox image build fails                                                                                    | Check Docker has enough disk space. Delete old images with `docker system prune`                                                                                                                                                                                                                                                                                                                                       |
| Agent server health check fails                                                                              | Check sandbox logs: `docker exec <container_id> cat /tmp/agent-server.log`                                                                                                                                                                                                                                                                                                                                             |
| `SANDBOX_JWT_PRIVATE_KEY` missing                                                                            | Re-run `python manage.py setup_background_agents` — it will auto-fill from `.env.example`                                                                                                                                                                                                                                                                                                                              |
| Port conflict on sandbox host port                                                                           | DockerSandbox maps container port 47821 to a dynamic host port. Check sandbox logs or TaskRun state for the assigned port; if another process uses it, stop that process or restart Docker                                                                                                                                                                                                                             |
| Sandbox can't reach PostHog API                                                                              | Don't set `SANDBOX_API_URL` with Docker — auto-transform handles it. If overriding, use port 8000, not 8010 (Caddy returns empty responses from inside Docker)                                                                                                                                                                                                                                                         |
| MCP Store connectors don't mount in local sandbox runs (agent lists only `posthog` and `posthog-code-tools`) | Known local-dev gap: store-connector proxy URLs are built from `SANDBOX_API_URL`/`SITE_URL` and, unlike sandbox env vars, are not rewritten to `host.docker.internal` for Docker. The agent SDK drops unreachable servers silently. Affects loop and workflow connectors locally; prod URLs are public so it never applies there                                                                                       |
| `DEBUG` not set                                                                                              | `SANDBOX_PROVIDER=docker` requires `DEBUG=1`. Re-run `python manage.py setup_background_agents` to write it                                                                                                                                                                                                                                                                                                            |
| `... sandbox is for local development only` (RuntimeError at import)                                         | The `docker` / `MODAL_DOCKER` providers require `DEBUG=1` (or `TEST=1`, which pytest sets). `DEBUG=1` is normally injected by the flox env (`.flox/env/manifest.toml` `[vars]`) — this fires when you're outside `flox activate` or explicitly unset `DEBUG` (e.g. to escape the cloud-DEBUG guard). Keep `DEBUG` on and use `CLOUD_DEPLOYMENT=E2E` for cloud-mode dev instead. See [dev-env-vars.md](dev-env-vars.md) |
| `git commit is disabled in PostHog Desktop`                                                                  | A PATH shim (`git-guard.sh` at `/opt/posthog/bin/git`) blocks `git commit` and `git push` so unsigned commits can't leave the sandbox. Stage changes with `git add`, then use the `git_signed_commit` tool. To bypass during debugging, set `POSTHOG_ALLOW_UNSIGNED_GIT=1`                                                                                                                                             |
