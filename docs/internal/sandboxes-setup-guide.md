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
is happening with a background cloud run and for debugging. You can also use PostHog Code to do this rather than the debug UI.

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

### Tunnel gateway, API, and MCP

If you run in a docker sandbox you don't need to do this. If you are testing with Modal sandboxes, since they run in the cloud and can't reach `localhost` directly,
you'll need to expose the Django API, LLM gateway, and MCP server via a tunnel (e.g. ngrok or Cloudflare Tunnel).

With ngrok, add tunnels to your ngrok config, `~/.config/ngrok/ngrok.yml` (Linux) or `~/Library/Application Support/ngrok/ngrok.yml` (MacOS):

```yaml
tunnels:
  django:
    proto: http
    addr: 8000
  gateway:
    proto: http
    addr: 3308
  mcp:
    proto: http
    addr: 8787
```

**IMPORTANT:** The free version of Ngrok includes on `dev` domain, that will try to cover both tunnels, and it won't work. Use Cloudflare (free). If you want to use ngrok, upgrade to `Hobbyist` plan, create custom domans, and add them to config:

```yaml
tunnels:
  django:
    proto: http
    addr: 8000
    domain: alexl-django.ngrok.dev
  gateway:
    proto: http
    addr: 3308
    domain: alexl-llmg.ngrok.dev
  mcp:
    proto: http
    addr: 8787
    domain: alexl-mcp.ngrok.dev
agent:
  authtoken: ...
```

Then, get an auth token at `https://dashboard.ngrok.com/get-started/your-authtoken` and add it locally (either to ngrok directly, through `ngrok config add-authtoken`, or to the config file).

After that, start both tunnels:

```bash
ngrok start --all
```

Set the resulting URLs in your `.env`:

```bash
SANDBOX_API_URL=https://<django-8000-subdomain>.ngrok-free.app
SANDBOX_LLM_GATEWAY_URL=https://<gateway-3308-subdomain>.ngrok-free.app
SANDBOX_MCP_URL=https://<mcp-8787-subdomain>.ngrok-free.app/mcp
```

`SANDBOX_MCP_URL` overrides the `host.docker.internal` default (which only resolves from local Docker sandboxes, not Modal). Without it, sandbox agents can't reach the MCP server and lose access to the PostHog `execute-sql`, query, and tool-calling stack.

### MCP server `.dev.vars`

`MODAL_DOCKER` (and the local Docker provider) both depend on the MCP Worker running at `localhost:8787`. The Worker reads its config from `services/mcp/.dev.vars` — without it, things like `POSTHOG_API_BASE_URL`, the UI-apps token, and analytics keys are missing and the Worker will either refuse to start or return broken responses to the sandbox.

```bash
cd services/mcp && cp .dev.vars.example .dev.vars
```

Then fill in the secrets. `INKEEP_API_KEY` (for the `docs-search` tool) lives in 1Password under **"Inkeep API key - mcp"**. `POSTHOG_UI_APPS_TOKEN` and `POSTHOG_ANALYTICS_API_KEY` are public PostHog `phc_*` project keys — for local dev you can paste the same key you use for analytics, or leave them as the placeholder (analytics calls will no-op). Restart the `mcp` phrocs process after changing `.dev.vars`.

### Local agent packages

```bash
# In your .env:
SANDBOX_PROVIDER=MODAL_DOCKER
LOCAL_POSTHOG_CODE_MONOREPO_ROOT=/path/to/posthog-code
```

Then build the agent package and restart the temporal worker:

```bash
cd /path/to/posthog-code/packages/agent && pnpm build
```

### Sandbox providers

| Provider          | `.env` value                    | When to use                                                                                                                                                                                                                                                                            |
| ----------------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `modal` (default) | `SANDBOX_PROVIDER=modal`        | Production. Uses the published `@posthog/agent` npm package from the GHCR image.                                                                                                                                                                                                       |
| `MODAL_DOCKER`    | `SANDBOX_PROVIDER=MODAL_DOCKER` | **Local development with Modal.** Same as `modal` but uses a separate Modal app (`posthog-sandbox-modal-docker-*`) so local image builds don't pollute the production app cache. When `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` is set, the local agent packages are overlaid onto the image. |
| `docker`          | `SANDBOX_PROVIDER=docker`       | Local-only Docker containers (`DEBUG=True` required). No Modal account needed. This is the recommended option for local development.                                                                                                                                                   |

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

