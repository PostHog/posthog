---
name: debugging-local-task-agent-runs
description: 'Set up and debug local PostHog task runs: the Temporal `process-task` workflow that runs the agent (and, for the wizard cloud-run path, the setup wizard first) inside a Modal sandbox (`SANDBOX_PROVIDER=MODAL_DOCKER`). Use when setting up local task sandboxes, when a local run looks stuck, failed, or silent, or when you need the wizard or agent logs, live from the sandbox or from object storage after teardown. Trigger terms: task-sandbox, run_wizard, agent-server, process-task, SANDBOX_PROVIDER, MODAL_DOCKER, AI_GATEWAY, cloud_run, posthog-wizard.log, tasks:setup, tasks:funnel, tasks:doctor.'
---

# Debugging local task/agent runs

A "cloud run" of the Tasks product executes as the Temporal **`process-task`** workflow on the `development-task-queue`. Locally each run gets a **Modal sandbox** (`SANDBOX_PROVIDER=MODAL_DOCKER`), in which:

1. **`run_wizard`** activity — wizard cloud runs only: runs the published `@posthog/wizard` to integrate PostHog (writes `/tmp/posthog-wizard.log`).
2. **`agent-server`** — the coding agent that does the task, commits, opens the PR, and keeps it green (writes `/tmp/agent-server.log`).

The hard part of debugging is that **the Temporal UI doesn't show this output** — workflow result/failure payloads are `binary/encrypted`, and the activity captures the wizard/agent output to the run's logs, not to the timeline. This skill is how you actually read it.

The full setup guide is [docs/internal/sandboxes-setup-guide.md](../../../docs/internal/sandboxes-setup-guide.md). This flow is for PostHog staff only.

## Step 0 — check the setup

Run these in order:

```bash
hogli tasks:doctor             # provider, Modal token, dev token and budget, Funnel, .env/.env.local shadowing
hogli tasks:setup --dry-run    # the plan; writes nothing
hogli tasks:setup --yes        # apply it (add --force only to overwrite a value the user set)
```

On a devbox, pass `--funnel-host <laptop>.<tailnet>.ts.net` to both `tasks:setup` calls so the URLs point at the laptop that runs the Funnel.

Stop and ask the user when a remaining step needs a human:

- **The Modal token.** `tasks:setup` reads the shared "Modal Development Token" from the General vault of PostHog's 1Password with `op`. If `op` isn't installed or signed in, the user has to fix that. Never create a personal Modal token (`modal token new`).
- **The gateway token.** Approving `hogli gateway:token` happens in the user's browser.

Then make sure the Funnel is up (`hogli tasks:funnel up`, on the laptop when the stack runs on a devbox). After any env change, re-activate flox and run `hogli stop && hogli up -d` — env is read at process start, not hot-reloaded.

