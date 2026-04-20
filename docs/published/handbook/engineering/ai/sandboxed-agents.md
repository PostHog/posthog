---
title: Using sandboxed agents
sidebar: Docs
showTitle: true
---

Sandboxed agents are background AI agents that run in isolated cloud containers with access to PostHog data,
GitHub repositories, and code execution.
Use them when your feature needs an autonomous agent that reads PostHog data, writes code, and produces artifacts like PRs or reports.

For simpler LLM calls (summarization, translation, classification),
skip this page and use the LLM gateway (`get_llm_client()`) directly —
it's simpler and doesn't need a sandbox.

## When to use what

| Example                                                                                         | Solution                           |
| ----------------------------------------------------------------------------------------------- | ---------------------------------- |
| Signals team building an enrichment pipeline that generates reports from PostHog analytics data | Sandboxed agent (this page)        |
| Conversations team building a support agent that queries PostHog and customer documentation     | Sandboxed agent (this page)        |
| LLM analytics summarizing a funnel, generating a natural-language insight title                 | LLM gateway via `get_llm_client()` |
| Not sure                                                                                        | Ask in `#team-posthog-ai`          |

**Rule of thumb**: if the LLM needs to _do things_ (query data, read files, create branches, open PRs), use a sandboxed agent.
If it just needs to _answer a question_ given some context you already have, use the LLM gateway.

## How it works

A sandboxed agent runs inside an isolated cloud container (Modal in production, Docker locally).
The system provisions the sandbox, clones a GitHub repo, starts an agent server, and waits for the agent to finish.

```text
Your product code
    │
    │  Task.create_and_run(...)
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

| Parameter                | Required | Description                                                                |
| ------------------------ | -------- | -------------------------------------------------------------------------- |
| `team`                   | Yes      | The team this task belongs to                                              |
| `title`                  | Yes      | Human-readable task title                                                  |
| `description`            | Yes      | Detailed description of what the agent should do                           |
| `origin_product`         | Yes      | Which product created this task (see `Task.OriginProduct` choices)         |
| `user_id`                | Yes      | User ID — used for feature flag validation and creating the scoped API key |
| `repository`             | Yes      | GitHub repo in `org/repo` format (e.g., `posthog/posthog-js`)              |
| `posthog_mcp_scopes`     | No       | Scope preset or explicit scope list (default: `"full"`)                    |
| `create_pr`              | No       | Whether the agent should create a PR (default: `True`)                     |
| `mode`                   | No       | Execution mode (default: `"background"`)                                   |
| `slack_thread_context`   | No       | Slack thread context for agents triggered from Slack                       |
| `start_workflow`         | No       | Whether to start the Temporal workflow immediately (default: `True`)       |
| `sandbox_environment_id` | No       | ID of a `SandboxEnvironment` to apply network restrictions (see below)     |

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

### Skills

Skills are job-to-be-done templates that teach agents _how_ to compose MCP tools into workflows.
They provide domain knowledge, query patterns, and step-by-step guidance.

Skills are pre-installed in the sandbox base image and available to all sandboxed agents.
They're copied to three discovery locations during image build:

- `/scripts/plugins/posthog/skills/` – plugin discovery
- `~/.agents/skills/` – Codex agent discovery
- `~/.claude/skills/` – Claude Code CLI discovery

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

To apply network restrictions from your product code,
create a `SandboxEnvironment` and pass its ID to `Task.create_and_run`:

```python
from products.tasks.backend.models import SandboxEnvironment, Task

# 1. Create an environment (once, or look up an existing one)
env = SandboxEnvironment.objects.create(
    team=team,
    created_by=user,
    name="Restricted agent env",
    network_access_level="custom",  # "full" | "trusted" | "custom"
    allowed_domains=["github.com", "api.example.com"],
    include_default_domains=True,  # merge GitHub, npm, PyPI defaults
)

# 2. Pass its ID when creating the task
task = Task.create_and_run(
    team=team,
    title="My restricted task",
    description="...",
    origin_product=Task.OriginProduct.YOUR_PRODUCT,
    user_id=user.id,
    repository="org/repo",
    sandbox_environment_id=str(env.id),
)
```

The temporal workflow resolves the allowed domains at execution time from the environment,
so updates to the environment take effect on the next run.
Domain restrictions are enforced at the syscall level by `agentsh` via ptrace —
the agent cannot bypass them through proxy settings or DNS tricks.

Environments can also be managed via the REST API (`SandboxEnvironmentViewSet`)
or the PostHog Code settings UI.

## Local development

To set up sandboxed agents for local development:

1. Create a personal dev GitHub App (see the [Cloud runs setup guide](https://github.com/PostHog/posthog/blob/master/docs/internal/sandboxes-setup-guide.md#github-app) for details)
2. Run `python manage.py setup_background_agents`
3. Run `hogli start`

The setup command is idempotent and handles:

- Writing required env vars (`OIDC_RSA_PRIVATE_KEY`, `SANDBOX_JWT_PRIVATE_KEY`, `DEBUG`, `SANDBOX_PROVIDER`) to your `.env`
- Creating the Array OAuth application
- Enabling the `tasks` feature flag for all teams
- Building the agent skills bundle

For advanced setup options (Modal sandboxes, local agent packages), see the [Cloud runs setup guide](https://github.com/PostHog/posthog/blob/master/docs/internal/sandboxes-setup-guide.md).

## Questions?

If you're unsure whether a sandboxed agent is the right fit for your use case,
ask in **#team-posthog-ai** on Slack.
