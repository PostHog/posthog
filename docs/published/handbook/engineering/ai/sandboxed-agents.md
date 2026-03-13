---
title: Using sandboxed agents
sidebar: Docs
showTitle: true
---

Sandboxed agents are AI agents that run in isolated cloud containers with access to PostHog data,
GitHub repositories, and code execution.
They support two modes: **background** (batch tasks that produce artifacts like PRs or reports) and **interactive** (real-time conversational agents that stream responses via SSE).
Use them when your feature needs an autonomous agent that reads PostHog data, writes code, and produces artifacts.

For simpler LLM calls (summarization, translation, classification),
skip this page and use the LLM gateway (`get_llm_client()`) directly —
it's simpler and doesn't need a sandbox.

## When to use what

| Example                                                                                         | Solution                           |
| ----------------------------------------------------------------------------------------------- | ---------------------------------- |
| Signals team building an enrichment pipeline that generates reports from PostHog analytics data | Sandboxed agent — background mode  |
| Conversations team building an interactive chat agent with code execution                       | Sandboxed agent — interactive mode |
| LLM analytics summarizing a funnel, generating a natural-language insight title                 | LLM gateway via `get_llm_client()` |
| Not sure                                                                                        | Ask in `#team-posthog-ai`          |

**Rule of thumb**: if the LLM needs to _do things_ (query data, read files, create branches, open PRs), use a sandboxed agent.
If it just needs to _answer a question_ given some context you already have, use the LLM gateway.

## How it works

A sandboxed agent runs inside an isolated cloud container (Modal in production, Docker locally).
The system provisions the sandbox, clones a GitHub repo, starts an agent server, and then either waits for the agent to finish (background mode) or streams events in real time (interactive mode).

### Background mode

Background mode runs the agent to completion and produces artifacts like pull requests.

```text
Your product code
    │
    │  Task.create_and_run(..., mode="background")
    ▼
Temporal workflow (process-task)
    │
    ├── 1. Create scoped OAuth token
    ├── 2. Provision sandbox (Modal / Docker)
    ├── 3. Clone repository
    ├── 4. Start agent server
    ├── 5. Wait for completion (heartbeat-extended timeout)
    └── 6. Cleanup sandbox
```

### Interactive mode

Interactive mode relays sandbox events to a Redis stream and streams them to the browser via SSE.
It supports multi-turn conversations through Temporal signals and snapshot-based resumption.

```text
Your product code
    │
    │  Task.create_and_run(..., mode="interactive")
    ▼
Temporal workflow (process-task)
    │
    ├── 1. Create scoped OAuth token
    ├── 2. Provision sandbox (Modal / Docker)
    ├── 3. Clone repository
    ├── 4. Start agent server
    ├── 5. Relay events to Redis stream (relay_sandbox_events activity)
    ├── 6. Wait for follow-up messages (send_followup_message signal)
    ├── 7. Create snapshot on turn complete (create_resume_snapshot activity)
    └── 8. Cleanup sandbox

Browser ◄── SSE ◄── Django endpoint ◄── Redis stream ◄── Temporal relay ◄── Sandbox SSE
```

The agent inside the sandbox gets:

- A **scoped OAuth access token** for the PostHog API (6-hour TTL)
- A **GitHub installation token** for repo operations
- Access to the **PostHog MCP server** for querying data
- **Code execution** capabilities within the sandbox

## Creating a sandboxed agent

Use `Task.create_and_run()` to launch a sandboxed agent from your product code:

```python
from products.tasks.backend.models import Task

task = Task.create_and_run(
    team=team,
    title="Generate weekly signal report",
    description="Analyze error trends and generate a summary report with recommendations.",
    origin_product=Task.OriginProduct.ERROR_TRACKING,  # or your product's origin
    user_id=user.id,
    posthog_mcp_scopes="read_only",  # or "full" if the agent needs write access
)
```

### Parameters

