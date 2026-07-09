---
name: debugging-local-task-agent-runs
description: Debug the output of local PostHog task runs — the wizard cloud-run path that executes inside a Docker sandbox under the local Temporal `process-task` workflow (the wizard that integrates PostHog, then the coding agent that commits and opens the PR). Use when a local run looks stuck, failed, or silent, or when you need to read the wizard or agent logs. Covers the `.env.local` keys + `ai_features` intent required for cloud runs locally, finding the task UUID (docker ps, temporal CLI, Temporal UI at localhost:8081), tailing live logs inside the sandbox container (`/tmp/posthog-wizard.log`, `/tmp/agent-server.log`), and reading the durable per-run console log from object storage after the sandbox is torn down. Trigger terms: task-sandbox, run_wizard, agent-server, process-task, SANDBOX_PROVIDER, LLM_GATEWAY, cloud_run, posthog-wizard.log.
---

# Debugging local task/agent runs

A "cloud run" of the Tasks product (e.g. the setup-wizard `cloud_run` endpoint) executes as the Temporal **`process-task`** workflow on the `development-task-queue`. Locally (`SANDBOX_PROVIDER=docker`) each run gets a **Docker sandbox container** in which two things happen in sequence:

1. **`run_wizard`** activity — runs the published `@posthog/wizard` to integrate PostHog (writes `/tmp/posthog-wizard.log`).
2. **`agent-server`** — the coding agent that commits the wizard's changes, opens the PR, and keeps it green (writes `/tmp/agent-server.log`).

The hard part of debugging is that **the Temporal UI doesn't show this output** — workflow result/failure payloads are `binary/encrypted`, and the activity captures the wizard/agent output to the run's logs, not to the timeline. This skill is how you actually read it.

## Prerequisites: env for local cloud runs

Cloud runs only work locally if **all** of these are set in `.env.local` (values shown are the local targets — never commit real secrets). Inside the Docker sandbox, `localhost` is the container itself, so PostHog URLs use `host.docker.internal`.

| Key                             | Purpose / local value                                                                                  |
| ------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `SANDBOX_PROVIDER`              | `"docker"` — route sandboxes to local Docker instead of Modal                                          |
| `SANDBOX_MCP_URL`               | `"http://host.docker.internal:8787/mcp"` — MCP server the agent uses                                   |
| `SANDBOX_LLM_GATEWAY_URL`       | `"http://host.docker.internal:3308"` — local LLM gateway the agent routes model calls through          |
| `SANDBOX_JWT_PRIVATE_KEY`       | signs the scoped sandbox tokens                                                                        |
| `GITHUB_APP_CLIENT_ID`          | your local GitHub App (clone + PR)                                                                     |
| `GITHUB_APP_CLIENT_SECRET`      | ""                                                                                                     |
| `GITHUB_APP_SLUG`               | ""                                                                                                     |
| `GITHUB_APP_PRIVATE_KEY`        | ""                                                                                                     |
| `LLM_GATEWAY_ANTHROPIC_API_KEY` | real Anthropic key the **local gateway** proxies to (read via the gateway's `LLM_GATEWAY_` env prefix) |

Two non-env requirements, or the keys above are inert:

- **The LLM gateway must actually be running on `:3308`.** It's gated behind the `llm_gateway` capability — enable the **`ai_features`** intent (`hogli dev:setup`) so the `llm-gateway` proc starts. `SANDBOX_LLM_GATEWAY_URL` pointing at a dead port just yields `ConnectionRefused` from the agent.
- **The wizard OAuth app must exist** — `bin/ensure-local-setup` provisions it and sets `WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID`; without it the `cloud_run` endpoint returns 404 "not available".

After editing `.env.local`, **restart the stack** — env is read at process start, not hot-reloaded.

## Step 1 — find the task UUID

You need the **task UUID** for the container, and sometimes the **run UUID** for the durable log. The workflow id encodes both: `task-processing-<task_id>-<run_id>`.

Fastest (no Temporal needed — the sandbox container name carries the task UUID):

```bash
docker ps --format '{{.Names}}' | grep task-sandbox
# task-sandbox-<TASK_ID>-<suffix>
```

From the Temporal CLI (lists running/recent `process-task` workflows with both UUIDs):

```bash
docker exec posthog-temporal-admin-tools-1 \
  temporal workflow list --address temporal:7233 --namespace default --limit 10 \
  | grep process-task
# task-processing-<TASK_ID>-<RUN_ID>  process-task  Running
```

From the **Temporal UI** — http://localhost:8081, open the `process-task` workflow; the id in the URL is `task-processing-<TASK_ID>-<RUN_ID>`.

## Step 2 — tail live logs inside the sandbox (while it's running)

The wizard and agent write line-by-line to files in the container **as they run**, so this is the only way to watch progress live (the activity buffers stdout and only flushes to the durable log when it finishes).

```bash
TASK_ID=<task-uuid-from-step-1>
CID=$(docker ps -q --filter "name=task-sandbox-$TASK_ID")

docker exec "$CID" tail -f /tmp/posthog-wizard.log   # wizard stage (full agent SDK detail)
docker exec "$CID" tail -f /tmp/agent-server.log     # agent stage (commit + PR + CI loop)
```

Both files are JSON-heavy. For just the readable activity:

```bash
docker exec "$CID" tail -f /tmp/agent-server.log \
  | grep -iE '"text"|tool_use|error|✔|✖|commit|PR|CI'
```

These files vanish when the sandbox is torn down (on run completion/failure), so grab them while the container is up.

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
- **Agent prose is filtered out.** `append_log` drops `agent_message_chunk` events to keep the log lean, so the durable log shows _what the agent did_ (tool calls, commits, progress) but not its narration. For the agent's reasoning, read `/tmp/agent-server.log` in the container (Step 2) before teardown.

## Common failure signatures

- **`Could not determine cloud region from access token`** — the wizard hit cloud auth instead of your local instance. Local needs the wizard pointed at the local base URL; see `run_wizard._build_wizard_command` (`--base-url`, DEBUG-gated).
- **`Unable to connect to API (ConnectionRefused)`** from the agent — `LLM_GATEWAY_URL=UNSET` or the gateway isn't on `:3308`. Check `SANDBOX_LLM_GATEWAY_URL` + the `ai_features` intent (gateway proc).
- **Auth/4xx from the gateway** — the gateway is reachable but has no upstream provider key (`LLM_GATEWAY_ANTHROPIC_API_KEY`) or the token lacks `llm_gateway:read`.
- **Workflow "running" but nothing happening** — it's in the wait loop (CI follow-up / inactivity). The workflow's Temporal **Current Details** field names what it's waiting on.
