# Cloud runs: local setup guide

## Quickstart

1. Create a personal dev GitHub App (see [GitHub App](#github-app) below)
2. Run `python manage.py setup_background_agents`
3. Run `hogli start`
4. Open Tasks in PostHog and create a task

The setup command is idempotent — re-run it anytime. It writes the dev JWT keys
to your `.env`, creates the Array OAuth application, enables the `tasks` feature
flag for every team, and builds the agent skills bundle.

## GitHub App

Each engineer needs their own GitHub App. The setup command will print these
instructions and offer to open the creation page in your browser, but for
reference:

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
3. Set the permissions above
4. Generate and download a private key
5. Install the app on your test repositories by going to `http://localhost:8010/project/1/settings/project-integrations` and installing the GitHub Integration
6. Add to your `.env`:

```bash
GITHUB_APP_CLIENT_ID=your_app_id
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
is happening with a background cloud run.

1. Navigate to Tasks in PostHog (requires the `tasks` feature flag)
2. Create a task with a title, description, and repository (format: `owner/repo`)
3. Click "Run task"
4. Watch logs stream in the session view

## Testing with local agent packages

To test changes to `@posthog/agent` before publishing:

### Modal credentials

Both `MODAL_DOCKER` and `modal` providers require a Modal API token.
Look up **"Modal Development Token"** in 1Password and add the values to your `.env`:

```bash
MODAL_TOKEN_ID=<token_id>
MODAL_TOKEN_SECRET=<token_secret>
```

### Tunnel gateway and API

Since Modal sandboxes run in the cloud and can't reach `localhost` directly,
you'll need to expose the Django API and LLM gateway via a tunnel (e.g. ngrok or Cloudflare Tunnel).

With ngrok, add tunnels to your ngrok config, `~/.config/ngrok/ngrok.yml` (Linux) or `~/Library/Application Support/ngrok/ngrok.yml` (MacOS):

```yaml
tunnels:
  django:
    proto: http
    addr: 8000
  gateway:
    proto: http
    addr: 3308
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
```

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
| `docker`          | `SANDBOX_PROVIDER=docker`       | Local-only Docker containers (`DEBUG=True` required). No Modal account needed.                                                                                                                                                                                                         |

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

| Problem                            | Solution                                                                                                                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Docker not running                 | Start Docker Desktop or the Docker daemon                                                                                                                                                  |
| Temporal not reachable             | Ensure Temporal is running on `127.0.0.1:7233`. Check with `temporal server start-dev`                                                                                                     |
| Feature flag not enabled           | Re-run `python manage.py setup_background_agents` to (re-)create the `tasks` flag at 100% rollout                                                                                          |
| Array OAuth app missing            | Re-run `python manage.py setup_background_agents`                                                                                                                                          |
| GitHub token expired               | Tokens from GitHub App installations expire after ~1 hour. Re-run the task to get a fresh token                                                                                            |
| "Task workflow execution blocked"  | The `tasks` feature flag is not enabled for this user/org                                                                                                                                  |
| Sandbox image build fails          | Check Docker has enough disk space. Delete old images with `docker system prune`                                                                                                           |
| Agent server health check fails    | Check sandbox logs: `docker exec <container_id> cat /tmp/agent-server.log`                                                                                                                 |
| `SANDBOX_JWT_PRIVATE_KEY` missing  | Re-run `python manage.py setup_background_agents` — it will auto-fill from `.env.example`                                                                                                  |
| Port conflict on sandbox host port | DockerSandbox maps container port 47821 to a dynamic host port. Check sandbox logs or TaskRun state for the assigned port; if another process uses it, stop that process or restart Docker |
| Sandbox can't reach PostHog API    | Don't set `SANDBOX_API_URL` with Docker — auto-transform handles it. If overriding, use port 8000, not 8010 (Caddy returns empty responses from inside Docker)                             |
| `DEBUG` not set                    | `SANDBOX_PROVIDER=docker` requires `DEBUG=1`. Re-run `python manage.py setup_background_agents` to write it                                                                                |
