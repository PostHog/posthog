# Plan: Agent platform — posthog implementation

## Context

Companion to [`agent-stack/docs/agent-platform.md`](https://github.com/PostHog/agent-stack/blob/main/docs/agent-platform.md). That doc covers the full system; this one is the posthog-side build plan. Where the two conflict, this plan wins for posthog-side concerns.

Two things we own here:

1. **Management plane** — a new flag-gated product under `products/agents/` (Django app + viewsets + frontend), modelled on the existing [`products/deployments/`](../../products/deployments) scaffold from #58421.
2. **Runtime** — a new node service that executes Claude Agent SDK sessions. Lives under `nodejs/src/agents/` (or a new `packages/agent-runtime/` workspace — see "Runtime placement" below). **The session executor is built on top of cyclotron-v2.** A "session" is a long-lived cyclotron job that gets re-scheduled each tool boundary.

The runtime split (API ingress + worker) from the agent-stack doc still holds. This plan refines what each half looks like inside the posthog monorepo and which existing primitives we lean on.

---

## Why cyclotron-v2 for sessions

A Claude Agent SDK run looks structurally identical to the existing CDP hog-flow execution model:

- Long-running, stateful work that crosses many tool / model-call boundaries.
- Each boundary is a natural suspend/resume point — the worker doesn't need to hold a stack frame across a tool call, it can serialize state and re-queue.
- Concurrent runs of the same agent are independent; ordering doesn't matter.
- Need lock-based concurrency so a session is owned by exactly one worker instance, with heartbeats so a crashed worker's sessions get reaped.
- Need a janitor for stalled/poisoned runs.

cyclotron-v2 already gives us all of this. From the cyclotron survey:

| cyclotron-v2 primitive | Agent platform reuse |
| --- | --- |
| `JobState: available \| running \| completed \| failed \| canceled` ([`rust/cyclotron-core/src/types.rs:10`](../../rust/cyclotron-core/src/types.rs)) | Drop-in for `AgentSession.state`. Add no new states v1. |
| `lock_id` + `last_heartbeat` + `FOR UPDATE SKIP LOCKED` dequeue ([`nodejs/src/cdp/services/cyclotron-v2/worker.ts:88`](../../nodejs/src/cdp/services/cyclotron-v2/worker.ts)) | Worker owns a session via lock; heartbeats every N seconds while inside an SDK turn. |
| `state: BYTEA` payload ([`rust/cyclotron-node-migrations/20260303000001_initial_schema.sql:9`](../../rust/cyclotron-node-migrations/20260303000001_initial_schema.sql)) | Persist Claude Agent SDK conversation/turn state between suspensions. |
| `reschedule({ scheduledAt, state })` ([`nodejs/src/cdp/services/cyclotron-v2/worker.ts:161`](../../nodejs/src/cdp/services/cyclotron-v2/worker.ts)) | After every tool call (especially sandbox tool calls that might take seconds), worker reschedules with updated state instead of blocking. |
| Janitor — stall recovery + poison-pill detection ([`nodejs/src/cdp/services/cyclotron-v2/janitor.ts`](../../nodejs/src/cdp/services/cyclotron-v2/janitor.ts)) | Same daemon, no fork. Reaps crashed sessions; poison-pill threshold catches sessions that can't get past a tool. |
| `parent_run_id` for batch grouping | Use for "trigger fanout" — one cron firing creates N sessions sharing a parent run id, so the UI can show them grouped. |
| `queue_name` + `priority` | Per-app or per-tier queue isolation. v1 = single queue; schema is open for v2 fairness work. |
| `function_id` (UUID) | Repurpose as `revision_id` so we can quickly find all sessions for a given revision (useful for promotion + reaper). |

What we add on top:

- **Heartbeat-from-inside-the-SDK.** SDK tool callbacks tick the cyclotron heartbeat. Long Anthropic streaming responses tick on each chunk.
- **Session event bus.** Cyclotron stores final state, not intermediate frames. SSE streaming for `/listen` lives in a Redis pub-sub keyed by `session_id`. The session row + final-state blob is the durable record; the bus is best-effort.
- **`AgentSession` mirror table in the main posthog Postgres.** Cyclotron jobs live in their own DB (`cyclotron_node`); we still want a row in the main DB for the management plane (foreign keys to `Team`, `AgentApplication`, `Revision`; activity-log integration; UI queries). The runtime writes both — the cyclotron job is the work item, the `AgentSession` row is the user-visible record.

### What we don't reuse

- **CDP's hog-function executor wiring** ([`nodejs/src/cdp/services/job-queue/job-queue-postgres-v2.ts`](../../nodejs/src/cdp/services/job-queue/job-queue-postgres-v2.ts)). It assumes hog VM state and CDP-shaped invocation payloads. Agent runtime gets its own thin adapter around cyclotron-v2 — same patterns, different shape.
- **CDP consumers** (`nodejs/src/cdp/consumers/cdp-cyclotron-worker*.consumer.ts`). New consumer process under `nodejs/src/agents/consumers/` so we can size, deploy, and roll back independently. The agent-stack plan calls this out: agent runtime has very different load shape from CDP, mixing them means we can't size either.

---

## Part A — `products/agents/` Django app

Mirror the [`products/deployments/`](../../products/deployments) scaffold from #58421. That PR established the per-product layout we should follow exactly:

```
products/agents/
  __init__.py
  product.yaml             # name + owners
  manifest.tsx             # frontend scenes + routes + flag
  package.json
  backend/
    __init__.py
    apps.py                # Django app config
    access.py              # scope wiring
    models.py              # AgentApplication, Revision, Secret, Session, SandboxInstance
    api/                   # viewsets
    services/              # bundle validator, S3 helpers
    migrations/
    management/
    test/
  frontend/                # scenes (list, detail, sessions, secrets)
  mcp/                     # MCP tool defs (later)
```

### Models

All inherit `UUIDModel` ([`posthog/models/utils.py:183`](../../posthog/models/utils.py)) — uuid7 PKs.

**`AgentApplication`** (team-scoped)
- `team: FK(Team)`, `name`, `slug` (unique, see open Q1), `description`
- `live_revision: FK(Revision, null=True)` — pointer-swap on promotion
- Soft delete (`deleted: bool`)
- Activity-logged via `log_activity_from_viewset` ([`posthog/api/hog_function.py:640`](../../posthog/api/hog_function.py))

**`Revision`** (immutable per deploy)
- `application: FK(AgentApplication)`
- `state: enum(pending_upload | uploaded | validating | ready | failed)` — Django state, distinct from cyclotron job state
- `bundle_s3_key`, `bundle_size`, `bundle_sha256` — content-hash binding for the presigned PUT
- `top_level_config: JSONField` — validated synchronously at deploy start
- `parsed_manifest: JSONField(null=True)` — populated by async validator: full agent/tool/skill resolution
- `validation_report: JSONField(null=True)` — structured errors on failure
- `created_by: FK(User)`, `created_at`
- Index: `(application_id, state, created_at desc)` for "list ready revisions"

**`PreviewBinding`**
- `application: FK(AgentApplication)`, `revision: FK(Revision)`, `subdomain_suffix: str`
- Lets `ass preview` route a non-promoted revision

**`AgentApplicationSecret`**
- `application: FK(AgentApplication)`, `name: str` (unique per app), `encrypted_value: EncryptedJSONStringField`
- Use `EncryptedJSONStringField` from [`posthog/helpers/encrypted_fields.py:137`](../../posthog/helpers/encrypted_fields.py) — same pattern as `Integration.sensitive_config`
- Plaintext never returned by REST API after creation
- Decryption only via internal API endpoint, audit-logged per call

**`AgentSession`** (mirror of cyclotron job in main DB)
- `team: FK(Team)`, `application: FK(AgentApplication)`, `revision: FK(Revision)`
- `cyclotron_job_id: UUID` — points at the actual job in the cyclotron DB
- `state: enum` — mirrors cyclotron's `JobState`. Updated by the worker on transition.
- `trigger_type: str`, `trigger_payload: JSONField`
- `input: JSONField`, `output: JSONField(null=True)`, `error: JSONField(null=True)`
- `parent_run_id: UUID(null=True)` — same id as cyclotron's `parent_run_id` for trigger fanouts
- `started_at`, `last_heartbeat_at`, `completed_at`
- `runtime_instance: str(null=True)` — for attribution

**`SandboxInstance`** (tracks Modal sandboxes)
- `application: FK(AgentApplication)`, `revision: FK(Revision)`
- `modal_sandbox_id: str`, `state: enum(provisioning | ready | terminating | terminated)`
- `created_at`, `last_used_at`, `terminated_at`
- v1 = at most one per `(application, revision)`. Schema does not preclude more — no unique constraint, just an in-runtime check.

### Migrations

Standard Django migrations under `products/agents/backend/migrations/`. Follow the [`django-migrations`](../../.claude/skills/django-migrations) skill (non-blocking index/constraint patterns, multi-phase backfills if anything ends up needing one).

### API (DRF + OAuth)

New scope object: `agent_application` (and `agent_secret` for scoped secret access). Add to [`posthog/scopes.py:16`](../../posthog/scopes.py).

Viewsets follow the `TeamAndOrgViewSetMixin` + `scope_object` pattern from [`posthog/api/hog_function.py:469`](../../posthog/api/hog_function.py).

Endpoints (project-scoped `/api/projects/{team_id}/...`):

- `agent_applications/` — CRUD + soft delete
  - `POST /:id/start_deploy` → returns `{ revision_id, presigned_put_url, expires_at, max_size, required_sha256 }`
  - `POST /:id/complete_upload` → CLI ping fallback to S3-event trigger
  - `POST /:id/promote` → swap `live_revision` to a `ready` revision
- `revisions/` — list + retrieve (read-only). Includes `validation_report` and `parsed_manifest`.
- `preview_bindings/` — CRUD
- `agent_application_secrets/` — create/list/delete (no read of plaintext)
- `agent_sessions/` — list + retrieve. Filters: `application_id`, `state`, `parent_run_id`, time range.

**Internal-only endpoints** (consumed by the runtime, not by users):

- `GET /internal/agents/applications/{id}/resolve` — given a domain or app id, returns the live revision + parsed manifest. Cacheable for ~5s.
- `POST /internal/agents/secrets/{app_id}/decrypt` — returns plaintext for a named set of secrets. Audit-logged. Use a separate internal scope, not exposed in OAuth UI.

Keep these on `INTERNAL_API_SCOPE_OBJECTS` ([`posthog/scopes.py:121`](../../posthog/scopes.py)) so they don't appear in PAT creation flows.

### Async bundle validation

Celery task in `posthog/tasks/agents.py`, registered via the existing `posthog/tasks/__init__.py` import-everything pattern. New `CeleryQueue.AGENTS` enum entry.

Trigger:
- Primary: S3 object-created event → SQS → Celery (existing infra; check whether posthog already wires SQS → Celery for any other artifact upload — if not, fallback below is the v1 path).
- Fallback: CLI's `complete_upload` ping. Idempotent — safe if S3 event also fires.

Steps (follow agent-stack plan §C exactly): re-fetch revision → set `validating` → stream + verify size+hash → unpack with size/file-count caps → walk manifests → resolve referenced ids against built-ins registry → static checks (secrets exist, allow-listed actions exist on referenced tools, triggers valid) → on success set `ready` + persist `parsed_manifest`; on failure set `failed` + structured `validation_report`.

Validators kept pure (`(bytes) -> (parsed, errors)`), no I/O. Reusable from CLI for `ass build` later.

### Frontend

Mirror [`products/deployments/manifest.tsx`](../../products/deployments/manifest.tsx). Behind a `FEATURE_FLAGS.AGENTS` flag, marked `tags: ['alpha']`.

v1 scenes:
- `AgentApplications` (list)
- `AgentApplication` (detail: revisions, secrets, sessions, sandbox state tabs)
- `AgentSession` (single-session inspection)

Use the [`scene-menu-bar`](../../.claude/skills/scene-menu-bar) and [`making-scenes-tab-aware`](../../.claude/skills/making-scenes-tab-aware) conventions for tabs in the application detail scene.

Routes:
- `/agents` → list
- `/agents/:slug` → detail (default tab: revisions)
- `/agents/:slug/sessions/:session_id` → session detail

CLI is the primary deploy surface in v1; this UI is for management and observability.

---

## Part B — Runtime (node)

Two processes, deployed independently, both new:

```
nodejs/src/agents/
  api/                     # process 1: ingress + session lifecycle endpoints
  worker/                  # process 2: cyclotron-v2 consumer that runs Claude Agent SDK
  shared/                  # types, manifest reader, signed-payload helpers
  bin/
    api-server.ts
    worker.ts
```

### Runtime placement: `nodejs/` vs `packages/agent-runtime/`

The agent-stack doc suggests `packages/agent-runtime/` to avoid plugin-server cruft. **Recommendation: start in `nodejs/src/agents/`.** Reasons:

- All the cyclotron-v2 building blocks are already wired into `nodejs/` (DB connections, Kafka, Redis, Prometheus, the consumer harness). Re-creating that in a new workspace is a multi-week tax.
- The legacy plugin-server concepts the agent-stack plan worries about live in `nodejs/src/worker/` and `nodejs/src/main/`. We can scope our new code to `nodejs/src/agents/` and not import from those paths — codeowner rules + lint can enforce.
- We can extract to its own workspace later if/when it earns it. Reversible.

We should still split the **process** in two from day one (separate entrypoints, separate deploys). The split in the agent-stack plan is about runtime topology, not source-tree topology.

### API process (`nodejs/src/agents/api/`)

- Express/Fastify server. All `*.agents.posthog.com` traffic terminates here.
- Domain → `(application, revision)` resolved via the Django internal `/internal/agents/applications/{id}/resolve` endpoint. In-process LRU keyed by revision id; promotion invalidates by revision id (cheap).
- Implements `/run`, `/listen/:id`, `/send/:id`, `/webhooks/:provider`, `/health`, `/status`.
- `/run` writes an `AgentSession` row + enqueues a cyclotron job, returns `{ session_id }` immediately.
- `/listen` subscribes to the Redis pub-sub channel `agent_session:{session_id}` for SSE.
- `/send` publishes a message into `agent_session:{session_id}:input` — worker picks it up at the next yield.

**Hard rule (matches agent-stack plan):** API process imports zero Anthropic / Claude Agent SDK / Modal code, and never decrypts a secret. Lint rule to enforce. The blast-radius win is the whole point.

### Worker process (`nodejs/src/agents/worker/`)

Cyclotron-v2 consumer that:

1. Dequeues a session job (cyclotron handles the lock + heartbeat).
2. Loads `parsed_manifest` from cached internal-API resolve.
3. Restores Claude Agent SDK state from the cyclotron job's `state` BYTEA.
4. Runs one "turn" — until the next tool boundary or completion.
5. Two cases:
   - **Completion** → `job.ack()`, write final `output` to `AgentSession`, publish completion to pub-sub.
   - **Suspension** (long-running tool, sandbox call, waiting on `/send`) → `job.reschedule({ scheduledAt, state: serialized_sdk_state })`. Heartbeat keeps ticking until reschedule, so we don't get reaped mid-turn.
6. Streams events to the pub-sub bus throughout.

Tool execution split:
- **Meta tools** — in-process. Trivial.
- **Referenced (built-in) tools** — in-process. Built-ins registry is a hardcoded map in v1 (e.g. `nodejs/src/agents/worker/builtins/index.ts`). Validator imports the same map so unknown ids fail before deploy (agent-stack open Q9 — recommend yes, share the registry from day one).
- **Local tools** — proxied to a Modal sandbox via the sandbox manager. Per-invocation secrets passed in the call, never persisted in the sandbox.

Sandbox manager:
- Looks up the live `SandboxInstance` row for `(application, revision)`. JIT-provisions on first request.
- Updates `last_used_at` on each call.
- Periodic reaper job (cooperative Postgres advisory lock) destroys sandboxes idle > TTL.

Reaper:
- Runs in the worker process. Two passes per tick:
  1. **Sessions** — cyclotron's janitor handles the actual reset; we additionally write `AgentSession.state = 'failed'` for any session whose cyclotron job ended up dead-lettered (poison pill).
  2. **Sandboxes** — described above.

### API ↔ worker handoff

Cyclotron-v2 itself is the queue. No additional Redis stream / `LISTEN/NOTIFY` needed — that resolves agent-stack open Q3. Pub-sub for SSE streaming is a separate Redis channel; the queue is durable, the bus is ephemeral.

---

## Part C — Security & infra

Mostly unchanged from agent-stack §E. posthog-specific additions:

- **DB**: cyclotron-v2 jobs go in the existing `cyclotron_node` Postgres (already provisioned for CDP). Mirror `AgentSession` lives in the main posthog Postgres — same tenancy guarantees as every other team-scoped table.
- **S3 bucket**: new bucket `posthog-agent-bundles-{env}`, KMS-encrypted, lifecycle expires non-`ready` bundles after 7 days. Use [`posthog/storage/object_storage.py:33`](../../posthog/storage/object_storage.py) helpers.
- **Secrets**: `EncryptedJSONStringField` (same key schedule as `Integration`). Decrypt only in the worker process via the internal API.
- **Per-team quotas**: enforce on Django writes (apps, secrets, revisions/day) and at the API process (concurrent sessions per app, /run rate limit). Surface limits in the management UI.
- **Observability**: structured logs with `app_id` / `revision_id` / `session_id` / `cyclotron_job_id`; OTel traces per session and per tool call; Prometheus metrics; Sentry tagged `agent-runtime-api` and `agent-runtime-worker` separately.
- **Feature flag**: `FEATURE_FLAGS.AGENTS` gates the product (frontend + API + runtime ingress). Per-team rollout.

---

## Open questions (posthog-specific)

Resolutions to the agent-stack open questions, plus a few new ones:

1. **Slug uniqueness** — global. Subdomain-driven; per-team would need a tenant prefix in the URL we don't want.
2. **API ↔ worker transport** — cyclotron-v2. Closed.
3. **Built-ins registry visibility** — share the registry between worker and validator from day one. Avoids the "deploy succeeds, runtime fails" failure mode.
4. **Where does the worker process run?** — Same k8s cluster as CDP cyclotron consumers (`PLUGIN_SERVER_MODE=agent-runtime-worker`). Separate HPA from CDP.
5. **Do we share the `cyclotron_node` Postgres with CDP, or a new instance?** — Share v1 with a distinct `queue_name` prefix (`agent-session`). Carve out a separate DB if hot-spot or noisy-neighbour shows up.
6. **Cyclotron job state size cap** — Claude Agent SDK conversation state can grow large. Need a soft cap (e.g. 1 MiB) and a fallback that offloads the conversation log to S3, keeping only a pointer in the job state. Validate the cap with a real workload before promising one.
7. **Internal-API auth between runtime and Django** — mTLS via existing service mesh, or a shared signing key checked in middleware? Match whatever CDP currently uses for its Django callbacks.
8. **Activity log for sessions** — log session start/complete/fail, or only management-plane changes (apps, revisions, secrets)? Recommend management-plane only; sessions are too high-volume for the activity log, surface them in the dedicated sessions UI instead.

---

## Milestones (posthog-side)

Each shippable behind `FEATURE_FLAGS.AGENTS`. Maps onto the agent-stack milestones but scoped to what we own.

1. **Scaffold + models.** `products/agents/` skeleton (mirror `products/deployments/`), Django app, models, migrations. New scope entries. No business logic, no UI scenes beyond a stub. *(unblocks parallel work)*
2. **Management API.** CRUD viewsets for apps/revisions/secrets/preview-bindings. Manual `ready` transitions for testing. Activity logging wired.
3. **Deploy flow.** `start_deploy` → presigned PUT → `complete_upload` → Celery validator → `ready`. Validators are the trickiest pure-functions in the project; lots of unit tests.
4. **Internal API.** `resolve` + `decrypt` endpoints with internal scopes. mTLS / signed-key auth.
5. **Runtime API skeleton.** New `nodejs/src/agents/api/` process. Domain resolution, `/run` writes session row + enqueues cyclotron job, `/listen` SSE wired to Redis pub-sub. Worker stubbed (returns canned response).
6. **Runtime worker — meta + built-in tools.** Cyclotron consumer in `nodejs/src/agents/worker/`. Real Claude Agent SDK invocation. State serialized into cyclotron `state` BYTEA, reschedule loop on tool boundaries. Built-ins registry shared with validator.
7. **Sandboxes.** Modal integration, custom-tool execution, sandbox lifecycle + reaper. `SandboxInstance` writes from the worker.
8. **Triggers.** Webhooks, cron, slack event ingestion (likely lean on existing posthog scheduling infra for cron).
9. **Frontend.** App list, app detail (revisions/secrets/sessions/sandbox tabs), session detail.
10. **Preview deploys, observability polish, quotas.**
11. **Skills + registry v2** (publish flow, third-party tool publishing). Reuses the same models — `Revision`-style immutable artifacts for published tools.

---

## Cross-references

- agent-stack plan: [`agent-stack/docs/agent-platform.md`](https://github.com/PostHog/agent-stack/blob/main/docs/agent-platform.md)
- Reference scaffold: [`products/deployments/`](../../products/deployments) (#58421)
- cyclotron-v2 core: [`rust/cyclotron-core/src/`](../../rust/cyclotron-core/src/), [`nodejs/src/cdp/services/cyclotron-v2/`](../../nodejs/src/cdp/services/cyclotron-v2/)
- Patterns to mirror: `UUIDModel` ([`posthog/models/utils.py:183`](../../posthog/models/utils.py)), `EncryptedJSONStringField` ([`posthog/helpers/encrypted_fields.py:137`](../../posthog/helpers/encrypted_fields.py)), `TeamAndOrgViewSetMixin` + `scope_object` ([`posthog/api/hog_function.py:469`](../../posthog/api/hog_function.py)), `object_storage` presigned helpers ([`posthog/storage/object_storage.py:33`](../../posthog/storage/object_storage.py)), activity logging ([`posthog/api/hog_function.py:640`](../../posthog/api/hog_function.py))
