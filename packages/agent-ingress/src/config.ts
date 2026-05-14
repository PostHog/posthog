import { z } from 'zod'

const ConfigSchema = z.object({
    port: z.coerce.number().int().min(1).max(65_535).default(3030),
    queueDbUrl: z.string().min(1),
    /** Base URL for the Django internal API (e.g. http://app:8000). */
    internalApiBaseUrl: z.string().min(1),
    /** Shared signing key for internal-api calls. */
    internalApiSharedKey: z.string().optional(),
    /** ioredis URL. When unset, we fall back to the in-memory bus (single-process only). */
    redisUrl: z.string().optional(),
    /** Resolver cache TTL for `(domain → revision)` entries. */
    resolverTtlMs: z.coerce.number().int().min(0).default(5_000),
    /** Suffix for application subdomains, e.g. ".agents.posthog.com". */
    domainSuffix: z.string().default('.agents.posthog.com'),
})

export type IngressConfig = z.infer<typeof ConfigSchema>

export function loadConfig(env: NodeJS.ProcessEnv = process.env): IngressConfig {
    return ConfigSchema.parse({
        port: env.PORT,
        queueDbUrl: env.AGENT_RUNTIME_QUEUE_DATABASE_URL,
        internalApiBaseUrl: env.INTERNAL_API_BASE_URL,
        internalApiSharedKey: env.INTERNAL_API_SHARED_KEY,
        redisUrl: env.REDIS_URL,
        resolverTtlMs: env.RESOLVER_TTL_MS,
        domainSuffix: env.DOMAIN_SUFFIX,
    })
}