| Parameter              | Required | Description                                                                |
| ---------------------- | -------- | -------------------------------------------------------------------------- |
| `team`                 | Yes      | The team this task belongs to                                              |
| `title`                | Yes      | Human-readable task title                                                  |
| `description`          | Yes      | Detailed description of what the agent should do                           |
| `origin_product`       | Yes      | Which product created this task (see `Task.OriginProduct` choices)         |
| `user_id`              | Yes      | User ID — used for feature flag validation and creating the scoped API key |
| `repository`           | Yes      | GitHub repo in `org/repo` format (e.g., `posthog/posthog-js`)              |
| `posthog_mcp_scopes`   | No       | Scope preset or explicit scope list (default: `"full"`)                    |
| `create_pr`            | No       | Whether the agent should create a PR (default: `True`)                     |
| `mode`                 | No       | Execution mode: `"background"` (default) or `"interactive"`                |
| `slack_thread_context` | No       | Slack thread context for agents triggered from Slack                       |
| `start_workflow`       | No       | Whether to start the Temporal workflow immediately (default: `True`)       |

### Adding a new origin product

If your product doesn't have an `OriginProduct` entry yet,
add one to `Task.OriginProduct` in `products/tasks/backend/models.py`:

```python
class OriginProduct(models.TextChoices):
    ERROR_TRACKING = "error_tracking", "Error Tracking"
    # ...
    YOUR_PRODUCT = "your_product", "Your Product"
```

Then create and run a Django migration.

## Interactive mode

Interactive mode enables real-time conversational agents that stream responses to the browser via Server-Sent Events (SSE). Use it when building chat interfaces or other conversational experiences on top of sandboxed agents.

Interactive mode requires the `phai-sandbox-mode` feature flag (bypassed when `DEBUG=1`).

### How interactive streaming works

When you create a task with `mode="interactive"`, the Temporal workflow starts a `relay_sandbox_events` activity alongside the agent server. This activity:

1. Connects to the sandbox's SSE endpoint (`GET /events`)
2. Relays each event into a per-run Redis stream
3. Reconnects on transient failures (up to 5 attempts)

A Django SSE endpoint reads from this Redis stream and pushes events to the browser. This queue-based decoupling means the browser's read speed doesn't affect the sandbox relay.

**Redis stream configuration:**

| Setting         | Value                          |
| --------------- | ------------------------------ |
| Stream key      | `task-run-stream:{run_id}`     |
| Max entries     | 2000                           |
| Stream TTL      | 60 minutes                     |
| Wait timeout    | 120 seconds (sandbox startup)  |

### Turn detection

The agent signals when its turn is complete by sending a `_posthog/turn_complete` notification. The SSE stream uses this to know when to stop streaming for the current turn.

Terminal notifications that end the session entirely:

- `_posthog/task_complete` — agent finished successfully
- `_posthog/error` — agent encountered an error

A 60-second idle timeout acts as a safety fallback if no turn-complete signal arrives.

### Follow-up messages

After the first turn completes, the browser can send follow-up messages. The Django layer signals the Temporal workflow via `ProcessTaskWorkflow.send_followup_message`, which triggers the `send_followup_to_sandbox` activity to deliver the message to the running sandbox.

### Snapshot-based resumption

When a task run reaches a terminal state, the workflow creates a filesystem snapshot of the sandbox via `create_resume_snapshot`. If the user sends another message, the system creates a new task run that resumes from that snapshot:

1. Look up the previous run's `snapshot_external_id` from its state
2. Create a new `TaskRun` with the snapshot ID in its extra state
3. Provision a new sandbox from the snapshot
4. Continue the conversation

### Conversation model integration

Interactive sandboxes are linked to a `Conversation` model through two fields:

- `sandbox_task_id` — permanent link to the `Task`
- `sandbox_run_id` — link to the current `TaskRun` (updated on snapshot resume)

A Redis mapping (`conversation-sandbox:{conversation_id}`) provides fast lookups from conversation to task/run IDs with a 24-hour TTL. If the Redis mapping expires, the system falls back to the conversation's database fields.

## Fine-grained access tokens

