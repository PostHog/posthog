import { createSandboxEmailRuntime } from './sandbox-email-runtime'

describe('createSandboxEmailRuntime', () => {
    const configured = {
        WORKFLOWS_SANDBOX_SENDER_ENABLED: true,
        SES_REGION: 'us-east-1',
        SES_ENDPOINT: '',
        SES_RATE_LIMITER_VALKEY_HOST: 'ses-valkey',
        SES_RATE_LIMITER_VALKEY_PORT: 6379,
        SES_RATE_LIMITER_VALKEY_PASSWORD: '',
        SES_RATE_LIMITER_VALKEY_TLS: false,
        CDP_SES_RATE_LIMIT_CAPACITY: 10,
        CDP_SES_RATE_LIMIT_REFILL_PER_SECOND: 10,
        CDP_SES_RATE_LIMIT_THROTTLED_POLL_DELAY_MS: 100,
        SES_SANDBOX_FROM_ADDRESS: 'sandbox@send.example.com',
        SES_SANDBOX_CONFIGURATION_SET: 'sandbox-config-set',
        SES_SANDBOX_TENANT_NAME: 'sandbox-tenant',
        WORKFLOWS_SANDBOX_DAILY_TEAM_CAP: 10,
        WORKFLOWS_SANDBOX_DAILY_RECIPIENT_CAP: 5,
        WORKFLOWS_SANDBOX_CAPS_VALKEY_HOST: 'caps-valkey',
        WORKFLOWS_SANDBOX_CAPS_VALKEY_PORT: 6379,
        WORKFLOWS_SANDBOX_CAPS_VALKEY_PASSWORD: '',
        WORKFLOWS_SANDBOX_CAPS_VALKEY_TLS: false,
        EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD: 3,
        EMAIL_SUPPRESSION_GLOBAL_HARD_BOUNCE_ENFORCE: false,
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 3,
    }
    const deps = { postgres: {} as any, teamManager: {} as any, pubSub: {} as any }

    it('builds nothing while sending is off, whatever else is set', () => {
        expect(
            createSandboxEmailRuntime({ ...configured, WORKFLOWS_SANDBOX_SENDER_ENABLED: false, SES_REGION: '' }, deps)
        ).toBeNull()
    })

    it.each<[string, Partial<typeof configured>]>([
        ['SES_SANDBOX_FROM_ADDRESS', { SES_SANDBOX_FROM_ADDRESS: '' }],
        ['SES_SANDBOX_CONFIGURATION_SET', { SES_SANDBOX_CONFIGURATION_SET: '' }],
        ['SES_SANDBOX_TENANT_NAME', { SES_SANDBOX_TENANT_NAME: '' }],
        ['SES_RATE_LIMITER_VALKEY_HOST', { SES_RATE_LIMITER_VALKEY_HOST: '' }],
        ['WORKFLOWS_SANDBOX_CAPS_VALKEY_HOST', { WORKFLOWS_SANDBOX_CAPS_VALKEY_HOST: '' }],
        ['WORKFLOWS_SANDBOX_DAILY_TEAM_CAP', { WORKFLOWS_SANDBOX_DAILY_TEAM_CAP: 0 }],
        ['WORKFLOWS_SANDBOX_DAILY_RECIPIENT_CAP', { WORKFLOWS_SANDBOX_DAILY_RECIPIENT_CAP: 2.5 }],
    ])('refuses to start a sending pod without %s', (setting, override) => {
        expect(() => createSandboxEmailRuntime({ ...configured, ...override }, deps)).toThrow(setting)
    })
})
