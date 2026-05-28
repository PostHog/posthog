# Design — typed config loader for agent services

**Status:** draft. **Owner:** ben.

`process.env.*` is read from ~40 different sites across the four
node services (ingress, janitor, runner, shared). That's fine for the
six original env vars, but the surface has grown: Kafka brokers, Redis
URLs, encryption salts, per-provider LLM keys, rate-limit knobs,
sandbox pool selection. The current pattern is leaking.

## 1. Problem

Three concrete pain points:

1. **Defaults are scattered.** `AGENT_BUNDLE_ROOT` defaults to
   `$HOME/.posthog/agent-bundles` in agent-runner's `index.ts` and
   in agent-janitor's `index.ts` — two copies of the same constant.
   When one moves, the other doesn't, and the runner / janitor see
   different bundle roots. We hit this in the build-and-invoke
   debugging session.
2. **No type signal on the boundary.** `process.env.AGENT_MAX_CONCURRENCY`
   returns `string | undefined`; every caller has to `parseInt` and
   handle NaN. Easy to miss the `?? 8` default and get NaN
   propagating into a `Worker({ maxConcurrency: NaN })` constructor
   call.
3. **No central manifest** of what env each service reads. The
   deploy-runbook is hand-maintained;
   [`docs/agent-platform/docs/deploy-runbook.md`](../docs/deploy-runbook.md)
   has drifted from the code (the wrong janitor port, missing
   `AGENT_USE_LLM_GATEWAY`). With one loader the runbook can be
   generated.

## 2. Shape — config schema per service

One schema file per service, in `services/<service>/src/config.ts`:

```typescript
import { z } from 'zod'

export const AgentIngressConfigSchema = z.object({
  port: z.coerce.number().int().positive().default(3030),
  posthogDbUrl: z.string().url().default('postgres://posthog:posthog@localhost:5432/posthog'),
  agentDbUrl: z.string().url().default('postgres://posthog:posthog@localhost:5432/agent_runtime_queue'),
  teamId: z.coerce.number().int().positive().default(1),
  routingMode: z.enum(['path', 'domain']).default('path'),
  domainSuffix: z.string().optional(),
  pathPrefix: z.string().default('/agents'),
  redisUrl: z.string().url().optional(),
  slackSigningSecret: z.string().optional(),
  logLevel: z.enum(['debug', 'info', 'warn', 'error', 'fatal']).default('info'),
})

export type AgentIngressConfig = z.infer<typeof AgentIngressConfigSchema>

/**
 * Maps the env-var name (UPPER_SNAKE) to the schema key (camelCase).
 * Keep this exhaustive — the loader walks it.
 */
const ENV_KEY_MAP: Record<string, keyof AgentIngressConfig> = {
  PORT: 'port',
  POSTHOG_DB_URL: 'posthogDbUrl',
  AGENT_DB_URL: 'agentDbUrl',
  TEAM_ID: 'teamId',
  ROUTING_MODE: 'routingMode',
  DOMAIN_SUFFIX: 'domainSuffix',
  PATH_PREFIX: 'pathPrefix',
  REDIS_URL: 'redisUrl',
  SLACK_SIGNING_SECRET: 'slackSigningSecret',
  LOG_LEVEL: 'logLevel',
}

export function loadAgentIngressConfig(env: NodeJS.ProcessEnv = process.env): AgentIngressConfig {
  const raw: Record<string, string | undefined> = {}
  for (const [envName, schemaKey] of Object.entries(ENV_KEY_MAP)) {
    if (env[envName] !== undefined) {
      raw[schemaKey] = env[envName]
    }
  }
  return AgentIngressConfigSchema.parse(raw)
}
```

The same shape repeats for janitor, runner, and shared-defaults
(things every service uses: `AGENT_BUNDLE_ROOT`, `ENCRYPTION_SALT_KEYS`).

## 3. Shared-defaults module

Some env vars are read by multiple services (bundle root, encryption
keys, redis url). Two options:

- **(A) Inline duplication.** Each service's schema declares its own
  `bundleRoot`. The defaults match by convention; CI lints check the
  defaults are identical across services.
- **(B) Shared schema slice.** A `BundleRootConfigSchema` in
  agent-shared that each service `.merge()`s into its own schema.

Option B is the right answer when the env var is conceptually
"platform shared" (bundle root, encryption keys, Postgres URLs); A
when it's service-specific (port, log level). Plan: ship B for the
small set of cross-service vars, A for everything else.

```typescript
// services/agent-shared/src/config/platform.ts
export const PlatformConfigSchema = z.object({
  bundleRoot: z.string().default(`${process.env.HOME ?? '/tmp'}/.posthog/agent-bundles`),
  posthogDbUrl: z.string().url().default('postgres://...'),
  agentDbUrl: z.string().url().default('postgres://...'),
  encryptionSaltKeys: z.string().default(''),
})
```

Each service's schema merges:

```typescript
export const AgentRunnerConfigSchema = PlatformConfigSchema.extend({
  maxConcurrency: z.coerce.number().int().positive().default(8),
  useLlmGateway: z.coerce.boolean().default(false),
  // ...
})
```

## 4. Where the loader runs

Once per process, at startup, in `index.ts`. Everything else inside
the service receives the typed `Config` object via constructor /
function arg:

