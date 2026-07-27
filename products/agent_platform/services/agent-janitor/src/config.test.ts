import { AgentJanitorConfigSchema, loadAgentJanitorConfig } from './config'

// Minimal prod env that satisfies every `requiredInProd` field, so a test can
// omit exactly one and assert it's the thing that trips the loader.
const PROD_REQUIRED = {
    AGENT_INTERNAL_SIGNING_KEY: 'prod-signing-key',
    AGENT_BUNDLE_S3_BUCKET: 'prod-bundles',
    AGENT_MEMORY_S3_BUCKET: 'prod-memory',
    AGENT_MEMORY_S3_ENDPOINT: 'https://s3.example.com',
}

describe('loadAgentJanitorConfig', () => {
    afterEach(() => {
        vi.unstubAllEnvs()
    })

    it('returns defaults for an empty env', () => {
        const cfg = loadAgentJanitorConfig({})
        expect(cfg.port).toBe(3031) // dev default (vitest runs NODE_ENV=test)
        expect(cfg.maxRetries).toBe(3)
        expect(cfg.logLevel).toBe('info')
        // Dev default — gates RPC auth locally without forcing every dev to set it.
        expect(cfg.internalSigningKey).toBe('dev-internal-signing-key-do-not-use-in-prod')
        expect(cfg.posthogDbUrl).toContain('postgres://')
    })

    it('fails closed at config-load in prod when AGENT_INTERNAL_SIGNING_KEY is unset', () => {
        vi.stubEnv('NODE_ENV', 'production')
        const { AGENT_INTERNAL_SIGNING_KEY: _omit, ...rest } = PROD_REQUIRED
        expect(() => loadAgentJanitorConfig(rest)).toThrow(/AGENT_INTERNAL_SIGNING_KEY/)
    })

    it('loads in prod when every required field is set', () => {
        vi.stubEnv('NODE_ENV', 'production')
        const cfg = loadAgentJanitorConfig(PROD_REQUIRED)
        expect(cfg.internalSigningKey).toBe('prod-signing-key')
        expect(cfg.bundleS3Bucket).toBe('prod-bundles')
        expect(cfg.port).toBe(8082) // prod default
    })

    it('coerces numeric env strings without leaking NaN', () => {
        const cfg = loadAgentJanitorConfig({
            PORT: '3031',
            STUCK_RUNNING_MS: '120000',
            MAX_RETRIES: '5',
        })
        expect(cfg.port).toBe(3031)
        expect(cfg.stuckRunningMs).toBe(120_000)
        expect(cfg.maxRetries).toBe(5)
    })

    it('throws a clear error on a bad numeric value rather than producing NaN', () => {
        expect(() => loadAgentJanitorConfig({ PORT: 'lol' })).toThrow()
    })

    it('throws on an unknown logLevel rather than casting silently', () => {
        expect(() => loadAgentJanitorConfig({ LOG_LEVEL: 'TRACE' })).toThrow()
    })

    it('respects ENV_KEY_MAP — unknown env keys are ignored, not surfaced as schema errors', () => {
        // Stray env vars shouldn't fail the loader; only mapped ones are read.
        const cfg = loadAgentJanitorConfig({
            PORT: '3031',
            RANDOM_UNMAPPED_VAR: 'whatever',
        })
        expect(cfg.port).toBe(3031)
    })

    it('every schema key carries a description (for runbook generation)', () => {
        for (const [key, field] of Object.entries(AgentJanitorConfigSchema.shape)) {
            expect((field as { description?: string }).description, `missing .describe() for ${key}`).toBeTruthy()
        }
    })
})
