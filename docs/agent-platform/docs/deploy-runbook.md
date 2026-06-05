# Agent platform — deploy runbook

The agent-platform services (ingress, runner, janitor) are ESM-only Node
processes. They take their configuration entirely from env vars. This doc
lists what the deploy manifest needs to set for each.

## Two-DB topology

All three services read / write two Postgres databases:

- **`POSTHOG_DB_URL`** — main posthog DB (Django-owned). Tables:
  `agent_application`, `agent_revision`.
- **`AGENT_DB_URL`** — runtime queue DB. Tables: `agent_session`,
  `agent_user`, `agent_sandbox_instance`, `agent_tool_approval_request`.
  Schema is owned by `@posthog/agent-migrations` and applied via
  `bin/migrate --scope=agent_runtime` before service boot.

Both can point at the same Postgres in dev. In prod, give the agent DB its
own physical instance — high write churn on sessions / sandbox instances
shouldn't pressure the product DB.

## Per-service env

### `agent-runner`

| Var                                                               | Required                           | Default                        | Notes                                                                                                                                                                                                                                                                                                                           |
| ----------------------------------------------------------------- | ---------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POSTHOG_DB_URL`                                                  | yes (prod)                         | localhost posthog              | Reads applications + revisions.                                                                                                                                                                                                                                                                                                 |
| `AGENT_DB_URL`                                                    | yes (prod)                         | localhost agent_runtime_queue  | Queue schema lives in @posthog/agent-migrations; runner applies pending migrations on boot (idempotent).                                                                                                                                                                                                                        |
| `AGENT_BUNDLE_S3_BUCKET` / `AGENT_BUNDLE_S3_ENDPOINT`             | yes (boot fails without)           | unset                          | S3-backed bundle store (real S3 in prod, MinIO in dev). Runner uses the IRSA role; no static creds needed in prod. Optional companions: `AGENT_BUNDLE_S3_REGION`, `AGENT_BUNDLE_S3_PREFIX` (default `agent_bundles`), `AGENT_BUNDLE_S3_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY`, `AGENT_BUNDLE_S3_FORCE_PATH_STYLE` (default `1`). |
| `ENCRYPTION_SALT_KEYS`                                            | yes (when agents have env secrets) | unset                          | Comma-separated UTF-8 Fernet keys, matches Django's `EncryptedTextField`. When unset, `resolveSecrets` is a noop.                                                                                                                                                                                                               |
| `REDIS_URL`                                                       | yes (cross-host)                   | unset                          | When set, lifecycle events publish to `RedisSessionEventBus` for cross-host `/listen` SSE.                                                                                                                                                                                                                                      |
| `AGENT_MAX_CONCURRENCY`                                           | no                                 | 8                              | In-flight sessions per worker process.                                                                                                                                                                                                                                                                                          |
| `AGENT_USE_AI_GATEWAY`                                            | no                                 | unset                          | When `1`, routes every model call through `posthogAiGatewayModel()`.                                                                                                                                                                                                                                                            |
| `POSTHOG_AI_GATEWAY_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | per-provider                       | unset                          | First non-empty wins; runner forwards as the default `apiKey`.                                                                                                                                                                                                                                                                  |
| `KAFKA_BROKERS`                                                   | yes (prod)                         | unset                          | Comma-separated brokers. When set + a `KafkaLogSink` is wired in, lifecycle events fan out to ClickHouse via the existing `log_entries` Kafka topic.                                                                                                                                                                            |
| `KAFKA_LOG_ENTRIES_TOPIC`                                         | no                                 | `log_entries`                  | Override if a deployment uses a non-default topic.                                                                                                                                                                                                                                                                              |
| `HTTPS_PROXY`                                                     | yes (prod)                         | unset                          | Smokescreen proxy URL. The shared `HttpClient` (every outbound fetch — tools, MCP transport, ai-gateway, identity bridges) routes through this dispatcher. Boot fails fast when unset under `NODE_ENV=production`. Wired by `httpProxy.enabled: true` in `charts/shared/agent-platform/common.yaml`.                            |
| `SANDBOX_BACKEND`                                                 | yes (prod / local-dev)             | unset                          | `modal` (prod) or `docker` (local-dev with isolation). In-process sandbox is selected by tests directly, never via env.                                                                                                                                                                                                         |
| `SANDBOX_HOST_IMAGE`                                              | yes (prod)                         | unset                          | Canonical `posthog-agent-sandbox-host` image reference, pinned by SHA in prod. Applied to both backends.                                                                                                                                                                                                                        |
| `SANDBOX_DOCKER_IMAGE` / `SANDBOX_MODAL_IMAGE`                    | no                                 | (uses `SANDBOX_HOST_IMAGE`)    | Backend-specific overrides.                                                                                                                                                                                                                                                                                                     |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`                           | yes (when `SANDBOX_BACKEND=modal`) | unset                          | Read by the Modal SDK directly. Provisioned per-region via the IRSA path.                                                                                                                                                                                                                                                       |
| `MODAL_APP_NAME` / `MODAL_REGION`                                 | no                                 | SDK default / derived          | Per-region pin (e.g. `us-east`, `eu-west`).                                                                                                                                                                                                                                                                                     |
| `LOG_LEVEL`                                                       | no                                 | `info` (prod), `warn` (vitest) | pino level. Set `debug` to trace per-turn detail.                                                                                                                                                                                                                                                                               |

### `agent-ingress`

| Var                    | Required                   | Default                       | Notes                                                                                                                                                                                                                          |
| ---------------------- | -------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `POSTHOG_DB_URL`       | yes                        | localhost posthog             | Reads applications + revisions for slug/domain resolution.                                                                                                                                                                     |
| `AGENT_DB_URL`         | yes                        | localhost agent_runtime_queue | Enqueues sessions; writes `agent_user` rows.                                                                                                                                                                                   |
| `PORT`                 | no                         | 8080                          | HTTP listen port.                                                                                                                                                                                                              |
| `TEAM_ID`              | no                         | 1                             | Single-tenant fallback for the in-memory dev path. Prod resolves team_id per request via the auth middleware.                                                                                                                  |
| `ROUTING_MODE`         | no                         | `path`                        | `path` (`/agents/<slug>/...`) or `domain` (`<slug>.agents.example.com`).                                                                                                                                                       |
| `DOMAIN_SUFFIX`        | when `ROUTING_MODE=domain` | unset                         | The shared parent domain.                                                                                                                                                                                                      |
| `PATH_PREFIX`          | no                         | `/agents`                     | URL prefix in `path` mode.                                                                                                                                                                                                     |
| `ENCRYPTION_SALT_KEYS` | yes (prod)                 | unset                         | Must match Django's value. Backs `EncryptedFields` for `PgIntegrationStore` (Slack bot tokens) + `PgCredentialBroker` + Slack signing-secret resolution (see below). Boot fails closed when unset under `NODE_ENV=production`. |
| `REDIS_URL`            | yes (cross-host)           | unset                         | When set, `/listen` SSE subscribes to `RedisSessionEventBus` so events from any runner host reach this ingress's SSE clients.                                                                                                  |
| `HTTPS_PROXY`          | yes (prod)                 | unset                         | Smokescreen proxy URL. Outbound Slack identity bridge + PostHog API introspect route through the shared `HttpClient`. Boot fails fast when unset under `NODE_ENV=production`.                                                  |
| `LOG_LEVEL`            | no                         | `info`                        | pino level.                                                                                                                                                                                                                    |

**Slack signing secret — per-agent, no env var, no spec ref.** Each
trigger type declares the secrets it expects in `TRIGGER_REQUIRED_SECRETS`
(see `services/agent-shared/src/spec/trigger-secrets.ts`). The slack
trigger requires `SLACK_SIGNING_SECRET` in the agent's
`AgentApplication.encrypted_env`. Authors set it via the env editor in
the console; the Django `promote` action refuses to flip a revision live
if the key is missing, so production traffic always finds a value when
the ingress decrypts at request time. BYO Slack apps work day-1 — each
agent points at its own Slack app's secret. To extend this to other
triggers / tools, add an entry to `TRIGGER_REQUIRED_SECRETS` and the
freeze-time gate picks it up automatically.

### `agent-janitor`

| Var                                                   | Required                 | Default                       | Notes                                                                                                                         |
| ----------------------------------------------------- | ------------------------ | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `POSTHOG_DB_URL`                                      | yes                      | localhost posthog             | Reads agent_revision for the authoring `/revisions/*` endpoints.                                                              |
| `AGENT_DB_URL`                                        | yes                      | localhost agent_runtime_queue | Owns sweep + session reads.                                                                                                   |
| `AGENT_BUNDLE_S3_BUCKET` / `AGENT_BUNDLE_S3_ENDPOINT` | yes (boot fails without) | unset                         | S3-backed bundle store. Must point at the **same bucket** the runner reads. Optional companions match the runner table above. |
| `INTERNAL_SECRET`                                     | yes (prod)               | unset                         | Shared secret Django sends as `x-internal-secret`. Required for any endpoint other than `/healthz`.                           |
| `PORT`                                                | no                       | 8082                          | HTTP listen port.                                                                                                             |
| `STUCK_RUNNING_MS`                                    | no                       | 300000 (5min)                 | Sweep re-queues `running` rows older than this.                                                                               |
| `STUCK_WAITING_MS`                                    | no                       | 86400000 (24h)                | Sweep fails `waiting` rows older than this.                                                                                   |
| `MAX_RETRIES`                                         | no                       | 3                             | Poison-pill threshold for re-queues.                                                                                          |
| `SWEEP_INTERVAL_MS`                                   | no                       | 30000                         | How often the in-process sweep timer fires.                                                                                   |
| `LOG_LEVEL`                                           | no                       | `info`                        | pino level.                                                                                                                   |

### Django (posthog backend)

| Var                    | Required                                  | Default                 | Notes                                                                                          |
| ---------------------- | ----------------------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------- |
| `AGENT_JANITOR_URL`    | yes (when `agent_platform` API is in use) | `http://localhost:8082` | Base URL of the janitor service. Bundle / native_tools API proxies through here.               |
| `AGENT_JANITOR_SECRET` | yes (prod)                                | unset                   | Sent as `x-internal-secret` on every janitor call. Must match the janitor's `INTERNAL_SECRET`. |
| `ENCRYPTION_SALT_KEYS` | yes                                       | (existing)              | Same keys the worker uses to decrypt `agent_application.encrypted_env`.                        |

## Smoke tests after deploy

### 1. Each service is up

```bash
curl -s "$INGRESS/healthz"
curl -s "$RUNNER_METRICS/healthz"   # if metrics endpoint is exposed
curl -s "$JANITOR/healthz"
```

### 2. Two-pool DB wire-up

The runner logs `posthogDb` + `agentDb` URLs on startup (only the connection
strings, not credentials). Check the boot log for both. Then create a
draft revision via the Django API and watch the runner pick up a session
that references it — if `POSTHOG_DB_URL` is wrong the runner will log
`session.revision_missing` and mark the session failed.

### 3. Redis SSE fan-out (cross-host)

Run the runner on host A, ingress on host B, both with `REDIS_URL` set to
the same Redis. Fire a chat trigger against host B, immediately open
`/listen` against host B too. The events from host A's runner should
arrive on host B's SSE stream. If they don't, check:

- `REDIS_URL` resolves from both hosts.
- The runner is on the same `channelPrefix` as ingress (default
  `agent_session_v2:<id>` — kept that name for backwards-compat).

### 4. Kafka log sink (when wired)

After running one session end-to-end, query ClickHouse:

```sql
SELECT count() FROM log_entries
WHERE log_source = 'agent_session'
  AND instance_id = '<session_id>'
```

You should see at least `session_started`, `turn_started`, `completed`
rows. If count is 0, check (a) the runner is using `KafkaLogSink` (not
`NoopLogSink`), (b) `KAFKA_BROKERS` is set, (c) the `log_entries` topic
exists, (d) the CH materialized view that reads the topic is up.

### 5. Janitor authoring proxy

```bash
# From a host that can reach the janitor (or via Django):
curl -H "x-internal-secret: $INTERNAL_SECRET" "$JANITOR/native_tools"
```

Returns the list of `@posthog/*` tools. Validates that
`@posthog/agent-tools` is reachable from the janitor process. If empty or
errored, the runner / MCP wiring will break later — fix this first.

## Rollback

Pre-prod cutover, no rollback plan required — agents aren't in user-visible
production yet. After GA: a previous live revision is one `promote` away
(idempotent, takes seconds).
