# Plan: Agent platform — posthog implementation

## Context

Companion to [`agent-platform/docs/agent-platform.md`](https://github.com/PostHog/agent-platform/blob/main/docs/agent-platform.md). That doc covers the full system; this one is the posthog-side build plan. Where the two conflict, this plan wins for posthog-side concerns.

Two things we own here:

1. **Management plane** — a new flag-gated product under `products/agent_platform/` (Django app + viewsets + frontend).
2. **Runtime** — four TypeScript services under `services/`, deployed as independent node processes. They share **no code** with `nodejs/` (the legacy plugin-server). Anything we want from `nodejs/` we copy and adapt in `services/agent-core/`.
   - `services/agent-core/` — shared library, no process.
   - `services/agent-ingress/` — public-facing `*.agents.posthog.com` terminator.
   - `services/agent-runner/` — session executor (queue consumer + SDK).
   - `services/agent-janitor/` — operational: queue sweeps + internal HTTP surface that Django calls to read/cancel sessions. **The runtime owns session state; Django reads via this surface, never writes to `agent_sessions`.**

The runtime split (ingress + runner) from the agent-platform doc still holds. This plan refines what each half looks like inside the posthog monorepo and which existing primitives we lean on conceptually (not by import).

---

## Status & nodejs TODO

Working tracker for the runtime services only — the Django side is being built in parallel. Update inline as work lands; the rest of this doc is the spec.

**Last audited:** 2026-05-13.

### services/agent-core/ (milestone 5 — substantially done)

- [x] Queue schema + migration ([rust/agent_runtime_queue_migrations/](../../rust/agent_runtime_queue_migrations/), sqlx-managed via the shared rust migrations image): state enum, `lock_id`, `last_heartbeat`, `BYTEA` state, `transition_count`, `janitor_touch_count`, indexes for dequeue/stall/cleanup
- [x] Manager / enqueue with depth limit + 1 MiB state cap ([src/queue/manager.ts](../../services/agent-core/src/queue/manager.ts))
- [x] Worker / dequeue + `FOR UPDATE SKIP LOCKED` + heartbeat + ack/fail/reschedule/cancel ([src/queue/worker.ts](../../services/agent-core/src/queue/worker.ts))
- [x] Janitor / stall recovery + poison-pill + terminal cleanup + Prom metrics ([src/queue/janitor.ts](../../services/agent-core/src/queue/janitor.ts))
- [x] Migrations runner ([rust/bin/migrate-agent-runtime-queue](../../rust/bin/migrate-agent-runtime-queue), wired into the shared rust sqlx-migrate image)
- [x] Pub-sub interface + Redis adapter + in-memory adapter ([src/pubsub/](../../services/agent-core/src/pubsub))
- [x] PostHog DB reader (`agent_platform_agentapplication` / `*revision` rows) + Fernet decryptor for `encrypted_env` — replaces the old HTTP InternalApiClient. ([src/posthog-db/](../../services/agent-core/src/posthog-db/), [src/encryption/](../../services/agent-core/src/encryption/))
- [x] Built-ins registry — `posthog.events.capture`, `posthog.feature_flags.evaluate`, `http.fetch` ([src/builtins/index.ts](../../services/agent-core/src/builtins/index.ts))
- [x] Manifest reader + Zod schema + built-in id validation ([src/manifest/index.ts](../../services/agent-core/src/manifest/index.ts))
- [x] Logger (pino) + Prom metrics ([src/logger.ts](../../services/agent-core/src/logger.ts), [src/metrics.ts](../../services/agent-core/src/metrics.ts))
- [x] `SessionQuery` — read-only `findSession` / `listSessions` + targeted-write `cancelSession`, used by the janitor's HTTP surface ([src/queue/query.ts](../../services/agent-core/src/queue/query.ts))
- [x] Tests: pubsub in-memory, manifest, builtins
- [x] Tests: internal-API client smoke — 200, 404, 5xx, shared-key header, timeout ([src/internal-api/client.test.ts](../../services/agent-core/src/internal-api/client.test.ts))
- [ ] **Rewrite the DB-backed test suite from scratch, run step by step.** The current DB-gated tests in [src/queue/queue.test.ts](../../services/agent-core/src/queue/queue.test.ts) are flaky — `enqueue → dequeue → ack` and `reschedule round-trips state` hang at `consumeOnce()` against a real Postgres, suggesting the polling worker isn't dequeuing what the manager inserted. Plan: write per-method tests that exercise one operation at a time against a fresh DB (createJob → assert row, dequeue → assert lock, ack → assert status), drive the worker synchronously where possible, and don't share pools across tests. SessionQuery and janitor tests are fine; only the worker-polling tests need rebuilding.
- [ ] Tests: Redis pubsub integration (needs Redis in CI)
- [ ] Decide internal-API transport auth (mTLS vs shared key) — both supported in code, pick at infra time

### services/agent-ingress/ (milestone 6 — wired end-to-end against fakes)

- [x] Bootstrap, Zod-validated env, SIGTERM/SIGINT shutdown ([src/index.ts](../../services/agent-ingress/src/index.ts), [src/config.ts](../../services/agent-ingress/src/config.ts))
- [x] Host resolver with LRU + TTL + `invalidate()` hook ([src/resolver.ts](../../services/agent-ingress/src/resolver.ts))
- [x] Auth modes: `public`, `shared_secret`, `webhook_signature` (generic HMAC-SHA256) ([src/auth.ts](../../services/agent-ingress/src/auth.ts))
- [x] `/run` — resolves, authorizes, writes job via agent-core queue, returns 202 `{ sessionId }` ([src/routes/run.ts](../../services/agent-ingress/src/routes/run.ts))
- [x] `/listen/:id` — SSE wired to `bus.subscribeEvents` + 15s heartbeat ([src/routes/listen.ts](../../services/agent-ingress/src/routes/listen.ts))
- [x] `/send/:id` — publishes `user_message` to `bus.publishInput` ([src/routes/send.ts](../../services/agent-ingress/src/routes/send.ts))
- [x] `/webhooks/:provider` — host check, generic signature verify, enqueue ([src/routes/webhooks.ts](../../services/agent-ingress/src/routes/webhooks.ts))
- [x] `/health`, `/status`
- [x] ESLint hard rule blocking Anthropic / Modal / nodejs imports ([.eslintrc.json](../../services/agent-ingress/.eslintrc.json))
- [x] Tests: `/health`, `/status`, `/run`, `/send` happy/sad paths with FakeQueue + InMemoryBus ([src/server.test.ts](../../services/agent-ingress/src/server.test.ts))
- [x] Tests: `/listen` SSE flow — subscribe → publish → frame received ([src/listen.test.ts](../../services/agent-ingress/src/listen.test.ts))
- [x] Tests: resolver LRU + TTL + invalidate ([src/resolver.test.ts](../../services/agent-ingress/src/resolver.test.ts))
- [ ] Tests: webhook signature flow end-to-end
- [ ] Provider-specific webhook strategies (Stripe, Slack-style HMAC-with-timestamp) under the generic webhook_signature mode
- [ ] Per-team concurrent-session quota enforcement on `/run`
- [ ] `/run` rate limiter
- [ ] Promotion invalidation: settle on push-from-Django call to `resolver.invalidate(...)` vs TTL-only

### services/agent-runner/ (milestone 7 — orchestration solid, executor stubbed)

- [x] Worker — dequeue, lock, heartbeat, reschedule on suspend, ack/fail on terminal ([src/worker.ts](../../services/agent-runner/src/worker.ts))
- [x] `SessionExecutor` interface + `ExecutorTurnInput/Output` shape ([src/executor.ts](../../services/agent-runner/src/executor.ts))
- [ ] **Real executor backed by Claude Agent SDK.** Currently `NotImplementedExecutor` ([src/executor-stub.ts](../../services/agent-runner/src/executor-stub.ts)) returns a "not implemented" error. The real one must invoke the SDK, stream chunks, tick heartbeats, and return `tool_call | completed | failed | awaiting_input` per turn.
- [ ] State ↔ Claude Agent SDK `Message[]` / `ContentBlock` mapping. Today [src/state.ts](../../services/agent-runner/src/state.ts) round-trips a generic `{role, content, at}` envelope.
- [x] Meta tools `complete`, `wait_for_input` ([src/tools/meta.ts](../../services/agent-runner/src/tools/meta.ts))
- [x] `http.fetch` builtin — real fetch with timeout ([src/tools/builtins.ts](../../services/agent-runner/src/tools/builtins.ts))
- [ ] `posthog.events.capture` builtin — currently logs to console; wire `posthog-node` + per-app credentials from secrets
- [ ] `posthog.feature_flags.evaluate` builtin — currently hardcoded false; wire to PostHog API
- [x] Tool registry + dispatch ([src/tools/registry.ts](../../services/agent-runner/src/tools/registry.ts))
- [x] Config (Anthropic key, queue DB, internal API, Redis) ([src/config.ts](../../services/agent-runner/src/config.ts))
- [x] Tests: state round-trip, tool dispatch, worker outcomes (`completed` / `failed` / `tool_call` / `awaiting_input` / pendingInputs flush)
- [ ] Tests: real Claude Agent SDK turn (gated on key + recorded fixtures)
- [ ] Secrets loader — [src/index.ts](../../services/agent-runner/src/index.ts) `loadSecrets` returns `{}`; wire to `apiClient.decryptSecrets` once a tool actually needs them
- [ ] Runner-side reaper: queue janitor already resets stalled jobs; need a matching write to set `AgentApplicationSession.state = 'failed'` for the mirror row
- [ ] **Settled with Django owner: runtime owns session state.** No mirror writes from runner. Django reads + cancels through `agent-janitor`'s `/internal/sessions/*` surface (below). `AgentApplicationSession` (the model joshsny added) is treated as a thin request record; its `state` column may be removed once the read path lands.

### services/agent-janitor/ (new in this branch)

Operational process: queue sweeps + internal HTTP surface for Django. The runtime owns session state; Django **reads** sessions through this service and never writes to `agent_sessions`.

- [x] Bootstrap, Zod-validated env, SIGTERM/SIGINT shutdown ([src/index.ts](../../services/agent-janitor/src/index.ts), [src/config.ts](../../services/agent-janitor/src/config.ts))
- [x] Hosts the queue janitor daemon (same `SessionQueueJanitor` from agent-core)
- [x] `/internal/sessions/:id` — fetch single session ([src/routes/sessions.ts](../../services/agent-janitor/src/routes/sessions.ts))
- [x] `/internal/sessions` — list filtered by `application_id`, `revision_id`, `status`, `team_id`, `created_before`, `limit`
- [x] `POST /internal/sessions/:id/cancel` — cancel an `available` or `running` session
- [x] Shared-key auth (`x-internal-key`, `AGENT_INTERNAL_API_SHARED_KEY`) on every `/internal/*` request; refuses traffic when no key is configured ([src/auth.ts](../../services/agent-janitor/src/auth.ts))
- [x] `/health` and `/metrics` are open (no key required)
- [x] Tests: route-level happy/sad paths + auth gating with a `FakeSessionQuery` ([src/server.test.ts](../../services/agent-janitor/src/server.test.ts))
- [ ] Tests: end-to-end against a real Postgres (extend the existing DB-gated suite)
- [ ] Cursor-style pagination on `/internal/sessions` once the UI needs it
- [ ] Mirror cancel to `agent-ingress` / `agent-runner` (broadcast on the bus) so an in-flight turn aborts promptly rather than waiting for the next heartbeat
- [ ] Internal-API transport: mTLS vs `x-internal-key` — settle alongside agent-core's outbound transport decision

### Cross-package / system level

- [ ] End-to-end integration test: ingress `/run` → queue → runner picks up → real Claude Agent SDK turn → tool call → completion → SSE frame delivered via `/listen`
- [ ] Observability
  - [ ] OTel traces per session + per tool invocation
  - [ ] Sentry tagging (`service: agent-ingress`, `service: agent-runner`)
  - [ ] Structured-log fields (`app_id`, `revision_id`, `session_id`, `queue_job_id`) everywhere a request or job is logged
- [ ] `FEATURE_FLAGS.AGENTS` gating — decide whether ingress checks the flag or Django blocks at `resolve`. Pick one and document.
- [ ] k8s deploy manifests + HPA configs (ingress and runner as separate deployments)

### Deferred (later milestones, intentionally not in this list)

- Triggers (M9): cron, slack event ingestion — webhook endpoint exists; orchestrator still TBD
- Sandboxes (M8): Modal integration, custom-tool execution, sandbox lifecycle + reaper
- Bundle validator (M12): the fourth package `services/agent-validator/`
- Skills + registry v2 (M13)

---

## CLI wire-up: stubbed commands against existing endpoints

The Django management API and the existing `/internal/*` session proxy are kept as-is. What remains is wiring the stubbed `ass logs` and `ass secrets` commands in the CLI against endpoints that already exist on the Django side. No new auth, no new services.

**Last audited:** 2026-05-19.

- [ ] `ass-client`: add `sessions.{list, get, cancel, logs}` and `env.{update, patch}` methods on the `AssClient` interface; remove the `sessions.tail` placeholder.
- [ ] `ass logs [--agent <slug>] [--session <id>]`: real implementation — list latest session for the agent, poll `sessions.logs(id)` every 2s, render entries (mirrors the frontend's polling cadence).
- [ ] `ass secrets list / set / rm`: against the existing `env_redacted` field and `PATCH /env` (`{ keys: {NAME: "value" | null } }`). CLI command name stays `secrets`; underlying client method is `env.*` (one-line comment to bridge the naming).
- [ ] Vitest unit tests for the new client methods (mock fetch, assert URL + payload shape).
- [ ] Vitest integration tests for the new CLI commands under `POSTHOG_INTEGRATION=1`.

The architectural pieces previously documented here (extracting management to a new service, OAuth-gating a public janitor surface) were considered and rejected — see [Part E](#part-e--considered-and-rejected-publishing-the-management-api-outside-django).

---

## Runtime services

Three services under `services/`, each its own process / deployment:

```text
services/
  agent-core/        # shared types, db client, queue primitives, manifest reader
  agent-ingress/     # process: HTTP ingress, *.agents.posthog.com terminator
  agent-runner/      # process: session executor (Claude Agent SDK + tools + sandbox)
```

A fourth service will land later for async bundle validation (see §C below). v1 does not ship it.

**Hard rule: no imports from `nodejs/`.** When we need a primitive that exists in `nodejs/` (cyclotron queue ops, structured logger, Prom metrics middleware, Postgres connection pool wrapper, Redis client, etc.) we copy the relevant code into `services/agent-core/` and adapt it. We pay a duplication cost upfront in exchange for:

- Independent dependency graph — no plugin-server transitive cruft.
- Independent deploy cadence and release process.
- Free hand to delete/restructure without coordinating with CDP.
- Clean ownership boundary for codeowners / on-call.

Cherry-pick what we want, leave the rest. The legacy concepts the agent-platform plan calls out (plugin VMs, worker thread topology, event-pipeline-shaped hooks) don't come with us.

### `services/agent-core/`

Shared library, no process of its own. Lives here:

- TypeScript types for the session model, manifest, tool protocol, secrets.
- Postgres client(s) — one for the main posthog DB (read app/revision/encrypted_env rows; write `AgentApplicationSession`/`AgentApplicationSandboxInstance` rows), one for the agent-runtime queue DB (jobs). Each package depends on whichever it needs.
- **Queue primitives** — the cyclotron-v2-shaped session queue (see next section). Single `cyclotron_jobs`-style table with `available | running | completed | failed | canceled`, `FOR UPDATE SKIP LOCKED` dequeue, `lock_id` + `last_heartbeat`, `reschedule({ scheduledAt, state })`, janitor loop. The schema and ops are a clean reimplementation in this package — we own it end-to-end, no shared migrations with `cyclotron_node`.
- PostHog DB reader — pg pool + `ApplicationsRepository` reading `agent_platform_agentapplication` / `*revision` rows directly from the main posthog Postgres. Encryption helper (copied from `nodejs/src/cdp/utils/encryption-utils.ts`) decrypts `encrypted_env` in-process. No HTTP hop to Django.
- Structured logger, Prom registry, OTel setup.
- Manifest reader / built-ins registry (also imported by the future validator package, so the same code rejects unknown ids in both places).

### `services/agent-ingress/`

The public-facing process. Responsibilities:

- All `*.agents.posthog.com` traffic terminates here.
- Domain → `(application, revision)` resolution by direct Postgres query against the main posthog DB (no Django HTTP hop). In-process LRU keyed by revision id, TTL-based invalidation on promotion.
- Per-app auth derived from the resolved revision's config (public / webhook signature / shared secret).
- Implements `/run`, `/listen/:id`, `/send/:id`, `/webhooks/:provider`, `/health`, `/status`. Same contract as the SDK's local dev server.
- `/run` writes an `AgentApplicationSession` row + enqueues a session job in the agent-core queue, returns `{ session_id }` immediately.
- `/listen` subscribes to the Redis pub-sub channel `agent_session:{id}` for SSE streaming.
- `/send` publishes a message into `agent_session:{id}:input` — runner picks it up at the next yield.

**Hard rule (matches agent-platform plan):** ingress imports zero Anthropic / Claude Agent SDK / Modal code, and never decrypts a secret. Enforced by an `eslint-plugin-no-restricted-imports` rule in the package. The blast-radius win is the whole point of splitting from the runner.

### `services/agent-runner/`

The session executor. Responsibilities:

1. Dequeues a session job from the agent-core queue (lock + heartbeat handled by the queue layer).
2. Loads `parsed_manifest` from cached internal-API resolve.
3. Restores Claude Agent SDK state from the job's `state` payload.
4. Runs one "turn" — until the next tool boundary or completion.
5. Two cases:
   - **Completion** → ack the job, write final `output` to `AgentApplicationSession`, publish completion to pub-sub.
   - **Suspension** (long-running tool, sandbox call, waiting on `/send`) → `reschedule({ scheduledAt, state: serialized_sdk_state })`. Heartbeats keep ticking while inside a turn so we don't get reaped mid-execution.
6. Streams events to the pub-sub bus throughout.

Tool execution split:

- **Meta tools** — in-process. Trivial.
- **Referenced (built-in) tools** — in-process. Built-ins registry is a hardcoded map in `agent-core` (e.g. `services/agent-core/src/builtins/index.ts`). The future validator package imports the same map so unknown ids fail before deploy.
- **Local tools** — proxied to a Modal sandbox via the sandbox manager. Per-invocation secrets passed in the call, never persisted in the sandbox.

Sandbox manager:

- Looks up the live `AgentApplicationSandboxInstance` row for `(application, revision)`. JIT-provisions on first request.
- Updates `last_used_at` on each call.
- Periodic reaper job (cooperative Postgres advisory lock) destroys sandboxes idle > TTL.

Reaper:

- Runs in the runner process. Two passes per tick:
  1. **Sessions** — the queue janitor resets stalled jobs; we additionally write `AgentApplicationSession.state = 'failed'` for any session whose job hit the poison-pill threshold.
  2. **Sandboxes** — described above.

---

## Why cyclotron-v2 — as a concept, not a dependency

A Claude Agent SDK run looks structurally identical to the CDP hog-flow execution model: long-running, stateful, crosses many tool / model-call boundaries, each boundary a natural suspend/resume point, no ordering between concurrent runs, needs lock-based concurrency with heartbeats, needs a janitor for stalled or poisoned jobs.

cyclotron-v2 has solved exactly these problems in production for CDP. We **reimplement the concepts** in `agent-core`, copying the relevant code where it's cheaper than rebuilding, with no runtime dependency on `nodejs/src/cdp/services/cyclotron-v2/` or the `cyclotron_node` schema.

| cyclotron-v2 concept                                                | Agent-core mirror                                                                                  | Reference (for copying)                                                                                                                        |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `JobState: available \| running \| completed \| failed \| canceled` | Same enum, drop-in for `AgentApplicationSession.state`.                                            | [`rust/cyclotron-core/src/types.rs:10`](../../rust/cyclotron-core/src/types.rs)                                                                |
| `lock_id` + `last_heartbeat` + `FOR UPDATE SKIP LOCKED` dequeue     | Same pattern. Runner owns a session via lock; heartbeats every N seconds while inside an SDK turn. | [`nodejs/src/cdp/services/cyclotron-v2/worker.ts:88`](../../nodejs/src/cdp/services/cyclotron-v2/worker.ts)                                    |
| `state: BYTEA` payload                                              | Persist Claude Agent SDK conversation/turn state between suspensions.                              | [`rust/cyclotron-node-migrations/20260303000001_initial_schema.sql:9`](../../rust/cyclotron-node-migrations/20260303000001_initial_schema.sql) |
| `reschedule({ scheduledAt, state })`                                | After every tool boundary, runner reschedules with updated state rather than blocking.             | [`nodejs/src/cdp/services/cyclotron-v2/worker.ts:161`](../../nodejs/src/cdp/services/cyclotron-v2/worker.ts)                                   |
| Janitor — stall recovery + poison-pill detection                    | New daemon inside agent-runner.                                                                    | [`nodejs/src/cdp/services/cyclotron-v2/janitor.ts`](../../nodejs/src/cdp/services/cyclotron-v2/janitor.ts)                                     |
| `queue_name`                                                        | Per-app or per-tier queue isolation. v1 = single queue.                                            |                                                                                                                                                |
| `function_id` (UUID) field                                          | Repurpose as `revision_id` for fast lookup of all sessions for a revision (promotion + reaper).    |                                                                                                                                                |

Deliberately **not** carried over in v1:

- `priority` — only useful with multiple queue tiers; v1 has one queue. Easy additive migration when v2 fairness work happens.
- `parent_run_id` — only useful for trigger fanout (one cron firing → N sessions); v1 has no triggers. The mirror `AgentApplicationSession` reserves a nullable column for forward-compat; the queue table will add the column when triggers ship.

What we add on top:

- **Heartbeat-from-inside-the-SDK.** SDK tool callbacks and Anthropic streaming chunks tick the queue heartbeat.
- **Session event bus.** The queue stores final state, not intermediate frames. SSE streaming lives in a Redis pub-sub keyed by `session_id`. Queue row + final-state blob is the durable record; the bus is best-effort.
- **`AgentApplicationSession` mirror in main posthog Postgres.** Queue rows live in the agent-runtime queue DB; the team-scoped mirror row in main posthog Postgres gives us FKs to `Team` / `AgentApplication` / `AgentApplicationRevision`, activity log integration, and clean UI queries.

### Queue database

A separate Postgres DB owned by the agent-runtime — `agent_runtime_queue` (name TBD). Schema lives in `services/agent-core/migrations/`, applied by a small bin script in the same package (mirrors how Rust migrations are managed for `cyclotron_node`, but in TypeScript since we have no Rust here). Not the main posthog Postgres. Not shared with `cyclotron_node`.

---

## Part A — `products/agent_platform/` Django app

> **Direction:** the management API lives here, in Django, and stays here. Auditing, access controls, activity feed, generated TypeScript types, MCP tools, and the approval-workflow infrastructure are all worth too much to give up. The session-proxy viewset stays too — the CLI talks to Django; Django talks to `agent-janitor`. See [Part E](#part-e--considered-and-rejected-publishing-the-management-api-outside-django) for the alternatives we considered and rejected.

Mirror the [`products/deployments/`](../../products/deployments) scaffold from #58421:

```text
products/agent_platform/
  __init__.py
  product.yaml
  manifest.tsx
  package.json
  backend/
    __init__.py
    apps.py
    access.py
    models.py
    api/
    services/
    migrations/
    management/
    test/
  frontend/
  mcp/                  # later
```

Bootstrap with `bin/hogli product:bootstrap agent_platform` per the [Products README](../../products/README.md), then customize. Remove the `products/db_routing.yaml` entry the bootstrap adds — these models live in the main posthog DB so they can FK to `Team` / `User`.

### Models

All inherit `UUIDModel` ([`posthog/models/utils.py:183`](../../posthog/models/utils.py)) — uuid7 PKs. All tenant-data models have `team_id` (FK to `posthog.Team`) per the CLAUDE.md rule. Models live on the main posthog Postgres DB (not an isolated product DB) so they keep real FKs to `Team` / `User`. All child-of-app models are namespaced with the `AgentApplication*` prefix.

**`AgentApplication`** (team-scoped)

- `team: FK(Team)`, `name`, `slug` (unique — partial unique constraint where `deleted=False` so deleted slugs can be reclaimed), `description`
- `encrypted_env: EncryptedTextField(null=True)` — raw `.env` contents uploaded by the developer, single encrypted blob. Null when no env is set (`EncryptedFieldMixin.get_prep_value` writes None for falsy values, so `null=True` is required to avoid a NOT NULL violation on insert). Plaintext never returned by the REST API after creation; the application serializer exposes a derived `env_redacted` field rendering one `KEY=********` line per declared key for UI display. Only the agent-runner decrypts the plaintext in-process via Fernet, audit-logged from the runner. (Replaces a separate `AgentApplicationSecret` per-key model — single blob is enough for v1.)
- Soft delete (`deleted: bool`, `deleted_at`)
- Activity-logged via `log_activity_from_viewset` ([`posthog/api/hog_function.py:640`](../../posthog/api/hog_function.py))

Note: there is **no `live_revision` FK** on the application. "Which revision is live" is a property of the revision itself (`deployment_status`, below). This keeps the FK graph acyclic and avoids a two-row update on promotion.

**`AgentApplicationRevision`** (immutable per deploy)

- `application: FK(AgentApplication)`
- `state: enum(pending_upload | uploaded | validating | ready | failed)` — **full state machine in the schema from day one**, even though v1 skips straight from `uploaded` to `ready` (see §C). Build/validation lifecycle.
- `deployment_status: enum(live | preview | disabled)` — orthogonal to `state`. How this revision serves traffic.
  - Default `disabled`. Logic-layer rule: must be `state=ready` before promotion to `live` or `preview`.
  - At-most-one `live` per application is enforced at the API layer, not the DB (lets promotion fail cleanly rather than via a unique-constraint violation).
  - Promotion is a single-row update: set new revision `live`, demote previous `live` to `disabled`.
- `bundle_s3_key`, `bundle_size`, `bundle_sha256` — S3 location, exact size (enforced by the presigned POST via `content-length-range`), and the CLI-reported SHA-256. The hash is metadata only at upload time; the future async validator re-hashes the uploaded bundle and verifies. Aligns with every other presigned-POST endpoint in the codebase (error_tracking, visual_review, tasks) which similarly trusts the client hash.
- `top_level_config: JSONField` — validated synchronously at deploy start by Django.
- `parsed_manifest: JSONField(null=True)` — populated by the future validator package. v1 leaves this null and runner falls back to reading the bundle's `.ass.yaml` manifest section directly via `top_level_config`.
- `validation_report: JSONField(null=True)` — structured errors when the future validator marks `failed`.
- `created_by: FK(User)`, `created_at`
- Indexes: `(application_id, state, created_at desc)` for "list ready revisions"; `(application_id, deployment_status)` for traffic resolution.

**Preview deploys (no separate model)**

`ass preview` sets `deployment_status = preview` on the revision; the ingress layer routes `<slug>-<revision_short_id>.agents.posthog.com` to that revision. (The original `PreviewBinding` model was dropped — the revision id is the suffix.)

**`AgentApplicationSession`** (mirror of queue job in main DB)

- `team: FK(Team)`, `application: FK(AgentApplication)`, `revision: FK(AgentApplicationRevision)`
- `queue_job_id: UUID(null=True, indexed)` — points at the actual job in the agent-runtime queue DB
- `parent_run_id: UUID(null=True, indexed)` — same id as the queue's `parent_run_id` for trigger fanouts
- `state: enum(available | running | completed | failed | canceled)` — mirrors the queue's `JobState`. Updated by the runner on transition.
- `trigger_type: str`, `trigger_payload: JSONField`
- `input: JSONField`, `output: JSONField(null=True)`, `error: JSONField(null=True)`
- `runtime_instance: str` — identifier of the agent-runner instance currently owning the session
- `started_at`, `last_heartbeat_at`, `completed_at`
- Indexes: `(application, state, created_at desc)` for the sessions UI; `(state, last_heartbeat_at)` for the reaper; `(parent_run_id)` for fanout queries.

**`AgentApplicationSandboxInstance`**

- `team: FK(Team)`, `application: FK(AgentApplication)`, `revision: FK(AgentApplicationRevision)`
- `modal_sandbox_id: str`, `state: enum(provisioning | ready | terminating | terminated)`
- `created_at`, `last_used_at`, `terminated_at`, `error_message`
- v1 = at most one per `(application, revision)`. No unique constraint at the DB level; enforced by runtime so v2 can grow concurrent sandboxes without a migration.
- Indexes: `(application, revision, state)` for lookup; `(state, last_used_at)` for the reaper.

### Migrations

Standard Django migrations under `products/agent_platform/backend/migrations/`. Follow the [`django-migrations`](../../.claude/skills/django-migrations) skill — invoke it before writing the migration files.

### API (DRF + OAuth)

Invoke [`improving-drf-endpoints`](../../.claude/skills/improving-drf-endpoints) before writing viewsets/serializers — it covers `@validated_request`, `@extend_schema`, and the schema/typing pipeline that feeds frontend + MCP.

New scope object: `agent_application`. `encrypted_env` write access is gated by the same scope; there is no separate `agent_secret` scope since secrets aren't a standalone resource. Add to [`posthog/scopes.py:16`](../../posthog/scopes.py).

Viewsets follow `TeamAndOrgViewSetMixin` + `scope_object` ([`posthog/api/hog_function.py:469`](../../posthog/api/hog_function.py)).

Endpoints (project-scoped `/api/projects/{team_id}/...`):

- `agent_applications/` — CRUD + soft delete
  - `POST /:id/start_deploy` → `{ revision_id, upload_url, upload_fields, expires_at, max_size, required_sha256 }` (presigned S3 POST with `content-length-range` bound to the exact size; `required_sha256` is what the CLI claimed and is stored on the revision row for the validator to re-verify later)
  - `POST /:id/complete_upload` → **v1: synchronously transition the revision to `state=ready`** (skipping `validating`). Logged so we know which revisions never went through real validation when the validator lands.
  - `POST /:id/promote` → atomically set the target revision's `deployment_status=live` and demote any prior live revision to `disabled`. Validates the target is `state=ready`.
  - `POST /:id/preview` → set the target revision's `deployment_status=preview`. Validates `state=ready`. Previews coexist — no siblings demoted.
  - `POST /:id/disable_revision` → set the target revision's `deployment_status=disabled`. Allowed from any state. Use to pull a broken live or preview out of traffic.
  - `PUT /:id/env` — replace `encrypted_env`. No plaintext read; the response carries `env_redacted` (one `KEY=********` line per declared key) instead.
- `agent_applications/:slug-or-uuid/revisions/` — nested, list + retrieve (read-only). Filter by `deployment_status`, `state`.
- `agent_applications/:slug-or-uuid/sessions/` — nested, list + retrieve. Filter by `revision`, `state`, `parent_run_id`, `created_after`, `created_before`.

`ass secrets list` is intentionally not exposed as a dedicated endpoint. The set of configured key names is already surfaced via `env_redacted` on the application detail response, so the CLI / UI can render "your env contains these keys" without a separate call. The developer's local `.env` remains the source of truth for values.

Sandboxes have no dedicated viewset. Sandbox usage is inferred per session (the runner annotates session events with the sandbox id when a tool call runs there); a sandbox-level dashboard would be additive later.

**No internal HTTP API for v1.** The runtime packages read from the main posthog Postgres DB directly:

- `agent-ingress` queries `AgentApplication` + `AgentApplicationRevision` for domain resolution.
- `agent-runner` reads `encrypted_env` and decrypts in-process using `ENCRYPTION_SALT_KEYS` passed via deployment env (Fernet is reimplemented in TS — well-defined spec, small surface).
- Per-decrypt audit log is emitted from the runner, not Django.

Keep `ENCRYPTION_SALT_KEYS` out of `agent-ingress` — only the runner needs them. The HTTP boundary is worth revisiting if/when the runtime stops being a first-party service.

### Frontend

Mirror [`products/deployments/manifest.tsx`](../../products/deployments/manifest.tsx). Gated by `FEATURE_FLAGS.AGENTS`, `tags: ['alpha']`.

v1 scenes:

- `AgentApplications` (list)
- `AgentApplication` (detail: revisions, env, sessions, sandbox state tabs)
- `AgentApplicationSession` (single-session inspection)

Use the [`scene-menu-bar`](../../.claude/skills/scene-menu-bar) and [`making-scenes-tab-aware`](../../.claude/skills/making-scenes-tab-aware) conventions for tabs.

Routes:

- `/agents` → list
- `/agents/:slug` → detail (default: revisions)
- `/agents/:slug/sessions/:session_id` → session detail

CLI is the primary deploy surface in v1; this UI is management + observability.

---

## Part B — Deploy flow (v1, no async validator)

1. CLI bundles the project locally.
2. CLI calls Django `start_deploy` with the parsed top-level config. Django validates synchronously (schema-level checks on `.ass.yaml` and triggers) and creates an `AgentApplicationRevision` row in `state=pending_upload`.
3. Django returns a presigned S3 POST URL bound to the exact bundle size. The CLI-reported sha256 is stored on the revision row; not enforced at upload time (matches existing presigned-POST patterns in the codebase).
4. CLI uploads the bundle to S3.
5. CLI calls `complete_upload`.
6. **v1 shortcut**: Django transitions the revision `uploaded → ready` immediately, with no manifest parsing. The bundle is trusted as-is.
7. CLI (or web UI) `promote`s the revision to live.
8. Runtime resolves traffic for the app to the live revision (cache invalidation keyed by revision id).

The full state machine (`pending_upload → uploaded → validating → ready | failed`) is present in the schema and the `complete_upload` endpoint; the `validating → ready` transition is just immediate in v1. When the validator package lands, `complete_upload` stops auto-promoting and instead enqueues a validation job in a separate queue.

---

## Part C — Async bundle validator (deferred, not v1)

When we ship it, the validator will be **a fourth node package**, not a Celery task. Lives at `services/agent-validator/`. Same shape as `agent-runner`:

- Polls its own work queue (`available` revisions whose state is `uploaded` / `validating`).
- Picks one up, marks `validating`, streams the bundle from S3, unpacks with size/file-count caps, walks manifests, resolves referenced ids against the shared built-ins registry in `agent-core`, runs static checks (secrets exist, allow-listed actions exist on referenced tools, triggers valid), transitions to `ready` (+ `parsed_manifest`) or `failed` (+ structured `validation_report`).
- Same heartbeat/lock/janitor pattern from `agent-core`'s queue primitives — the validator is just another consumer of the same primitive, against a different table.
- Built-ins registry shared via `agent-core` means the validator and the runner have identical opinions on which tool ids exist.

v1 ships without it. Models support the state transitions today; the runner reads `top_level_config` directly until `parsed_manifest` is being populated. When the validator lands:

- `complete_upload` stops auto-promoting.
- Existing revisions stay `ready` (they were trusted).
- Validator starts running for new revisions.
- Runner switches to preferring `parsed_manifest` when present.

Pure-function validators (`(bytes) -> (parsed, errors)`) inside the validator package will also be importable by the CLI for `ass build` local checks.

---

## Part D — Security & infra

- **DBs**:
  - Agent-runtime queue gets its own Postgres DB (`agent_runtime_queue`). Not shared with `cyclotron_node`. Owned by `agent-core` migrations.
  - `AgentApplicationSession` and `AgentApplicationSandboxInstance` mirrors live in main posthog Postgres (team-scoped, FKs, activity log eligible).
  - Runner writes to both — queue row is the work item, `AgentApplicationSession` is the user-visible record.
- **S3 bucket**: new `posthog-agent-bundles-{env}`, KMS-encrypted, lifecycle expires non-`ready` bundles after 7 days. Use [`posthog/storage/object_storage.py:33`](../../posthog/storage/object_storage.py) helpers from Django.
- **Secrets**: `AgentApplication.encrypted_env` is an `EncryptedTextField` (same key schedule as `Integration.sensitive_config`). Only `agent-runner` decrypts (in-process Fernet), and only the runner deployment receives `ENCRYPTION_SALT_KEYS`. Audit log emitted from the runner.
- **Per-team quotas**: enforced on Django writes (apps, secrets, revisions/day) and at `agent-ingress` (concurrent sessions per app, `/run` rate limit). Surface limits in the UI.
- **Observability**: structured logs with `app_id` / `revision_id` / `session_id` / `queue_job_id`; OTel traces per session and per tool call; Prometheus metrics; Sentry tagged separately for `agent-ingress` and `agent-runner`.
- **Feature flag**: `FEATURE_FLAGS.AGENTS` gates the product (frontend + API + ingress). Per-team rollout.

---

## Part E — Considered and rejected: publishing the management API outside Django

We seriously considered, and rejected, two architectural moves to extract management-plane functionality out of Django:

1. **A new `services/agent-management` service** that owned the entire agent_application API surface (CRUD, deploys, env, sessions), with the PostHog frontend hitting it via a Django-minted short-lived JWT and the CLI hitting it via OAuth.
2. **A narrower OAuth-gated public surface on `agent-janitor`** that owned only the session/log endpoints, with Django keeping CRUD/deploys/env.

Both are abandoned for now. Recording why so we don't relitigate from scratch:

- **Auditing, access controls, scope enforcement, activity feed, generated TypeScript types, MCP tools, approval workflows.** All wired into PostHog Django for free. Reimplementing them in a Node service is a meaningful undertaking with real service-drift risk.
- **The runtime is already Django-independent.** Already-deployed agents keep serving traffic during a Django outage — the runtime services read Postgres directly. The management plane being down during an outage is annoying (no new deploys, no env changes, no fresh session inspection) but not catastrophic.
- **OAuth tokens are opaque, not JWTs.** Verifying them statelessly in Node would mean either reading `oauth2_provider_accesstoken` from Postgres (schema coupling to django-oauth-toolkit) or HTTP-introspecting against Django (defeating the independence motivation). Neither is free.
- **The narrower janitor variant** would have shipped a second auth surface on a service whose name no longer matched its job, for a single operational scenario (inspect logs during a Django outage) that nobody has hit yet.

**What would change our minds:**

- A real, repeated operational scenario where management-plane outage tolerance matters and Django's uptime can't reach it.
- Customer demand for a third-party-callable management API that Django's auth/scope infrastructure can't comfortably serve.
- A frontend that needs SSE for session log tail (Node handles long-lived connections; WSGI doesn't). At that point, an SSE endpoint on janitor with a Django-minted token is the lowest-effort win and doesn't require giving up Django's CRUD surface.

Until one of those, the CLI talks to Django; Django talks to janitor through the existing `/internal/*` proxy. See the [CLI wire-up tracker](#cli-wire-up-stubbed-commands-against-existing-endpoints) for the small remaining work.

---

## Open questions

Resolutions to the agent-platform open questions + posthog-specific ones:

1. **Slug uniqueness** — global. Subdomain-driven; per-team would need a tenant prefix we don't want.
2. **API ↔ worker transport** — the agent-core queue (cyclotron-v2-shaped, in its own DB). Closed.
3. **Built-ins registry visibility** — shared from `agent-core` so the future validator and the runner agree from day one.
4. **Cluster placement** — `agent-ingress` and `agent-runner` are their own k8s deployments with their own HPAs. Sized independently.
5. **Queue DB sharing** — `agent_runtime_queue` is its own DB. No sharing with `cyclotron_node` or main posthog.
6. **Queue state size cap** — Claude Agent SDK conversation state can grow large. Need a soft cap (e.g. 1 MiB) and a fallback that offloads the conversation log to S3, keeping only a pointer in the job state. Validate against a real workload before promising a number.
7. **Internal-API auth between runtime and Django** — mTLS via existing service mesh, or a shared signing key checked in middleware? Pick at impl time.
8. **Activity log for sessions** — log only management-plane changes (apps, revisions, secrets). Sessions are too high-volume; surface them in the sessions UI instead.
9. **Code duplication strategy** — when copying from `nodejs/`, do we vendor whole files with attribution, or rewrite from scratch with the original as reference? Recommend: rewrite small primitives, vendor + adapt larger ones (the queue ops are the only obvious "vendor" candidate).

---

## Milestones (posthog-side)

Each shippable behind `FEATURE_FLAGS.AGENTS`.

1. **Scaffold + models.** `products/agent_platform/` skeleton, Django app, models with the **full state machine in the schema**, migrations. New scope entries. UI stub. _(unblocks parallel work)_
2. **Management API.** CRUD viewsets for apps and revisions. Env upload endpoint. Activity logging wired. `complete_upload` shortcut transitions straight to `state=ready`. Promote endpoint flips `deployment_status`.
3. **Deploy flow.** `start_deploy` → presigned PUT → `complete_upload` (auto-ready) → `promote`. End-to-end via CLI. No async work.
4. **Runtime DB access.** Wire `agent-ingress` to read `AgentApplication` + `AgentApplicationRevision` directly; wire `agent-runner` to read `encrypted_env` and decrypt in-process via Fernet. Pass `ENCRYPTION_SALT_KEYS` to runner deployment only. Audit log emitted from runner.
5. **`services/agent-core/`.** Types, DB clients, queue primitives (schema + ops), pub-sub helper, internal-API client, logger/metrics. No process; tested in isolation.
6. **`services/agent-ingress/`.** Domain resolution, `/run` writes `AgentApplicationSession` + enqueues job, `/listen` SSE wired to pub-sub, `/send` publishes to pub-sub. Runner stubbed.
7. **`services/agent-runner/` — meta + built-in tools.** Queue consumer. Real Claude Agent SDK invocation. State serialized into queue `state`, reschedule loop on tool boundaries. Built-ins registry shared with `agent-core`.
8. **Sandboxes.** Modal integration, custom-tool execution, sandbox lifecycle + reaper. `AgentApplicationSandboxInstance` writes from the runner.
9. **Triggers.** Webhooks, cron, slack event ingestion.
10. **Frontend.** App list, app detail (revisions/env/sessions/sandbox tabs), session detail.
11. **Preview deploys (set `deployment_status=preview`), observability polish, quotas.**
12. **`services/agent-validator/`.** Async bundle validator. Pure-function checks reusable from the CLI. Flip `complete_upload` to enqueue validation instead of auto-ready.
13. **Skills + registry v2** (publish flow, third-party tool publishing). Reuses the same immutable revision artifacts.

---

## Cross-references

- agent-platform plan: [`agent-platform/docs/agent-platform.md`](https://github.com/PostHog/agent-platform/blob/main/docs/agent-platform.md)
- Reference scaffold: [`products/deployments/`](../../products/deployments) (#58421)
- cyclotron-v2 (reference only, not a dependency): [`rust/cyclotron-core/src/`](../../rust/cyclotron-core/src/), [`nodejs/src/cdp/services/cyclotron-v2/`](../../nodejs/src/cdp/services/cyclotron-v2/)
- Patterns to mirror in Django: `UUIDModel` ([`posthog/models/utils.py:183`](../../posthog/models/utils.py)), `EncryptedTextField` ([`posthog/helpers/encrypted_fields.py:113`](../../posthog/helpers/encrypted_fields.py)), `TeamAndOrgViewSetMixin` + `scope_object` ([`posthog/api/hog_function.py:469`](../../posthog/api/hog_function.py)), `object_storage` presigned helpers ([`posthog/storage/object_storage.py:33`](../../posthog/storage/object_storage.py)), activity logging ([`posthog/api/hog_function.py:640`](../../posthog/api/hog_function.py))
