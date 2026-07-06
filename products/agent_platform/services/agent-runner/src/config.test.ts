import { AgentRunnerConfigSchema, DEV_GATEWAY_PHS, defaultApiKeyFromConfig, loadAgentRunnerConfig } from './config'

// Minimal prod env satisfying every `requiredInProd` field, so prod tests can
// load the config and assert the remaining (still-optional) fields.
const PROD_REQUIRED = {
    // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
    REDIS_URL: 'redis://prod-redis:6379',
    HTTPS_PROXY: 'http://smokescreen:4750',
    ENCRYPTION_SALT_KEYS: '00beef0000beef0000beef0000beef00',
    POSTHOG_API_BASE_URL: 'https://app.example.com',
    AGENT_MEMORY_S3_ENDPOINT: 'https://s3.example.com',
    AGENT_MEMORY_S3_BUCKET: 'prod-memory',
    AGENT_BUNDLE_S3_BUCKET: 'prod-bundles',
}

describe('loadAgentRunnerConfig', () => {
    afterEach(() => {
        vi.unstubAllEnvs()
    })

    it('returns prod-safe defaults when NODE_ENV=production', () => {
        vi.stubEnv('NODE_ENV', 'production')
        const cfg = loadAgentRunnerConfig(PROD_REQUIRED)
        expect(cfg.maxConcurrency).toBe(8)
        expect(cfg.useAiGateway).toBe(false)
        expect(cfg.aiGatewayUrl).toBe('http://ai-gateway/v1')
        expect(cfg.encryptionSaltKeys).toBe('00beef0000beef0000beef0000beef00')
        expect(cfg.logLevel).toBe('info')
        expect(cfg.bundleS3Bucket).toBe('prod-bundles')
        expect(cfg.memoryS3Bucket).toBe('prod-memory')
        // The dev-only defaults must NOT leak into prod: their only guard is
        // `isDev()`, so without this assert a hardcoded phs_ / analytics key
        // could ship to prod unnoticed. Prod must inject these explicitly.
        expect(cfg.posthogAiGatewayKey).toBeUndefined()
        expect(cfg.posthogAnalyticsApiKey).toBeUndefined()
        expect(cfg.posthogAnalyticsHost).toBeUndefined()
    })

    it('fails closed at config-load in prod when required infra env is unset', () => {
        vi.stubEnv('NODE_ENV', 'production')
        expect(() => loadAgentRunnerConfig({})).toThrow(/REDIS_URL|HTTPS_PROXY|AGENT_(MEMORY|BUNDLE)_S3/)
    })

    it('exposes dev SeaweedFS + gateway defaults when NODE_ENV is not production', () => {
        // vitest runs NODE_ENV=test — same branch as local dev.
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.bundleS3Bucket).toBe('posthog')
        expect(cfg.bundleS3Endpoint).toBe('http://localhost:8333')
        expect(cfg.memoryS3Bucket).toBe('posthog')
        // Local default is the gateway, with the deterministic dev phs_ bearer.
        expect(cfg.useAiGateway).toBe(true)
        expect(cfg.aiGatewayUrl).toBe('http://localhost:8080/v1')
        expect(cfg.posthogAiGatewayKey).toBe(DEV_GATEWAY_PHS)
    })

    it('defaults sandboxBackend to docker in dev so bin/start works without configuration', () => {
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.sandboxBackend).toBe('docker')
    })

    it('leaves sandboxBackend unset in prod so selectSandboxPool fails fast at boot', () => {
        vi.stubEnv('NODE_ENV', 'production')
        const cfg = loadAgentRunnerConfig(PROD_REQUIRED)
        expect(cfg.sandboxBackend).toBeUndefined()
    })

    it('explicit SANDBOX_BACKEND wins over the dev default', () => {
        const cfg = loadAgentRunnerConfig({ SANDBOX_BACKEND: 'modal' })
        expect(cfg.sandboxBackend).toBe('modal')
    })

    it('defaults sandboxHostImage to the locally-built dev tag in dev so bin/start works without configuration', () => {
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.sandboxHostImage).toBe('posthog/agent-sandbox-host:dev')
    })

    it('leaves sandboxHostImage unset in prod so SANDBOX_HOST_IMAGE must be set explicitly', () => {
        vi.stubEnv('NODE_ENV', 'production')
        const cfg = loadAgentRunnerConfig(PROD_REQUIRED)
        expect(cfg.sandboxHostImage).toBeUndefined()
    })

    it('explicit SANDBOX_HOST_IMAGE wins over the dev default', () => {
        const cfg = loadAgentRunnerConfig({ SANDBOX_HOST_IMAGE: 'ghcr.io/posthog/posthog-agent-sandbox-host:master' })
        expect(cfg.sandboxHostImage).toBe('ghcr.io/posthog/posthog-agent-sandbox-host:master')
    })

    it('AGENT_USE_AI_GATEWAY=1 parses to true', () => {
        const cfg = loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: '1' })
        expect(cfg.useAiGateway).toBe(true)
    })

    it('AGENT_USE_AI_GATEWAY=0 parses to false (legacy default)', () => {
        const cfg = loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: '0' })
        expect(cfg.useAiGateway).toBe(false)
    })

    it("'true' and 'false' string forms work too", () => {
        expect(loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: 'true' }).useAiGateway).toBe(true)
        expect(loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: 'false' }).useAiGateway).toBe(false)
    })

    it("rejects garbage AGENT_USE_AI_GATEWAY (won't silently default to false)", () => {
        // Previously `'lol' === '1'` was false so this silently became false.
        // Schema now rejects so we don't pretend.
        expect(() => loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: 'lol' })).toThrow()
    })

    it('throws on bad numeric AGENT_MAX_CONCURRENCY', () => {
        expect(() => loadAgentRunnerConfig({ AGENT_MAX_CONCURRENCY: 'lots' })).toThrow()
    })

    it('rejects an unknown id in AGENT_WEB_SEARCH_FALLBACKS at config load (matches primary strictness)', () => {
        expect(() => loadAgentRunnerConfig({ AGENT_WEB_SEARCH_FALLBACKS: 'exa,barve' })).toThrow(/webSearchFallbacks/)
    })

    it('accepts a valid AGENT_WEB_SEARCH_FALLBACKS list (case- and whitespace-insensitive)', () => {
        const cfg = loadAgentRunnerConfig({ AGENT_WEB_SEARCH_FALLBACKS: ' EXA , brave ' })
        expect(cfg.webSearchFallbacks).toBe(' EXA , brave ')
    })

    it('every schema key carries a description (for runbook generation)', () => {
        for (const [key, field] of Object.entries(AgentRunnerConfigSchema.shape)) {
            expect((field as { description?: string }).description, `missing .describe() for ${key}`).toBeTruthy()
        }
    })
})

