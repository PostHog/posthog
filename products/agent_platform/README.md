# Agent platform

The agent platform is PostHog's system for authoring, publishing, and running AI agents.
It includes the Django control plane, the Node.js runtime services, shared contracts, built-in tools, sandbox execution, and end-to-end tests.

This directory contains the active implementation.
The earlier v2 cutover is complete: the models use their final names, Django owns the schema, and all agent platform tables live in the dedicated `agent_platform` product database.

## How it works

The platform has two main paths:

- **Authoring:** clients use the Django API to create an application, edit draft revisions, manage secrets and bundle files, validate the result, and promote a revision to live.
- **Execution:** external triggers reach `agent-ingress`, while scheduled triggers are fired by `agent-janitor`. Both create sessions for the application's live revision. `agent-runner` claims each session, runs the model loop, dispatches tools, and persists the result.

```text
Authors and API clients
        │
        ▼
Django API ───────────────► agent-janitor
        │                    bundle, memory, and operational APIs
        │
        ▼
agent_platform database
 applications, revisions, sessions, users, credentials, approvals
        ▲
        │
External triggers ──► agent-ingress ──► agent-runner ──► tools and sandboxes
Scheduled triggers ─► agent-janitor ───────▲
                          │                 │
                          └── sessions ─────┘
```

Agent bundles and agent memory are stored in S3-compatible object storage.
The services authenticate internal requests with audience-bound JWTs signed by `AGENT_INTERNAL_SIGNING_KEY`.

## Repository layout

### Django control plane

[`backend/`](backend/) owns the database schema and the project-scoped REST API.

- [`backend/models.py`](backend/models.py) defines the authoring and runtime models.
- [`backend/presentation/`](backend/presentation/) contains serializers and viewsets for applications, revisions, sessions, users, approvals, memory, and fleet operations.
- [`backend/routes.py`](backend/routes.py) registers routes under `/api/projects/<project_id>/`.
- [`backend/logic/`](backend/logic/) contains the janitor and ingress clients, spec helpers, skill resolution, and generated cross-language contracts.
- [`backend/migrations/`](backend/migrations/) is the only source of database migrations for the platform. The Node.js services consume the schema but do not manage it.
- [`frontend/generated/`](frontend/generated/) contains generated TypeScript API clients and schemas. Do not edit these files by hand.

The primary authoring resources are:

- `agent_applications`: application CRUD, invocation, session history, users, approvals, and statistics.
- `agent_applications/<application_id>/revisions`: draft editing, bundle operations, validation, promotion, archiving, secrets, and skill references.
- `agent_applications/<application_id>/memory`: application-scoped memory management.
- `agent_native_tools`: the built-in tool catalog.
- `agent_fleet`: cross-application operational views for a project.

### Runtime services

[`services/`](services/) contains the Node.js packages that run agents:

- [`agent-ingress/`](services/agent-ingress/) accepts chat, webhook, Slack, and MCP traffic; authenticates callers; resolves live revisions; creates sessions; and streams lifecycle events.
- [`agent-runner/`](services/agent-runner/) claims queued sessions, builds the model context, runs the model loop, dispatches native, MCP, and custom tools, and records results.
- [`agent-janitor/`](services/agent-janitor/) exposes internal bundle, revision, memory, session, and maintenance APIs used by Django; fires cron triggers; and periodically recovers stale runtime state.
- [`agent-sandbox-host/`](services/agent-sandbox-host/) is the process inside isolated custom-tool sandboxes.
- [`agent-shared/`](services/agent-shared/) is the canonical home for the agent spec, persistence clients, identity and credential contracts, bundle storage, memory, transports, sandbox adapters, and runtime utilities.
- [`agent-tools/`](services/agent-tools/) contains PostHog-provided native tools and their authorization rules.
- [`agent-tests/`](services/agent-tests/) is the end-to-end harness for full authoring and execution flows.
- [`agents/`](services/agents/) builds the unified production image for ingress, runner, janitor, and migrations.

## Core data model

All models are team-scoped and stored in the dedicated product database.
The central records are:

- **Application:** the stable agent identity, globally unique routing slug, metadata, and pointer to the live revision.
- **Revision:** a versioned agent definition containing the structural spec, bundle location, encrypted environment, skill references, and revision lineage. Draft content is editable; promotion freezes the spec and bundle, while environment keys remain rotatable.
- **Session:** one execution, including trigger metadata, conversation state, status, output, usage, errors, and timing.
- **Agent user and transport binding:** the caller's transport identity and its verified canonical identity for an application.
- **Credentials and identity links:** short-lived session credentials, reusable linked credentials, and pending identity-link state.
- **Tool approval request:** a durable approval gate for tool calls that require human confirmation.
- **Sandbox instance:** lifecycle state for isolated custom-tool execution.

Revision state moves through:

```text
draft → ready → live
          │       │
          └───────┴──► archived
```

The canonical agent spec is [`AgentSpecSchema`](services/agent-shared/src/spec/spec.ts).
It defines the model, triggers, tools, MCP connections, skills, secrets, limits, identity policy, and runtime behavior.
Keep Python helpers and generated contracts synchronized with this schema.

## Development

Read [`docs/local-dev.md`](docs/local-dev.md) for stack setup, local MCP usage, smoke tests, and debugging recipes.
The `agent_runtime` development capability starts the database and the main runtime services through `hogli start`.

Common checks:

```bash
# Django tests and lint
hogli test products/agent_platform/backend
pnpm --filter @posthog/products-agent-platform backend:lint

# Runtime package tests
pnpm --filter @posthog/agent-ingress test
pnpm --filter @posthog/agent-runner test
pnpm --filter @posthog/agent-janitor test
pnpm --filter @posthog/agent-shared test
pnpm --filter @posthog/agent-tools test

# Full platform flow
pnpm --filter @posthog/agent-tests test
```

After changing a serializer or viewset, regenerate OpenAPI clients and MCP schemas:

```bash
hogli build:openapi
```

## Further reading

- [`docs/identity-and-tools.md`](docs/identity-and-tools.md): identity, credentials, approvals, and tool dispatch.
- [`docs/custom-tools.md`](docs/custom-tools.md): custom-tool contract and sandbox boundary.
- [`docs/coherence-overview.md`](docs/coherence-overview.md): cross-language contract generation and validation.
- [`AGENTS.md`](AGENTS.md): implementation rules and pointers for contributors working in this product.
