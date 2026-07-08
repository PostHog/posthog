# agent-shared — Shared building blocks for the v2 agent platform

Library, not a deployable service. Everything the three node services
(ingress, runner, janitor) share lives here: persistence, spec schema,
sandbox interface, bundle store, runtime types.

Read [docs/local-dev.md](../../docs/local-dev.md)
for the wider dev flow.

## What lives here

- [src/spec/](src/spec/) — `AgentSpecSchema` (zod). **The source of
  truth** for the `revision.spec` JSONB shape. The Django side
  validates loosely and passes through; this schema is authoritative.
- [src/persistence/](src/persistence/) — `PgSessionQueue`,
  `PgRevisionStore`, `PgIdentityStore`, `PgIntegrationStore`,
  `PgSandboxInstanceStore`, `PgApprovalStore`, `PgCredentialBroker`.
  All Postgres-backed; there are no in-memory variants. Schema is
  Django-owned ([products/agent_platform/backend/migrations/](../../backend/migrations/)), not here.
- [src/storage/](src/storage/) — `BundleStore` interface +
  `S3BundleStore` impl. Prod runs against real S3, tests against
  SeaweedFS via `buildTestBundleStore`. No fs/in-memory bundle store.
- [src/sandbox/](src/sandbox/) — `SandboxImpl` interface +
  `InProcessSandboxPool` (constructor refuses unless `NODE_ENV=test` —
  vitest sets it automatically). Prod uses Docker (local dev) or
  Modal via `selectSandboxPool()`.
- [src/runtime/](src/runtime/) — `SessionEventBus` interface +
  `RedisSessionEventBus` (the only impl); `LogSink` +
  `KafkaLogSink` (with optional `tap` for test assertions);
  `AnalyticsSink` + `CaptureAnalyticsSink` + `NoopAnalyticsSink`
  (latter is the dev fallback when no PostHog destination is wired);
  `SecretBroker`; `CredentialBroker` interface.
- [src/memory/](src/memory/) — `MemoryStore` interface +
  `S3MemoryStore`. Markdown + YAML frontmatter file format;
  MiniSearch-backed BM25 over file bodies for the
  `@posthog/memory-search` tool. **Tests always run against real
  SeaweedFS/S3, never an in-process fake** — same philosophy as the
  real-PG tests; a fake just hides shape drift.

## Rules of engagement

1. **No HTTP, no process boundaries, no bin entry.** This is a
   library. If you're tempted to add `express` or `startServer`,
   you're in the wrong package.

2. **Interfaces first, then one real impl.** Every cross-process
   boundary (queue, bundle, sandbox, bus, log sink, identity, secret)
   is an interface here, but there is only one concrete impl per
   boundary and it's the one prod runs (`PgX` for persistence,
   `S3X` for storage, `RedisSessionEventBus` for the bus,
   `KafkaLogSink` for logs, …). The test harness wires the same
   classes against real local services (Postgres, Redis, Kafka,
   SeaweedFS) — no fakes, no in-memory shortcuts. The rule is
   "if it's stateful and it diverges silently from prod, delete it"
   — that's exactly what bit us before this refactor.

3. **`AgentSpecSchema` is the contract — change it carefully.**
   Tightening a field can reject revisions Django happily wrote.
   Loosening can let the runner accept specs that downstream code
   can't handle. Mirror janitor `validate-spec.ts` whenever you
   touch this.

4. **Schema is Django-owned.** Tables live in the `agent_platform`
   product DB; models + migrations are under
   `products/agent_platform/backend/`. New tables or columns go in a
   new Django migration there. The node services are pure clients —
   they connect and run raw SQL, never DDL. Production applies
   migrations via the `migrate_product_databases` job. **Never** ship a
   feature that runs `CREATE TABLE IF NOT EXISTS` at runner / janitor /
   ingress boot — schema drift then becomes silent (column adds no-op)
   and the Django migration graph is bypassed.

5. **Cross-process services are constructor-injected, not module
   singletons.** Wire each impl at the entrypoint and pass it through
   `WorkerDeps` → `runSession` → dispatcher into `ToolContext` (see
   `memoryStore` for the worked example). Tests inject the same real
   impls; they don't construct fakes. No `setX()` / `getX()` global.
   The pre-existing `posthog-client.ts` / `memory-broker.ts`
   (deleted) pattern is the antipattern we're moving away from.

6. **Prefer well-tested libraries over hand-rolled rankers /
   parsers.** MiniSearch (`@posthog/agent-shared`'s `search.ts`) is
   the precedent: a ~7KB dep that gives BM25 + field weighting + IDF
   without us having to get it right. The same logic applies to YAML,
   markdown, regex-glob, etc. — if it's load-bearing in prod, swap
   in the off-the-shelf option even when the hand-rolled version "works."

7. **No `process.env` reads outside the typed config loader.** Every
   env var the agent services depend on goes through
   `PlatformConfigSchema` (here) or the service's
   `extend(...)` schema (in each service's `src/config.ts`), with an
   entry in `PLATFORM_ENV_KEY_MAP` / the service's `ENV_KEY_MAP`.
   Service `index.ts` reads `loadConfigFromEnv(...)` once at boot and
   passes the typed object onwards. Don't reach for `process.env.X`
   inline — it bypasses the schema (no default, no validation, no
   prod fail-fast). The platform-shared fields (DB URLs, REDIS_URL,
   ENCRYPTION_SALT_KEYS, HTTPS_PROXY, …) belong here so every service
   gets them for free; service-specific knobs go on the service's own
   schema. Also forbidden in tests: pass an explicit `env` object to
   `loadConfigFromEnv` instead of mutating `process.env`.

8. **Two HTTP clients, deliberately separate.** Every outbound fetch
   goes through one of two classes in
   `agent-shared/src/runtime/http-client.ts`:
   - **`HttpClient`** (proxy-bound) — default. Wraps `undici.fetch`
     with a smokescreen `ProxyAgent` when `config.httpsProxy` is set.
     Wire it everywhere an agent author can influence the target URL:
     native tools, MCP transport, sandbox guest, the Slack identity
     bridge (slack.com). `ToolContext.http` only ever holds this one.
   - **`DirectHttpClient`** (no proxy, ever) — reserved for cluster-
     internal services the platform owns and calls itself (ai-gateway,
     in-cluster PostHog API). Constructed at the service entrypoint
     and passed directly to `HttpGatewayClient` /
     `defaultPosthogIntrospector`. **Never thread this onto
     `ToolContext` / `WorkerDeps` / anywhere agent code can reach it.**
     A NO_PROXY-style allowlist would defeat the divide — an
     `@posthog/http-request` against `posthog-web-django.posthog.svc.
cluster.local` would match the suffix and bypass smokescreen
     entirely. The class identity is the capability.
     Bare global `fetch` is flagged by the lint rule in
     `.oxlintrc.json` across `services/agent-*/src/**/*.ts` (tests +
     `http-client.ts` itself exempt). Wire `HttpClient` once in each
     service `index.ts`, pass it through `WorkerDeps` /
     `BridgeSlackUserDeps` / `HttpGatewayClientOpts`, and surface it
     on `ToolContext.http`.

## Pointers

- **Local dev + MCP local + e2e overview** —
  [docs/local-dev.md](../../docs/local-dev.md).
- **Spec consumers** —
  [services/agent-janitor/src/validate-spec.ts](../agent-janitor/src/validate-spec.ts)
  (freeze-time check), [services/agent-runner/src/loop/](../agent-runner/src/loop/)
  (session-start check).
- **Test conventions** —
  [services/agent-tests/CLAUDE.md](../agent-tests/CLAUDE.md).
