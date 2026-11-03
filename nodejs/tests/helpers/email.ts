import { createExampleInvocation } from '~/cdp/_tests/fixtures'
import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
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
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { PostgresUse } from '~/common/utils/db/postgres'
import { Hub } from '~/types'

export type EmailInvocation = CyclotronJobInvocationHogFunction & {
    queueParameters: CyclotronInvocationQueueParametersEmailType
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

    integrationId(offset: number): number {
        return this.teamId + offset
    }

    sender(): Partial<IntegrationType> {
        return {
            id: this.integrationId(1),
            ...createEmailSender({ email: 'test@posthog.com', name: 'Test User', domain: 'posthog.com' }),
        }
    }

    params(
        overrides: Partial<CyclotronInvocationQueueParametersEmailType> = {}
    ): CyclotronInvocationQueueParametersEmailType {
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
                integrationIds: from.integrationIds?.map((id) => this.integrationId(id)),
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
    private readonly sesConfig: EmailServiceConfig
    readonly workflowsConfig: TeamWorkflowsConfigService
    readonly suppression: EmailSuppressionService
    readonly recipients: RecipientsManagerService
    readonly activationReporter = { report: jest.fn() }
    private readonly services: EmailService[] = []

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
            emailStatusService: null,
            workflowsActivationReporter: this.activationReporter,
            ...overrides,
            sesConfig: overrides.sesConfig ? { ...this.sesConfig, ...overrides.sesConfig } : this.sesConfig,
        })
        this.services.push(service)
        return service
    }

    /** Builds a service whose SES `send` is spied and accepts every email by default. */
    createWithSendSpy(overrides: EmailServiceOverrides = {}): { service: EmailService; send: jest.SpyInstance } {
        const service = this.create(overrides)
        if (!service.sesV2Client) {
            throw new Error('EmailServiceFixture.createWithSendSpy needs an SES region')
        }
        const send: jest.SpyInstance = jest.spyOn(service.sesV2Client, 'send')
        send.mockResolvedValue({ MessageId: 'test-message-id' })
        return { service, send }
    }

    close(): void {
        for (const service of this.services) {
            service.sesV2Client?.destroy()
        }
    }
}

/** The Valkey that backs the email rate limiters, as `emailValidationValkey` does in production. */
export function createEmailLimiterRedis(hub: Hub): RedisV2 {
    return createRedisV2PoolFromConfig({
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
