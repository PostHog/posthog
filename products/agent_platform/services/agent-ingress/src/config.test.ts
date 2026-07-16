import { AgentIngressConfigSchema, loadAgentIngressConfig } from './config'

// Minimal prod env satisfying every `requiredInProd` field; a test can omit one
// and assert it's what trips the loader.
const PROD_REQUIRED = {
    AGENT_INTERNAL_SIGNING_KEY: 'prod-signing-key',
    // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
    REDIS_URL: 'redis://prod-redis:6379',
    HTTPS_PROXY: 'http://smokescreen:4750',
    ENCRYPTION_SALT_KEYS: '00beef0000beef0000beef0000beef00',
    POSTHOG_API_BASE_URL: 'https://app.example.com',
}

describe('loadAgentIngressConfig', () => {
    afterEach(() => {
        vi.unstubAllEnvs()
    })

    it('returns defaults for an empty env', () => {
        const cfg = loadAgentIngressConfig({})
        expect(cfg.port).toBe(3030) // dev default (vitest runs NODE_ENV=test)
        expect(cfg.routingMode).toBe('path')
        expect(cfg.pathPrefix).toBe('/agents')
        // Dev default — backs the preview-token gate + posthog_internal mode locally.
        expect(cfg.internalSigningKey).toBe('dev-internal-signing-key-do-not-use-in-prod')
        expect(cfg.publicUrl).toBeUndefined()
        expect(cfg.logLevel).toBe('info')
    })

    it('fails closed at config-load in prod when AGENT_INTERNAL_SIGNING_KEY is unset', () => {
        vi.stubEnv('NODE_ENV', 'production')
        const { AGENT_INTERNAL_SIGNING_KEY: _omit, ...rest } = PROD_REQUIRED
        expect(() => loadAgentIngressConfig(rest)).toThrow(/AGENT_INTERNAL_SIGNING_KEY/)
    })

    it('fails closed at config-load in prod when REDIS_URL / HTTPS_PROXY are unset', () => {
        vi.stubEnv('NODE_ENV', 'production')
        expect(() => loadAgentIngressConfig({ AGENT_INTERNAL_SIGNING_KEY: 'k' })).toThrow(/REDIS_URL|HTTPS_PROXY/)
    })

    it('publicUrl comes from AGENT_INGRESS_PUBLIC_URL', () => {
        const cfg = loadAgentIngressConfig({ AGENT_INGRESS_PUBLIC_URL: 'https://x.trycloudflare.com' })
        expect(cfg.publicUrl).toBe('https://x.trycloudflare.com')
    })

    it('coerces numeric env strings', () => {
        const cfg = loadAgentIngressConfig({ PORT: '3030' })
        expect(cfg.port).toBe(3030)
    })

    it('throws on bad numeric values', () => {
        expect(() => loadAgentIngressConfig({ PORT: 'not-a-port' })).toThrow()
    })

    it('throws on unknown routingMode rather than casting silently', () => {
        expect(() => loadAgentIngressConfig({ ROUTING_MODE: 'lol' })).toThrow()
    })

    it('internalSigningKey comes from AGENT_INTERNAL_SIGNING_KEY', () => {
        const cfg = loadAgentIngressConfig({ AGENT_INTERNAL_SIGNING_KEY: 'shared-key' })
        expect(cfg.internalSigningKey).toBe('shared-key')
    })

    it('platform fields (POSTHOG_DB_URL, AGENT_DB_URL, REDIS_URL) come from the shared schema', () => {
        const cfg = loadAgentIngressConfig({
            POSTHOG_DB_URL: 'postgres://x/y',
            AGENT_DB_URL: 'postgres://x/z',
            // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
            REDIS_URL: 'redis://localhost:6379',
        })
        expect(cfg.posthogDbUrl).toBe('postgres://x/y')
        expect(cfg.agentDbUrl).toBe('postgres://x/z')
        // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
        expect(cfg.redisUrl).toBe('redis://localhost:6379')
    })

    it('every schema key carries a description (for runbook generation)', () => {
        for (const [key, field] of Object.entries(AgentIngressConfigSchema.shape)) {
            expect((field as { description?: string }).description, `missing .describe() for ${key}`).toBeTruthy()
        }
    })
})
