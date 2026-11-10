import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { TeamManager } from '~/common/utils/team-manager'
import { PluginsServerConfig } from '~/types'

import { RecipientsManagerService } from '../../managers/recipients-manager.service'
import { RateLimiterService } from '../../rate-limiter/rate-limiter.service'
import { EmailSuppressionService } from '../email-suppression.service'
import { CAPS_VALKEY_TIMEOUT_MS } from './sandbox-deadlines'
import { SandboxEmailEvents } from './sandbox-email-events'
import { SandboxEmailService, createSandboxEmailService } from './sandbox-email.service'
import { SandboxSesClient, createSandboxSesV2Client } from './sandbox-ses-client'

export type SandboxEmailRuntime = { service: SandboxEmailService; events: SandboxEmailEvents }

type SandboxRuntimeConfig = Pick<
    PluginsServerConfig,
    | 'WORKFLOWS_SANDBOX_SENDER_ENABLED'
    | 'SES_REGION'
    | 'SES_ENDPOINT'
    | 'SES_RATE_LIMITER_VALKEY_HOST'
    | 'SES_SANDBOX_FROM_ADDRESS'
    | 'SES_SANDBOX_CONFIGURATION_SET'
    | 'SES_SANDBOX_TENANT_NAME'
    | 'WORKFLOWS_SANDBOX_DAILY_TEAM_CAP'
    | 'WORKFLOWS_SANDBOX_DAILY_RECIPIENT_CAP'
    | 'WORKFLOWS_SANDBOX_CAPS_VALKEY_HOST'
    | 'WORKFLOWS_SANDBOX_CAPS_VALKEY_PORT'
    | 'WORKFLOWS_SANDBOX_CAPS_VALKEY_PASSWORD'
    | 'WORKFLOWS_SANDBOX_CAPS_VALKEY_TLS'
    | 'EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD'
    | 'EMAIL_SUPPRESSION_GLOBAL_HARD_BOUNCE_ENFORCE'
    | 'REDIS_POOL_MIN_SIZE'
    | 'REDIS_POOL_MAX_SIZE'
>

const REQUIRED_TEXT_SETTINGS = [
    'SES_REGION',
    'SES_RATE_LIMITER_VALKEY_HOST',
    'SES_SANDBOX_FROM_ADDRESS',
    'SES_SANDBOX_CONFIGURATION_SET',
    'SES_SANDBOX_TENANT_NAME',
    'WORKFLOWS_SANDBOX_CAPS_VALKEY_HOST',
] as const

const REQUIRED_CAP_SETTINGS = ['WORKFLOWS_SANDBOX_DAILY_TEAM_CAP', 'WORKFLOWS_SANDBOX_DAILY_RECIPIENT_CAP'] as const

export function missingSandboxSenderSettings(config: SandboxRuntimeConfig): string[] {
    return [
        ...REQUIRED_TEXT_SETTINGS.filter((key) => !config[key]),
        ...REQUIRED_CAP_SETTINGS.filter((key) => !Number.isSafeInteger(config[key]) || config[key] <= 0),
    ]
}

export function createSandboxEmailRuntime(
    config: SandboxRuntimeConfig,
    { postgres, teamManager }: { postgres: PostgresRouter; teamManager: TeamManager }
): SandboxEmailRuntime | null {
    if (!config.WORKFLOWS_SANDBOX_SENDER_ENABLED) {
        return null
    }
    const missing = missingSandboxSenderSettings(config)
    if (missing.length > 0) {
        throw new Error(`Sandbox email sending is on, but these settings are missing or invalid: ${missing.join(', ')}`)
    }
    const capsValkey = createRedisV2PoolFromConfig({
        connection: {
            url: config.WORKFLOWS_SANDBOX_CAPS_VALKEY_HOST,
            options: {
                port: config.WORKFLOWS_SANDBOX_CAPS_VALKEY_PORT,
                password: config.WORKFLOWS_SANDBOX_CAPS_VALKEY_PASSWORD,
                tls: config.WORKFLOWS_SANDBOX_CAPS_VALKEY_TLS ? {} : undefined,
                commandTimeout: CAPS_VALKEY_TIMEOUT_MS,
            },
            name: 'sandbox-email-caps',
            exitOnRepeatedErrors: false,
        },
        poolMinSize: config.REDIS_POOL_MIN_SIZE,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        acquireTimeoutMillis: CAPS_VALKEY_TIMEOUT_MS,
    })
    const service = createSandboxEmailService({
        enabled: true,
        db: postgres,
        recipientChecks: {
            suppression: new EmailSuppressionService(postgres, {
                transientBounceThreshold: config.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD,
                globalHardBounceEnforce: config.EMAIL_SUPPRESSION_GLOBAL_HARD_BOUNCE_ENFORCE,
            }),
            recipients: new RecipientsManagerService(postgres),
        },
        limiter: new RateLimiterService(capsValkey, { name: 'sandbox-email-caps' }),
        caps: {
            team: config.WORKFLOWS_SANDBOX_DAILY_TEAM_CAP,
            recipient: config.WORKFLOWS_SANDBOX_DAILY_RECIPIENT_CAP,
        },
        ses: new SandboxSesClient(
            createSandboxSesV2Client({ region: config.SES_REGION, endpoint: config.SES_ENDPOINT }),
            { configurationSet: config.SES_SANDBOX_CONFIGURATION_SET, tenantName: config.SES_SANDBOX_TENANT_NAME }
        ),
        fromAddress: config.SES_SANDBOX_FROM_ADDRESS,
        tenantName: config.SES_SANDBOX_TENANT_NAME,
    })
    return { service, events: new SandboxEmailEvents(teamManager) }
}
