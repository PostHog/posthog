/**
 * Typed configuration loader for the ingress.
 *
 * Extends `PlatformConfigSchema` with the trigger / routing knobs. Read once
 * at boot in `index.ts`; everything else inside the service receives the
 * typed `Config` via constructor / function arg.
 */

import { z } from 'zod'

import {
    DEV_ENCRYPTION_KEY,
    DEV_INTERNAL_SIGNING_KEY,
    DEV_POSTHOG_API_BASE_URL,
    DEV_REDIS_URL,
    extendEnvKeyMap,
    isDev,
    loadConfigFromEnv,
    PLATFORM_ENV_KEY_MAP,
    PlatformConfigSchema,
    requiredInProd,
    requiredInProdUnsetInDev,
} from '@posthog/agent-shared'

export const AgentIngressConfigSchema = PlatformConfigSchema.extend({
    port: z.coerce
        .number()
        .int()
        .positive()
        .default(() => (isDev() ? 3030 : 8080))
        .describe('HTTP listen port. Dev defaults to 3030; deployed sets it explicitly.'),
    // /listen SSE subscribes to the bus; HTTPS_PROXY routes outbound (Slack bridge,
    // PostHog introspect) through smokescreen. Both required in prod, enforced here
    // rather than via boot guards in index.ts.
    redisUrl: requiredInProd(DEV_REDIS_URL, 'REDIS_URL', { url: true }).describe(
        'SessionEventBus backing for cross-host /listen SSE. Required in prod; dev defaults to local Redis.'
    ),
    httpsProxy: requiredInProdUnsetInDev('HTTPS_PROXY', { url: true }).describe(
        'Outbound HTTP proxy (smokescreen) for Slack bridge + PostHog introspect. Required in prod; unset in dev (fetches go direct).'
    ),
    // EncryptedFields (Slack bot-token + credential broker) throws on empty keys;
    // the introspector needs the API base. Required in prod, enforced at config-load.
    encryptionSaltKeys: requiredInProd(DEV_ENCRYPTION_KEY, 'ENCRYPTION_SALT_KEYS').describe(
        'Comma-separated UTF-8 Fernet keys (match Django EncryptedTextField). Required in prod; deterministic dev default.'
    ),
    posthogApiBaseUrl: requiredInProd(DEV_POSTHOG_API_BASE_URL, 'POSTHOG_API_BASE_URL', { url: true }).describe(
        'PostHog API the oauth/pat verifiers introspect against. Required in prod; dev defaults to localhost:8010.'
    ),
    routingMode: z
        .enum(['path', 'domain'])
        .default('path')
        .describe(
            '`path` (`/agents/<slug>/...`) for local dev; `domain` (`<slug>.agents.<suffix>`) for prod with wildcard DNS.'
        ),
    domainSuffix: z
        .string()
        .optional()
        .describe('Required in domain mode — e.g. `.agents.posthog.com`. Stripped from Host to extract the slug.'),
    pathPrefix: z
        .string()
        .default('/agents')
        .describe('URL prefix in path mode (default `/agents`). Slug comes immediately after.'),
    internalSigningKey: requiredInProd(DEV_INTERNAL_SIGNING_KEY, 'AGENT_INTERNAL_SIGNING_KEY').describe(
        "HMAC signing key shared with Django and the janitor (must match Django's `AGENT_INTERNAL_SIGNING_KEY`). Backs the x-agent-preview-token gate (aud = agent-ingress.preview) and the posthog_internal auth mode. Required in prod, dev default for local running."
    ),
    publicUrl: z
        .string()
        .optional()
        .describe(
            'Public URL this ingress is reachable at from the outside world (e.g. `https://agents.us.posthog.com`, or a `https://<id>.trycloudflare.com` in local dev via `bin/agent-tunnel`). Optional and debug-only: when set it is logged on boot so you can spot mismatches with what Slack / webhooks are pointed at. Unset is normal — domain-mode routes by host, and Django builds the `slack_events_url` it returns from its own `AGENT_INGRESS_*` settings, not from this value.'
        ),
})

export type AgentIngressConfig = z.infer<typeof AgentIngressConfigSchema>

const ENV_KEY_MAP = extendEnvKeyMap<AgentIngressConfig>(PLATFORM_ENV_KEY_MAP, {
    PORT: 'port',
    ROUTING_MODE: 'routingMode',
    DOMAIN_SUFFIX: 'domainSuffix',
    PATH_PREFIX: 'pathPrefix',
    AGENT_INTERNAL_SIGNING_KEY: 'internalSigningKey',
    AGENT_INGRESS_PUBLIC_URL: 'publicUrl',
})

export function loadAgentIngressConfig(env: NodeJS.ProcessEnv = process.env): AgentIngressConfig {
    return loadConfigFromEnv(AgentIngressConfigSchema, ENV_KEY_MAP, env)
}