describe('defaultApiKeyFromConfig', () => {
    it('excludes the gateway bearer (phs_) — it is not a direct-path provider key', () => {
        const cfg = loadAgentRunnerConfig({
            POSTHOG_AI_GATEWAY_KEY: 'phs_gateway',
            ANTHROPIC_API_KEY: 'sk-ant',
            OPENAI_API_KEY: 'sk-openai',
            MODEL_API_KEY: 'sk-catchall',
        })
        expect(defaultApiKeyFromConfig(cfg)).toBe('sk-ant')
    })

    it('falls back through Anthropic → OpenAI → catch-all', () => {
        expect(
            defaultApiKeyFromConfig(
                loadAgentRunnerConfig({
                    ANTHROPIC_API_KEY: 'sk-ant',
                    MODEL_API_KEY: 'sk-catchall',
                })
            )
        ).toBe('sk-ant')
        expect(
            defaultApiKeyFromConfig(
                loadAgentRunnerConfig({
                    OPENAI_API_KEY: 'sk-openai',
                    MODEL_API_KEY: 'sk-catchall',
                })
            )
        ).toBe('sk-openai')
        expect(defaultApiKeyFromConfig(loadAgentRunnerConfig({ MODEL_API_KEY: 'sk-catchall' }))).toBe('sk-catchall')
    })

    it('returns undefined when no key is set', () => {
        expect(defaultApiKeyFromConfig(loadAgentRunnerConfig({}))).toBeUndefined()
    })
})
