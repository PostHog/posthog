/**
 * Shared config slice for env vars every agent service reads.
 *
 * The runner / ingress / janitor each `PlatformConfigSchema.extend(...)`
 * inside their own `src/config.ts`, then call `loadServiceConfig()` once
 * at boot. This keeps cross-service defaults (the two PG URLs,
 * `REDIS_URL`, encryption keys, etc.) in one place — if they ever
 * drift, the services see different DBs / bundles, which we've already
 * hit once. Bundle and memory S3 settings are service-specific (only
 * runner + janitor speak to those buckets) and live on each service's
 * own config schema.
 *
 * Service-specific schemas:
 *
 * ```ts
 * // services/agent-ingress/src/config.ts
 * export const AgentIngressConfigSchema = PlatformConfigSchema.extend({
 *     port: z.coerce.number().int().positive().default(8080).describe(...),
 *     // ... ingress-only fields ...
 * })
 * ```
 *
 * The env-key map composes the same way — each service ships its own map
 * via `extendEnvKeyMap(PLATFORM_ENV_KEY_MAP, { ... })`.
 */

import { z } from 'zod'

/**
 * "Is this a dev/test process?" Lets us provide ergonomic dev defaults
 * (encryption keys, local Django URL, …) without forcing every dev to
 * remember to set them, while staying strictly fail-closed in prod.
 *
 * Rule: dev = `NODE_ENV !== 'production'`. Production deployments
 * always have `NODE_ENV=production` set; everything else (local dev,
 * vitest, CI test runners) is dev.
 */
export function isDev(env: NodeJS.ProcessEnv = process.env): boolean {
    return env.NODE_ENV !== 'production'
}

/**
 * Dev-only Fernet key — 32 UTF-8 bytes, matches the convention in
 * `agent-shared/src/persistence/pg-impls.test.ts`. **Never used in
 * production**: the dev default is gated by `isDev()` at schema-default
 * time. A prod deploy with `NODE_ENV=production` and `ENCRYPTION_SALT_KEYS`
 * unset fails closed (empty key → encryption-requiring components
 * refuse to start).
 */
export const DEV_ENCRYPTION_KEY = '00beef0000beef0000beef0000beef00'

export const DEV_POSTHOG_API_BASE_URL = 'http://localhost:8010'

// Dev fallback only — prod entrypoints fail closed without an explicit REDIS_URL.
// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
export const DEV_REDIS_URL = 'redis://localhost:6379'

/**
 * Dev-only shared HMAC key for the internal service JWT. Must match
 * `.env.development`'s `AGENT_INTERNAL_SIGNING_KEY` so Django, ingress, and the
 * janitor all sign/verify with the same key in local dev. **Never used in
 * production** — gated behind `isDev()` by `requiredInProd`.
 */
export const DEV_INTERNAL_SIGNING_KEY = 'dev-internal-signing-key-do-not-use-in-prod'

/**
 * A config string that is genuinely required in prod but has an ergonomic dev
 * default. Resolves to `devDefault` when `isDev()`, and **fails at config-load**
 * (throws via `schema.parse`) when unset in prod. The output type is a plain
 * `string` — no `| undefined` — so downstream code never has to null-check or
 * re-assert the value with a scattered `if (!x) throw` boot guard. Use this
 * instead of `.optional()` for values the service cannot function without.
 */
export function requiredInProd(
    devDefault: string,
    envHint: string,
    opts?: { url?: boolean }
): z.ZodType<string, string | undefined> {
    const base = opts?.url ? z.string().url() : z.string()
    return base.optional().transform((v, ctx): string => {
        if (v) {
            return v
        }
        if (isDev()) {
            return devDefault
        }
        ctx.addIssue({ code: 'custom', message: `${envHint} must be set in production.` })
        return z.NEVER
    })
}

/**
 * Like {@link requiredInProd}, but the value is legitimately absent in dev
 * (e.g. `HTTPS_PROXY` — local fetches go direct). Required in prod (fails at
 * config-load when unset), `undefined` in dev. Use instead of `.optional()` +
 * an `if (!x && !isDev()) throw` boot guard.
 */
export function requiredInProdUnsetInDev(
    envHint: string,
    opts?: { url?: boolean }
): z.ZodType<string | undefined, string | undefined> {
    const base = opts?.url ? z.string().url() : z.string()
    return base.optional().transform((v, ctx): string | undefined => {
        if (v) {
            return v
        }
        if (isDev()) {
            return undefined
        }
        ctx.addIssue({ code: 'custom', message: `${envHint} must be set in production.` })
        return z.NEVER
    })
}