```typescript
// services/agent-runner/src/index.ts
async function main(): Promise<void> {
  const config = loadAgentRunnerConfig()
  // ... wire pools + Worker with the typed config object.
}
```

No `process.env.*` access outside `config.ts`. CI lint rule
(`eslint-plugin-no-process-env` with `allow: ['NODE_ENV']`) enforces
this. The harness gets a `buildConfig({ ... })` helper that constructs
a typed `Config` directly without touching env.

## 5. Default-value safety

Two failure modes the loader catches that today's `??` pattern doesn't:

1. **NaN from bad numeric input.** `process.env.AGENT_MAX_CONCURRENCY
= 'asdf'` today yields `parseInt('asdf') = NaN`; zod's
   `z.coerce.number()` throws at parse time with a clear message
   pointing at the env var name.
2. **Unknown enum values.** `ROUTING_MODE=lol` today casts to
   `'lol'` via `as 'path' | 'domain'`; zod rejects at parse with
   "Invalid enum value. Expected 'path' | 'domain', received 'lol'".

Both errors fire at process start, before listening — so misconfigured
services exit immediately with an actionable message rather than
crashing on first request.

## 6. Generated runbook

`hogli` script generates
[`docs/agent-platform/docs/deploy-runbook.md`](../docs/deploy-runbook.md)
from the four config schemas. Each row in the env-var table becomes:

```text
| Var | Required | Default | Notes |
| --- | --- | --- | --- |
| `AGENT_MAX_CONCURRENCY` | no | 8 | In-flight sessions per worker process. |
```

derived from:

- Schema key `maxConcurrency` → env name via `ENV_KEY_MAP`.
- `optional()` ↔ "no", missing default ↔ "yes (prod)".
- `default(...)` ↔ the default column.
- `.describe(...)` (zod 3.18+) ↔ the notes column.

Drift between runbook and code becomes impossible.

## 7. Surfaces that benefit

- **`bin/start-mcp-server` + `bin/mprocs.yaml`**. Today the start
  script hardcodes `PORT=${AGENT_JANITOR_PORT:-3031}`. With the
  loader, the default lives in code; the start script just sets the
  env var name and lets the loader resolve. Single source of truth.
- **The runbook**. Stops being a hand-curated table.
- **Tests.** The harness uses `loadAgentRunnerConfig({...envOverride})`
  to construct a config object directly. No `process.env` mutation,
  no global-state leakage between test cases.
- **`.dev.vars` parity check.** A CI step can parse
  `services/mcp/.dev.vars.example` and confirm every key has a
  corresponding entry in some config schema — surfaces drift.

## 8. Open questions

1. **Django side.** Same pattern applies — Django already has
   `posthog/settings/` modules that read env vars, but several places
   in `products/agent_stack/backend/` do direct `os.environ.get`
   reads (`janitor_client.py`'s `AGENT_JANITOR_URL` and `_SECRET`).
   Plan: those move into a `posthog.settings.agent_stack` module
   that the rest of the product imports. Out of scope for v0; same
   pattern, separate work.
2. **Secret vs config.** Currently `ANTHROPIC_API_KEY` is treated as
   regular env. Production runs use a secret store (k8s
   `valueFrom.secretKeyRef`); the env loader handles this
   transparently as long as the secret is materialized into the
   process env at startup. Document the expected flow.
3. **Hot reload.** None. The loader runs once at boot; env changes
   require a process restart. This matches today's behavior and is
   the right default — config changes shouldn't sneak in mid-flight.
4. **Per-team override.** A future "per-team configuration" surface
   (different LLM gateway endpoints per team) doesn't belong in env
   — it belongs in the Team model. Out of scope.

## 9. Rollout

**v0 — one schema, one service.**

- Pick agent-janitor (smallest surface, ~6 env vars).
- `src/config.ts` + `loadAgentJanitorConfig`.
- `src/index.ts` calls `loadAgentJanitorConfig()` once; everything
  downstream receives the typed `Config`.
- CI lint rule blocks `process.env.*` outside `config.ts` for this
  package only.

**v1 — sweep to all four services.**

- Same shape for ingress, runner, shared-defaults.
- `PlatformConfigSchema` for the cross-service slice.
- Lint rule extended to all four packages.

**v2 — generated runbook.**

- `hogli build:agent-runbook` reads all schemas, writes
  `docs/agent-platform/docs/deploy-runbook.md`.
- CI step runs the generator and fails on diff.

**v3 — Django side.**

- `posthog.settings.agent_stack` module owns the few env reads
  inside `products/agent_stack/backend/`.
- `posthog/settings/` already follows this pattern for other
  products; mirror it.

## 10. Dependencies + what this enables

**Hard depends on:** nothing.

**Composes with:** every other plan — most introduce new env vars
(streaming gateway keys, sandbox region, cron interval). Landing the
loader first means those plans just add a schema field instead of
yet-another-bespoke env read.

**What this unblocks:**

- A clean place to plumb the rate-limiting / cost-budget knobs
  ([`rate-limiting-sessions.md`](rate-limiting-sessions.md)) without
  spreading more `process.env.*` calls.
- The generated runbook — saves time on every future deploy doc
  change.
