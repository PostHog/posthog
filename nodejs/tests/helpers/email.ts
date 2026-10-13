import { createExampleInvocation } from '~/cdp/_tests/fixtures'
import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { HogFlowAction } from '~/cdp/schema/hogflow'
import { RecipientsManagerService } from '~/cdp/services/managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '~/cdp/services/managers/team-workflows-config.service'
import {
    EmailSuppressionService,
    emailSuppressionConfigFromEnv,
} from '~/cdp/services/messaging/email-suppression.service'
import { EmailService, EmailServiceConfig, EmailServiceDeps } from '~/cdp/services/messaging/email.service'
import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { MessageAssetsService } from '~/cdp/services/messaging/message-assets.service'
import { CyclotronJobInvocationHogFunction, HogFunctionType, IntegrationType } from '~/cdp/types'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PostgresUse } from '~/common/utils/db/postgres'
import { Hub } from '~/types'

import { TestRedisV2 } from './redis-v2'

export type EmailInvocation = CyclotronJobInvocationHogFunction & {
    queueParameters: CyclotronInvocationQueueParametersEmailType
}

export type WorkflowEmailMessage = Omit<CyclotronInvocationQueueParametersEmailType, 'type'>
export type WorkflowEmailAction = Pick<HogFlowAction, 'type' | 'config'> & { type: 'function_email' }

export function createWorkflowEmailAction(templateId: string, message: WorkflowEmailMessage): WorkflowEmailAction {
    return {
        type: 'function_email',
        config: { template_id: templateId, inputs: { email: { value: message } } },
    }
}

export function createEmailVmState(): NonNullable<CyclotronJobInvocationHogFunction['state']['vmState']> {
    return {
        bytecodes: {},
        stack: [],
        upvalues: [],
        callStack: [],
        throwStack: [],
        declaredFunctions: {},
        ops: 0,
        asyncSteps: 0,
        syncDuration: 0,
        maxMemUsed: 0,
    }
}

type EmailSenderConfig = {
    email: string
    name: string
    domain: string
    verified: boolean
    provider: string
}

export function createEmailSender(config: Partial<EmailSenderConfig> = {}): Pick<IntegrationType, 'kind' | 'config'> {
    return {
        kind: 'email',
        config: {
            email: 'sender@example.com',
            name: 'Example Sender',
            domain: 'example.com',
            verified: true,
            provider: 'ses',
            ...config,
        },
    }
}

export class EmailInvocationFixture {
    constructor(private readonly teamId: number) {}

    integrationId = (offset: number): number => this.teamId + offset

    sender(): Partial<IntegrationType> {
        return {
            id: this.integrationId(1),
            ...createEmailSender({ email: 'test@posthog.com', name: 'Test User', domain: 'posthog.com' }),
        }
    }

    params = (
        overrides: Partial<CyclotronInvocationQueueParametersEmailType> = {}
    ): CyclotronInvocationQueueParametersEmailType => {
        const from = overrides.from ?? { integrationId: 1 }
        return {
            type: 'email',
            to: { email: 'test@example.com', name: 'Test User' },
            subject: 'Test Subject',
            text: 'Test Text',
            html: 'Test HTML',
            ...overrides,
            from: {
                ...from,
                integrationId: this.integrationId(from.integrationId),
                integrationIds: from.integrationIds?.map(this.integrationId),
            },
        }
    }

    invocation(hogFunction: Partial<HogFunctionType> = {}, invocationId = 'invocation-1'): EmailInvocation {
        const invocation = createExampleInvocation({ team_id: this.teamId, id: 'function-1', ...hogFunction })
        invocation.id = invocationId
        invocation.state.vmState = createEmailVmState()
        return { ...invocation, queueParameters: this.params() }
    }
}

type EmailServiceOverrides = Partial<Omit<EmailServiceDeps, 'sesConfig'>> & {
    sesConfig?: Partial<EmailServiceConfig>
}

export class EmailServiceFixture {
    readonly sesConfig: EmailServiceConfig
    readonly workflowsConfig: TeamWorkflowsConfigService
    readonly suppression: EmailSuppressionService
    readonly recipients: RecipientsManagerService
    private readonly services: EmailService[] = []
    private readonly redisPools: TestRedisV2[] = []

    constructor(private readonly hub: Hub) {
        this.sesConfig = {
            sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
            sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
            sesRegion: hub.SES_REGION,
            sesEndpoint: hub.SES_ENDPOINT,
            sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
            sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
        }
        this.workflowsConfig = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
        this.suppression = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
        this.recipients = new RecipientsManagerService(hub.postgres)
    }

    create(overrides: EmailServiceOverrides = {}): EmailService {
        const service = new EmailService({
            integrationManager: this.hub.integrationManager,
            teamWorkflowsConfigService: this.workflowsConfig,
            encryptionSaltKeys: this.hub.ENCRYPTION_SALT_KEYS,
            siteUrl: this.hub.SITE_URL,
            trackingCodeSigner: new EmailTrackingCodeSigner(
                this.hub.ENCRYPTION_SALT_KEYS,
                this.hub.CDP_EMAIL_TRACKING_URL
            ),
            emailSuppressionService: this.suppression,
            recipientsManager: this.recipients,
            ...overrides,
            sesConfig: overrides.sesConfig ? { ...this.sesConfig, ...overrides.sesConfig } : this.sesConfig,
        })
        this.services.push(service)
        return service
    }

    createRateLimiterRedis(): TestRedisV2 {
        const redis = new TestRedisV2({
            connection: this.hub.CDP_REDIS_HOST
                ? {
                      url: this.hub.CDP_REDIS_HOST,
                      options: { port: this.hub.CDP_REDIS_PORT, password: this.hub.CDP_REDIS_PASSWORD },
                  }
                : { url: this.hub.REDIS_URL },
            poolMinSize: this.hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.hub.REDIS_POOL_MAX_SIZE,
        })
        this.redisPools.push(redis)
        return redis
    }

    async close(): Promise<void> {
        for (const service of this.services) {
            service.sesV2Client?.destroy()
        }
        await Promise.all(this.redisPools.map((redis) => redis.close()))
    }
}

export function createEmailValidationRedis(hub: Hub): TestRedisV2 {
    return new TestRedisV2({
        connection: {
            url: hub.CDP_VALKEY_HOST,
            options: { port: hub.CDP_VALKEY_PORT, password: hub.CDP_VALKEY_PASSWORD },
        },
        poolMinSize: 0,
        poolMaxSize: 1,
    })
}

export function createMessageAssetsService(): MessageAssetsService {
    return new MessageAssetsService(
        new IngestionOutputs({
            message_assets: {
                produce: jest.fn().mockResolvedValue(undefined),
                queueMessages: jest.fn().mockResolvedValue(undefined),
                checkHealth: jest.fn().mockResolvedValue(undefined),
                checkTopicExists: jest.fn().mockResolvedValue(undefined),
            },
        })
    )
}

export async function insertEmailWorkflowsConfig(hub: Hub, teamId: number): Promise<void> {
    await hub.postgres.query(
        PostgresUse.COMMON_WRITE,
        `INSERT INTO workflows_teamworkflowsconfig
         (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
          email_sending_suspension_reason, ses_tenant_sending_status, email_sending_tier)
         VALUES ($1, true, 'off', '', '', 0)`,
        [teamId],
        'test-create-workflows-config'
    )
}