export const PlatformConfigSchema = z.object({
    posthogDbUrl: z
        .string()
        .url()
        .default('postgres://posthog:posthog@localhost:5432/posthog')
        .describe(
            'Main PostHog DB — read for cross-product data only (users, teams, org membership). No agent tables.'
        ),
    agentDbUrl: z
        .string()
        .url()
        .default('postgres://posthog:posthog@localhost:5432/posthog_agent_platform')
        .describe('agent_platform product DB — Django-owned schema, holds every agent_* table (authoring + runtime).'),
    redisUrl: z
        .string()
        .url()
        .optional()
        // Base stays optional: services that use the bus (ingress, runner) tighten this to
        // `requiredInProd(DEV_REDIS_URL, ...)`; the janitor never touches Redis.
        .transform((v): string | undefined => v ?? (isDev() ? DEV_REDIS_URL : undefined))
        .describe(
            'SessionEventBus backing for cross-host /listen SSE — runner publishes lifecycle events here, ingress subscribes. Required in prod (entrypoints fail closed without it); defaults to a local dev Redis URL when NODE_ENV != production. Provisioned by terraform/modules/agent-platform/valkey_serverless and surfaced into the chart via the posthog-app `valkey:` map (REDIS_WRITER_URL → REDIS_URL).'
        ),
    encryptionSaltKeys: z
        .string()
        .default(() => (isDev() ? DEV_ENCRYPTION_KEY : ''))
        .describe(
            'Comma-separated UTF-8 Fernet keys (32 bytes each). Matches Django EncryptedTextField. In dev (NODE_ENV != production) defaults to a deterministic test key so the credential broker + encrypted env work out of the box. In prod, MUST be set explicitly — empty value → encryption-requiring components fail closed.'
        ),
    posthogApiBaseUrl: z
        .string()
        .default(() => (isDev() ? DEV_POSTHOG_API_BASE_URL : ''))
        .describe(
            'Base URL for the PostHog API the oauth/pat verifiers introspect against. Dev defaults to localhost:8010; prod must set explicitly (e.g. https://app.posthog.com).'
        ),
    httpsProxy: z
        .string()
        .url()
        .optional()
        .describe(
            'Outbound HTTP proxy URL — in prod this points at smokescreen (see charts/shared/agent-platform/common.yaml `httpProxy.enabled`). Every agent service wires this into a shared HttpClient so tool fetches, MCP transport, and external service calls dispatch through one dispatcher. Unset in dev — fetches go direct. Service entrypoints fail closed in prod when this is unset. Cluster-internal calls (ai-gateway, in-cluster PostHog API) construct a `DirectHttpClient` instead — explicit class divide, no shared NO_PROXY env, so an agent author can never bypass smokescreen by guessing an internal hostname.'
        ),
    kafkaHosts: z
        .string()
        .default('localhost:9092')
        .describe(
            'Comma-separated Kafka brokers. The runner ships structured per-turn events into the `log_entries` topic via KafkaLogSink. Default is the standard local PostHog kafka.'
        ),
    logLevel: z
        .enum(['debug', 'info', 'warn', 'error', 'fatal'])
        .default('info')
        .describe('pino level. Set debug to trace per-turn / per-request detail.'),
    metricsPort: z.coerce
        .number()
        .int()
        .positive()
        .default(6738)
        .describe(
            'Dedicated Prometheus scrape port. Every service binds a tiny metrics-only HTTP server here (GET /metrics + /_metrics) — separate from the request/health port so /metrics is never served on the public ingress listener. 6738 matches the rest of the PostHog Node fleet (nodejs/) and the posthog-app chart default; vmagent discovers it via the pod scrape annotations.'
        ),
})

export type PlatformConfig = z.infer<typeof PlatformConfigSchema>

/**
 * Maps the platform-shared env var names to schema keys. Service-specific
 * loaders merge this with their own additions via `extendEnvKeyMap`.
 */
export const PLATFORM_ENV_KEY_MAP: Record<string, keyof PlatformConfig> = {
    POSTHOG_DB_URL: 'posthogDbUrl',
    AGENT_DB_URL: 'agentDbUrl',
    REDIS_URL: 'redisUrl',
    ENCRYPTION_SALT_KEYS: 'encryptionSaltKeys',
    POSTHOG_API_BASE_URL: 'posthogApiBaseUrl',
    HTTPS_PROXY: 'httpsProxy',
    KAFKA_HOSTS: 'kafkaHosts',
    LOG_LEVEL: 'logLevel',
    AGENT_METRICS_PORT: 'metricsPort',
}

/**
 * Compose a child env-key map onto the platform one. Type-checked so a
 * typo in the child key produces a compile error rather than silently
 * mapping nothing.
 */
export function extendEnvKeyMap<TChild>(
    base: Record<string, keyof PlatformConfig>,
    child: Record<string, keyof TChild>
): Record<string, keyof PlatformConfig | keyof TChild> {
    return { ...base, ...child }
}

/**
 * Walk an env-key map, copy matched values out of `env`, and parse against
 * the schema. Throws a zod error at boot if anything's malformed — much
 * better than a NaN leaking into a setInterval.
 *
 * Tests pass an explicit env object to avoid process-state leakage between
 * cases.
 */
export function loadConfigFromEnv<TSchema extends z.ZodObject<z.ZodRawShape>>(
    schema: TSchema,
    envKeyMap: Record<string, string>,
    env: NodeJS.ProcessEnv = process.env
): z.infer<TSchema> {
    const raw: Record<string, string | undefined> = {}
    for (const [envName, schemaKey] of Object.entries(envKeyMap)) {
        if (env[envName] !== undefined) {
            raw[schemaKey] = env[envName]
        }
    }
    return schema.parse(raw) as z.infer<TSchema>
}
