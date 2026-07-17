# Agent platform — architecture at a glance

The high-level shape of the v2 agent platform. Two companion docs go deeper:
[services.md](services.md) (what each process does) and
[identity-and-tools.md](identity-and-tools.md) (the request → identity → tools
flow). For hacking locally see [local-dev.md](local-dev.md).

## Two planes, one product

The platform splits into a **control plane** (author + promote agents) and a
**data plane** (run them). They share nothing but two databases.

```mermaid
flowchart TB
    subgraph control["Control plane — authoring"]
        django["Django<br/>products/agent_platform/backend<br/>REST: /api/projects/&lt;team&gt;/agent_applications/*"]
        janitor["agent-janitor :3031<br/>bundle CRUD · freeze/validate/clone<br/>/native_tools · sweep timer"]
        django -- "HTTP (x-internal-secret JWT)" --> janitor
    end

    subgraph data["Data plane — runtime"]
        ingress["agent-ingress :3030<br/>triggers · routing · auth/identity · enqueue"]
        runner["agent-runner (no inbound HTTP)<br/>claim → load → model loop → tools → persist"]
        ingress -- "enqueue" --> queue[("agent_session<br/>queue")]
        queue -- "claim" --> runner
    end

    subgraph dbs["Databases"]
        pgdb[("POSTHOG_DB<br/>agent_application<br/>agent_revision")]
        agentdb[("AGENT_DB<br/>agent_session · agent_user<br/>identity · approvals · sandbox")]
    end

    mcp["MCP / console / Claude Code<br/>(authoring client)"] -->|generated MCP tools| django
    client["chat · webhook · Slack · cron · MCP"] --> ingress

    janitor -- writes bundle metadata --> pgdb
    django -- read/write --> pgdb
    ingress -- read revision --> pgdb
    runner -- read revision + bundle --> pgdb
    ingress -- write session/user --> agentdb
    runner -- write session/conversation --> agentdb
    queue -.-> agentdb
```

**Rule of thumb:** authoring writes flow Django → janitor → `POSTHOG_DB`.
Runtime writes flow ingress/runner → `AGENT_DB`. Django **never** touches the
bundle filesystem or the runtime tables directly; the node side **never**
writes the application/revision tables.

## The data model

```mermaid
erDiagram
    agent_application ||--o{ agent_revision : "has"
    agent_application ||--o| agent_revision : "live_revision"
    agent_revision ||--o{ agent_session : "runs"
    agent_application ||--o{ agent_user : "knows"
    agent_user ||--o{ agent_session : "starts"
    agent_user ||--o{ agent_identity_credential : "links"

    agent_application {
        int team_id
        string slug
        json encrypted_env
        uuid live_revision_id
    }
    agent_revision {
        string state "draft|ready|live|archived"
        string bundle_uri
        json spec "model,triggers,tools,mcps,skills..."
    }
    agent_session {
        string state
        string external_key
        json conversation
        json principal
    }
    agent_user {
        string principal_kind "slack|jwt|posthog|..."
        string principal_id
    }
    agent_identity_credential {
        string provider
        json encrypted_credentials
        string subject
    }
```

`agent_application` + `agent_revision` live in **POSTHOG_DB** (Django-owned).
Everything else lives in **AGENT_DB** (node-owned). In dev both are the same
local Postgres (`posthog` + `agent_runtime_queue`); in prod they are separate
physical instances.

## The spec is the contract

A revision's `spec` (JSONB) is the structural truth for an agent. It is
validated by `AgentSpecSchema` (zod) in
[agent-shared/src/spec/](../services/agent-shared/src/spec/) — Django validates
loosely and passes it through.

```mermaid
flowchart LR
    spec["revision.spec"] --> model["model"]
    spec --> triggers["triggers[]<br/>chat·webhook·slack·cron·mcp"]
    spec --> tools["tools[]<br/>native·custom·client"]
    spec --> mcps["mcps[]<br/>external MCP servers"]
    spec --> skills["skills[]"]
    spec --> idp["identity_providers[]<br/>posthog·oauth2"]
    spec --> secrets["secrets[]"]
    spec --> limits["limits<br/>turns·tools·wall·mem·cpu"]
    spec --> entry["entrypoint (agent.md)"]
```

## Revision lifecycle

A revision is authored as a `draft`, frozen to `ready` (bundle becomes
immutable, spec validated server-side), promoted to `live` (the slug now
routes to it), and superseded revisions go `archived`. Ingress only enqueues
against the **live** revision.

```mermaid
stateDiagram-v2
    [*] --> draft: create
    draft --> draft: edit bundle / spec
    draft --> ready: freeze (validate + seal bundle)
    ready --> live: promote (set live_revision_id)
    live --> archived: superseded by newer live
    ready --> archived: discarded
```

## Supporting infrastructure

| Concern                         | Backed by                                                               | Interface (agent-shared)            |
| ------------------------------- | ----------------------------------------------------------------------- | ----------------------------------- |
| Session queue                   | Postgres (`AGENT_DB`)                                                   | `PgSessionQueue`                    |
| Bundle store                    | S3 (prod) / SeaweedFS (test)                                            | `BundleStore` / `S3BundleStore`     |
| Event bus (SSE fan-out)         | Redis                                                                   | `RedisSessionEventBus`              |
| Credential broker (per-session) | Redis / in-memory                                                       | `CredentialBroker`                  |
| Log sink                        | Kafka → ClickHouse                                                      | `KafkaLogSink`                      |
| Analytics                       | PostHog capture                                                         | `CaptureAnalyticsSink`              |
| Custom-tool sandbox             | Docker (local) / Modal (prod)                                           | `SandboxImpl` / `selectSandboxPool` |
| Model calls                     | direct providers or [ai-gateway](https://github.com/PostHog/ai-gateway) | pi-ai (`AGENT_USE_AI_GATEWAY`)      |

Every cross-process boundary is an **interface with exactly one prod impl**.
The e2e harness wires those same real classes against local services — no
in-memory fakes — so shape drift can't hide. The only test-time swap is the
in-process sandbox and pi-ai's `faux` model provider.