Every sandboxed agent gets a scoped OAuth access token that controls what PostHog resources it can access.
Tokens expire after 6 hours and are scoped to a single team.

### Scope presets

Use the `posthog_mcp_scopes` parameter to control access:

| Preset             | What it grants                                                                                            | When to use                                                                                        |
| ------------------ | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `"read_only"`      | Read access to actions, cohorts, dashboards, experiments, feature flags, insights, queries, surveys, etc. | Agent only needs to read data for analysis or reporting                                            |
| `"full"` (default) | Read + write access to all MCP-exposed resources                                                          | Agent needs to create or modify PostHog resources (e.g., create feature flags, update experiments) |

### Custom scopes

For more granular control, pass an explicit list of scopes instead of a preset:

```python
Task.create_and_run(
    # ...
    posthog_mcp_scopes=["query:read", "feature_flag:read", "experiment:read"],
)
```

Available read scopes: `action:read`, `cohort:read`, `dashboard:read`, `error_tracking:read`,
`event_definition:read`, `experiment:read`, `feature_flag:read`, `insight:read`,
`project:read`, `query:read`, `survey:read`, and others.

Available write scopes: `action:write`, `cohort:write`, `dashboard:write`,
`experiment:write`, `feature_flag:write`, `insight:write`, `survey:write`, and others.

Internal scopes (`task:write`, `llm_gateway:read`) are always added automatically.

See `posthog/temporal/oauth.py` for the full list.

> **Principle of least privilege**: default to `"read_only"` unless your agent genuinely needs to create or modify resources.
> This limits blast radius if the agent misbehaves.

## PostHog MCP server

The sandbox comes with access to the PostHog MCP server,
which exposes PostHog resources as tools the agent can call —
listing feature flags, running HogQL queries, searching session recordings, etc.

The MCP server is ready to use today.
For details on available tools, see [Implementing MCP tools](/handbook/engineering/ai/implementing-mcp-tools).

### Skills (coming soon)

Skills are job-to-be-done templates that teach agents _how_ to compose MCP tools into workflows.
They provide domain knowledge, query patterns, and step-by-step guidance.

Skills are currently used by PostHog Code and Max.
Support for sandboxed agents is coming soon.

For details on writing skills, see [Writing skills](/handbook/engineering/ai/writing-skills).

## Code execution

Agents run inside an isolated sandbox with full code execution capabilities.
They can:

- Read, write, and execute files in the cloned repository
- Install dependencies (npm, pip, etc.)
- Run tests, linters, and build tools
- Create git branches, commits, and pull requests
- Execute arbitrary shell commands within the container

### Sandbox isolation

|           | Production (Modal)                     | Local dev (Docker)                      |
| --------- | -------------------------------------- | --------------------------------------- |
| Isolation | gVisor kernel-level sandboxing         | Standard Docker container               |
| Network   | Configurable via `SandboxEnvironment`  | Host network via `host.docker.internal` |
| Image     | `ghcr.io/posthog/posthog-sandbox-base` | Local Dockerfile build                  |
| Auth      | Modal connect token                    | No token needed                         |

### Network access

Network access is configured per-team via `SandboxEnvironment`:

- **Trusted** — only allows access to a default set of trusted domains (GitHub, npm, PyPI, etc.)
- **Full** — unrestricted network access
- **Custom** — explicit allowlist of domains, optionally including the trusted defaults

## Local development

See the [Cloud runs setup guide](https://github.com/PostHog/posthog/blob/master/products/tasks/backend/temporal/process_task/SETUP_GUIDE.md)
for step-by-step instructions on running sandboxed agents locally with Docker.

Key requirements:

- `DEBUG=1` and `SANDBOX_PROVIDER=docker` in your `.env`
- A GitHub App with Contents and Pull Requests permissions
- The `tasks` feature flag enabled at 100%
- The `phai-sandbox-mode` feature flag enabled (for interactive mode)
- Temporal running (starts automatically via mprocs with `./bin/start`)

## Questions?

If you're unsure whether a sandboxed agent is the right fit for your use case,
ask in **#team-posthog-ai** on Slack.