For wizard cloud runs, **the wizard OAuth app must exist** — `bin/ensure-local-setup` provisions it and sets `WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID`; without it the `cloud_run` endpoint returns 404 "not available". Clone and PR need the [GitHub App](../../../docs/internal/sandboxes-setup-guide.md#github-app).

## Step 1 — find the task and run UUIDs

The workflow id encodes both: `task-processing-<task_id>-<run_id>`.

From the Temporal CLI (lists running/recent `process-task` workflows):

```bash
docker exec posthog-temporal-admin-tools-1 \
  temporal workflow list --address temporal:7233 --namespace default --limit 10 \
  | grep process-task
# task-processing-<TASK_ID>-<RUN_ID>  process-task  Running
```

From the **Temporal UI** — http://localhost:8081, open the `process-task` workflow; the id in the URL is `task-processing-<TASK_ID>-<RUN_ID>`.

## Step 2 — tail live logs inside the sandbox (while it's running)

The wizard and agent write line-by-line to files in the sandbox **as they run**, so this is the only way to watch progress live (the activity buffers stdout and only flushes to the durable log when it finishes).

Local sandboxes live in the `posthog-sandbox-modal-docker-*` Modal apps and carry `task_id` and `task_run_id` tags:

```bash
RUN_ID=<run-uuid-from-step-1>
flox activate -- bash -c "python - <<'PY'
import modal
for name in ('posthog-sandbox-modal-docker-default', 'posthog-sandbox-modal-docker-self-driving'):
    try:
        app = modal.App.lookup(name)
    except modal.exception.NotFoundError:
        continue
    for sb in modal.Sandbox.list(app_id=app.app_id, tags={'task_run_id': '$RUN_ID'}):
        print(name, sb.object_id)
        print(sb.exec('tail', '-n', '200', '/tmp/agent-server.log').stdout.read())
PY"
```

Self-driving origins (scouts, ReviewHog, Signals) land in the `-self-driving` app. Swap in `/tmp/posthog-wizard.log` for the wizard stage. Both files are JSON-heavy; pipe through `grep -iE '"text"|tool_use|error|commit|PR|CI'` for the readable activity.

These files vanish when the sandbox is torn down (on run completion/failure), so grab them while the sandbox is up.

## Step 3 — read the durable per-run console log (after teardown)

Everything the wizard and agent emit is persisted to the run's console log in object storage at `tasks/logs/team_<id>/task_<id>/run_<run_id>.jsonl`. This survives teardown. Read it with the run UUID (last UUID of the workflow id; or `TaskRun.objects.filter(task_id=...).latest("created_at")`):

```bash
RUN_ID=<run-uuid>
flox activate -- bash -c "python manage.py shell <<'PY'
import json
from products.tasks.backend.models import TaskRun
from posthog.storage import object_storage
tr = TaskRun.objects.get(id='$RUN_ID')
print('status:', tr.status)
for line in (object_storage.read(tr.log_url, missing_ok=True) or '').splitlines():
    n = json.loads(line).get('notification', {}); m = n.get('method'); p = n.get('params', {})
    if m == '_posthog/console':
        print(f\"[{p.get('level')}] {p.get('message','')[:300]}\")
    elif m == 'session/update':                      # the agent stage (ACP stream)
        u = p.get('update', {}); t = u.get('sessionUpdate')
        if t == 'tool_call': print('  tool→', u.get('title') or u.get('kind'))
        elif t == 'tool_call_update' and u.get('status'): print('  tool✓', u.get('status'))
PY"
```

Notes on what you'll (not) see here:

- **Wizard stdout/verbose** lands as `_posthog/console` debug events, but only **after `run_wizard` finishes** (buffered `sandbox.execute`). Mid-run, use Step 2.
- **Agent prose is filtered out.** `append_log` drops `agent_message_chunk` events to keep the log lean, so the durable log shows _what the agent did_ (tool calls, commits, progress) but not its narration. For the agent's reasoning, read `/tmp/agent-server.log` in the sandbox (Step 2) before teardown.

## Common failure signatures

- **`Could not determine cloud region from access token`** — the wizard hit cloud auth instead of your local instance. Local needs the wizard pointed at the local base URL; see `run_wizard._build_wizard_command` (`--base-url`, DEBUG-gated).
- **Agent boots but never reaches PostHog or MCP**: the Funnel is down or `SANDBOX_API_URL` / `SANDBOX_MCP_URL` are stale. `hogli tasks:doctor` checks the Funnel; `hogli tasks:funnel up` restarts it.
- **Auth/4xx from the gateway, or `gateway_token_unavailable`**: the dev mode token expired, ran out of budget, or is unset, or `SANDBOX_AI_GATEWAY_PRODUCTS` doesn't list the run's product. `hogli tasks:doctor` shows which. Run `hogli tasks:setup --refresh-token` (the user approves it in the browser), then re-activate flox and run `hogli stop && hogli up -d`.
- **`... sandbox is for local development only`** at import: `DEBUG` is off, usually because the process runs outside `flox activate`.
- **The run uses an old image after a Dockerfile change**: the build context is cached per worker process. Restart the Temporal worker. The first run after an image change builds on Modal and takes minutes.
- **Workflow "running" but nothing happening** — it's in the wait loop (CI follow-up / inactivity). The workflow's Temporal **Current Details** field names what it's waiting on.

## Docker provider (backup)

With `SANDBOX_PROVIDER=docker` (see the [guide](../../../docs/internal/sandboxes-setup-guide.md#docker-provider-backup)), the sandbox is a local container named `task-sandbox-<TASK_ID>-<suffix>`. Tail logs with `docker exec "$(docker ps -q --filter "name=task-sandbox-$TASK_ID")" tail -f /tmp/agent-server.log`.