### How `MODAL_DOCKER` works

When both `SANDBOX_PROVIDER=MODAL_DOCKER` and `LOCAL_POSTHOG_CODE_MONOREPO_ROOT` are set:

1. The Dockerfile is built in a temp context with your local `packages/agent`, `packages/shared`, and `packages/git` copied in
2. `pnpm pack` + `pnpm install` replaces the published npm package with your local build
3. The image is pushed to a separate Modal app (`posthog-sandbox-modal-docker-default`) so it doesn't affect production
4. The first build takes a few minutes; subsequent builds reuse Modal's layer cache

After changing agent-server code, rebuild and restart the worker:

```bash
cd /path/to/posthog-code/packages/agent && pnpm build
```

> **Note:** The build context is cached for the lifetime of the worker process (`lru_cache`).
> You must restart the temporal worker to pick up new local package changes.

## Troubleshooting

| Problem                                                              | Solution                                                                                                                                                                                                                                                                                                                                                                                                               |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Docker not running                                                   | Start Docker Desktop or the Docker daemon                                                                                                                                                                                                                                                                                                                                                                              |
| Temporal not reachable                                               | Ensure Temporal is running on `127.0.0.1:7233`. Check with `temporal server start-dev`                                                                                                                                                                                                                                                                                                                                 |
| Feature flag not enabled                                             | Re-run `python manage.py setup_background_agents` to (re-)create the `tasks` flag at 100% rollout                                                                                                                                                                                                                                                                                                                      |
| Array OAuth app missing                                              | Re-run `python manage.py setup_background_agents`                                                                                                                                                                                                                                                                                                                                                                      |
| GitHub token expired                                                 | Tokens from GitHub App installations expire after ~1 hour. Re-run the task to get a fresh token                                                                                                                                                                                                                                                                                                                        |
| "Task workflow execution blocked"                                    | The `tasks` feature flag is not enabled for this user/org                                                                                                                                                                                                                                                                                                                                                              |
| Sandbox image build fails                                            | Check Docker has enough disk space. Delete old images with `docker system prune`                                                                                                                                                                                                                                                                                                                                       |
| Agent server health check fails                                      | Check sandbox logs: `docker exec <container_id> cat /tmp/agent-server.log`                                                                                                                                                                                                                                                                                                                                             |
| `SANDBOX_JWT_PRIVATE_KEY` missing                                    | Re-run `python manage.py setup_background_agents` — it will auto-fill from `.env.example`                                                                                                                                                                                                                                                                                                                              |
| Port conflict on sandbox host port                                   | DockerSandbox maps container port 47821 to a dynamic host port. Check sandbox logs or TaskRun state for the assigned port; if another process uses it, stop that process or restart Docker                                                                                                                                                                                                                             |
| Sandbox can't reach PostHog API                                      | Don't set `SANDBOX_API_URL` with Docker — auto-transform handles it. If overriding, use port 8000, not 8010 (Caddy returns empty responses from inside Docker)                                                                                                                                                                                                                                                         |
| `DEBUG` not set                                                      | `SANDBOX_PROVIDER=docker` requires `DEBUG=1`. Re-run `python manage.py setup_background_agents` to write it                                                                                                                                                                                                                                                                                                            |
| `... sandbox is for local development only` (RuntimeError at import) | The `docker` / `MODAL_DOCKER` providers require `DEBUG=1` (or `TEST=1`, which pytest sets). `DEBUG=1` is normally injected by the flox env (`.flox/env/manifest.toml` `[vars]`) — this fires when you're outside `flox activate` or explicitly unset `DEBUG` (e.g. to escape the cloud-DEBUG guard). Keep `DEBUG` on and use `CLOUD_DEPLOYMENT=E2E` for cloud-mode dev instead. See [dev-env-vars.md](dev-env-vars.md) |
| `git commit is disabled in PostHog Code`                             | A PATH shim (`git-guard.sh` at `/opt/posthog/bin/git`) blocks `git commit` and `git push` so unsigned commits can't leave the sandbox. Stage changes with `git add`, then use the `git_signed_commit` tool. To bypass during debugging, set `POSTHOG_ALLOW_UNSIGNED_GIT=1`                                                                                                                                             |
