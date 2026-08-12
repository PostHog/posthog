# Node service foundation follow-up plan

This plan covers the next work after the initial Node.js service foundation. It focuses on requirements found in `services/agent-proxy/` and the runtime boundary demonstrated by `services/oauth-proxy/`.

## Scope

- Extend `@posthog/node-service` for long-running streaming services.
- Adopt the shared runtime, build command, and Docker command in agent proxy.
- Keep OAuth proxy on Cloudflare Workers and Wrangler.
- Preserve existing agent proxy routes, metrics, logs, and deployment behavior during migration.

## Pull request stack

Implement this work as a shallow stack so each layer remains independently reviewable.

### Layer 1: Extend the shared runtime

Add these capabilities to `@posthog/node-service` before changing agent proxy:

1. **Pre-start shutdown hooks**
   - Let callers register resource cleanup before the HTTP listener opens.
   - Run hooks when startup fails after a resource connects.
   - Keep reverse-order cleanup and idempotent shutdown.

2. **Request timeout configuration**
   - Add a typed `requestTimeoutMs` option to `startNodeService`.
   - Keep the Node default for ordinary APIs.
   - Allow `0` for SSE and long-running ingest connections.

3. **Drain propagation delay**
   - Mark readiness unavailable as soon as shutdown begins.
   - Wait for an optional `drainDelayMs` before closing the listener.
   - Count the delay inside the total shutdown grace period.

4. **Request log enrichment**
   - Store one request log accumulator in the Hono context.
   - Let handlers add bounded domain fields to the final HTTP summary.
   - Keep request bodies and arbitrary headers out of logs.
   - Preserve request and trace IDs in the final record.

5. **HTTP duration bucket overrides**
   - Keep the current buckets as defaults.
   - Allow services to supply longer buckets for streaming requests.
   - Keep metric names and route-template labels standardized.

6. **Optional metrics authorization**
   - Support an optional dedicated bearer token for `/_metrics`.
   - Compare tokens in constant time.
   - Leave metrics open when no token is configured for in-cluster scraping.

Add focused tests for startup failure cleanup, readiness timing, request timeout configuration, enriched request logs, custom buckets, and metrics authorization.

### Layer 2: Adopt the runtime in agent proxy

Migrate `services/agent-proxy/` without changing its external protocol.

1. Replace its Pino wrapper, HTTP metrics middleware, probes, and process signal handlers with `@posthog/node-service`.
2. Register Redis cleanup before starting the HTTP listener.
3. Configure `requestTimeoutMs: 0` for SSE and streaming ingest.
4. Preserve the existing five-minute shutdown budget and pre-close propagation delay.
5. Configure duration buckets that cover requests through 600 seconds.
6. Keep the optional metrics token and existing public route aliases during deployment migration.
7. Keep JWT verification, CORS, Redis streams, stream capacity, callbacks, and domain metrics inside agent proxy.
8. Keep existing metric names during rollout so dashboards and alerts do not break.
9. Replace the custom esbuild and Docker implementations with the shared package commands.

Suggested source layout:

```text
src/
├── index.ts
├── app.ts
├── config.ts
├── features/
│   ├── stream-read/
│   │   ├── routes.ts
│   │   ├── sse-handler.ts
│   │   └── stream-capacity.ts
│   └── stream-ingest/
│       ├── routes.ts
│       └── ingest-handler.ts
└── infrastructure/
    ├── django-callback/
    ├── jwt/
    └── redis/
```

Do not combine the runtime adoption and the full source move if that makes the review difficult. Runtime adoption is the higher-value change.

### Layer 3: Strengthen agent proxy tests

Add the infrastructure coverage missing from the current mocked suites:

1. Add a real-Redis integration test under `tests/integration/`.
2. Write an event through the NDJSON endpoint and read it through SSE.
3. Verify reconnect behavior with `Last-Event-ID`.
4. Verify readiness closes before an open stream drains on `SIGTERM`.
5. Launch the built `dist/server.mjs` artifact in the end-to-end suite.
6. Emit JUnit reports and enforce category timing budgets.
7. Move pure unit tests beside their source files when those files change.

## OAuth proxy boundary

Do not migrate `services/oauth-proxy/` to `@posthog/node-service`.

OAuth proxy is a Cloudflare Worker with KV bindings, Worker observability, Wrangler builds, and no process lifecycle. Pino, Prometheus, Docker, Node signals, and `@hono/node-server` do not fit that runtime.

The service can adopt repository-wide organizational conventions separately:

- Keep feature behavior grouped by authorize, callback, registration, and token flows.
- Move pure tests beside source files when changing those features.
- Add a Worker integration suite with Cloudflare's Vitest worker pool or Miniflare.
- Keep OAuth validators, redirect checks, KV key hashing, and protocol error responses service-owned.

Do not create a shared Worker runtime package until a second Cloudflare Worker needs the same runtime behavior.

## Acceptance criteria

- Agent proxy exposes the same public routes and wire protocol.
- Existing agent proxy domain metric names remain available during rollout.
- SSE and ingest requests are not terminated by the Node request timeout.
- Readiness becomes unavailable before listener shutdown.
- Redis closes on startup failure and normal shutdown.
- The built artifact passes a real-Redis end-to-end flow.
- Agent proxy uses the shared build and Docker commands.
- OAuth proxy remains deployable through Wrangler without Node runtime dependencies.
