import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import {
    MessageRejected,
    SendEmailCommand,
    SendingPausedException,
    TooManyRequestsException,
} from '@aws-sdk/client-sesv2'
import Redis from 'ioredis'
import { HighLevelProducer } from 'node-rdkafka'
import { defaultTreeAdapter, parse, parseFragment } from 'parse5'

import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import {
    CyclotronInvocationQueueParametersEmailSchema,
    CyclotronInvocationQueueParametersEmailType,
} from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '~/cdp/types'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { defineLuaTokenBucketV2 } from '~/common/redis/redis-token-bucket-v2.lua'
import { defineLuaTokenBucketV3 } from '~/common/redis/redis-token-bucket-v3.lua'
import { RedisClient, RedisClientPipeline, RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import * as posthog from '~/common/utils/posthog'
import { waitForExpect } from '~/tests/helpers/expectations'
import {
    createOrganization,
    createOrganizationMembership,
    createTestTeamFixture,
    createUser,
} from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
import { OrganizationMembersService } from '../managers/organization-members.service'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { selectEmailSenderIntegrationId } from './email-sender-selection'
import { EmailSuppressionService, emailSuppressionConfigFromEnv } from './email-suppression.service'
import { EmailService, parseAddressList, sanitizeEmailSubject, teamEmailCapBuckets } from './email.service'
import { MailDevAPI } from './helpers/maildev'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'
import { MessageAssetsService } from './message-assets.service'
import { SandboxEmailSender } from './sandbox-email-sender'

class ThrottlingException extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ThrottlingException'
    }
}

describe('sanitizeEmailSubject', () => {
    it.each([
        ['passes through normal text', 'Hello World', 'Hello World'],
        ['strips null bytes', 'Hello\x00World', 'HelloWorld'],
        ['replaces newlines with space', 'Hello\r\nWorld', 'Hello World'],
        ['replaces lone CR with space', 'Hello\rWorld', 'Hello World'],
        ['replaces lone LF with space', 'Hello\nWorld', 'Hello World'],
        ['strips control chars (BEL, BS, ESC)', 'He\x07ll\x08o\x1BWorld', 'HelloWorld'],
        ['strips DEL character', 'Hello\x7FWorld', 'HelloWorld'],
        ['preserves horizontal tab', 'Hello\tWorld', 'Hello\tWorld'],
        ['trims leading/trailing whitespace', '  Hello World  ', 'Hello World'],
        [
            'collapses multiple newlines into single space',
            'Hello \\ \ goodbye rn\r\n\r\nn ¯\_(ツ)_/¯',
            'Hello \\  goodbye rn n ¯\_(ツ)_/¯',
        ],
        ['handles mixed control chars and newlines', '\x00Hello\r\n\x07World\x1B', 'Hello World'],
        ['preserves unicode characters', 'Héllo Wörld 🎉', 'Héllo Wörld 🎉'],
        ['preserves email-typical special chars', 'Re: Your order #1234 — 50% off!', 'Re: Your order #1234 — 50% off!'],
    ])('%s', (_name, input, expected) => {
        expect(sanitizeEmailSubject(input)).toEqual(expected)
    })
})

describe('parseAddressList', () => {
    it.each([
        ['clean input', 'a@b.com, c@d.com', ['a@b.com', 'c@d.com']],
        ['extra spaces', '  a@b.com ,  c@d.com  ', ['a@b.com', 'c@d.com']],
        ['trailing comma', 'a@b.com, c@d.com,', ['a@b.com', 'c@d.com']],
    ])('%s', (_name, input, expected) => {
        expect(parseAddressList(input)).toEqual(expected)
    })

    it('should return undefined for empty values', () => {
        expect(parseAddressList(undefined)).toBeUndefined()
        expect(parseAddressList('')).toBeUndefined()
        expect(parseAddressList(',')).toBeUndefined()
    })
})

let integrationIdBase: number

const getIntegrationId = (id: number): number => integrationIdBase + id

const createEmailParams = (
    params: Partial<CyclotronInvocationQueueParametersEmailType> = {}
): CyclotronInvocationQueueParametersEmailType => {
    const from = params.from ?? { integrationId: 1 }
    return {
        type: 'email',
        to: { email: 'test@example.com', name: 'Test User' },
        subject: 'Test Subject',
        text: 'Test Text',
        html: 'Test HTML',
        ...params,
        from: {
            ...from,
            integrationId: getIntegrationId(from.integrationId),
            integrationIds: from.integrationIds?.map(getIntegrationId),
        },
    }
}
describe('EmailService', () => {
    let service: EmailService
    let hub: Hub
    let team: Team
    beforeEach(async () => {
        hub = await createHub({})
        team = (await createTestTeamFixture(hub.postgres)).team
        integrationIdBase = team.id
        service = new EmailService(
            {
                sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                sesRegion: hub.SES_REGION,
                sesEndpoint: hub.SES_ENDPOINT,
                sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
            },
            hub.integrationManager,
            new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
            new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
            new RecipientsManagerService(hub.postgres)
        )
        mockFetch.mockClear()
    })
    afterEach(async () => {
        await closeHub(hub)
    })
    describe('when SES is not configured', () => {
        it('should not crash on construction and should fail explicitly on send', async () => {
            const serviceWithoutSES = new EmailService(
                {
                    sesAccessKeyId: '',
                    sesSecretAccessKey: '',
                    sesRegion: '',
                    sesEndpoint: '',
                    sesTrackedConfigurationSet: 'posthog-messaging',
                    sesUntrackedConfigurationSet: '',
                },
                hub.integrationManager,
                new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
                hub.ENCRYPTION_SALT_KEYS,
                hub.SITE_URL,
                new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                new RecipientsManagerService(hub.postgres)
            )
            expect(serviceWithoutSES.sesV2Client).toBeNull()

            await insertIntegration(hub.postgres, team.id, {
                id: getIntegrationId(1),
                kind: 'email',
                config: {
                    email: 'test@posthog.com',
                    name: 'Test User',
                    domain: 'posthog.com',
                    verified: true,
                    provider: 'ses',
                },
            })
            const invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = { stack: [] } as any
            invocation.queueParameters = createEmailParams({ from: { integrationId: 1 } })

            const result = await serviceWithoutSES.executeSendEmail(invocation)
            expect(result.error).toBe('SES is not configured - set SES_REGION and AWS credentials')
        })
    })

    describe('executeSendEmail', () => {
        let invocation: CyclotronJobInvocationHogFunction
        let sendEmailSpy: jest.SpyInstance
        beforeEach(async () => {
            await insertIntegration(hub.postgres, team.id, {
                id: getIntegrationId(1),
                kind: 'email',
                config: {
                    email: 'test@posthog.com',
                    name: 'Test User',
                    domain: 'posthog.com',
                    verified: true,
                    provider: 'ses',
                },
            })
            invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = {
                stack: [],
            } as any
            invocation.queueParameters = createEmailParams({ from: { integrationId: 1 } })

            // Mock SES v2 send to avoid actual AWS calls
            sendEmailSpy = jest.spyOn(service.sesV2Client!, 'send') as any
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
        })
        describe('sandbox sender', () => {
            let capture: jest.SpyInstance
            let memberId: number
            let memberIds: number[]
            let extraOrganizationIds: string[]
            const memberEmail = (name = 'test'): string => `${name}-${team.id}@example.com`
            const createSandboxParams = (
                params: Partial<CyclotronInvocationQueueParametersEmailType> = {}
            ): CyclotronInvocationQueueParametersEmailType =>
                createEmailParams({ to: { email: memberEmail(), name: 'Example member' }, ...params })
            const createMember = async (email: string, organizationId = team.organization_id): Promise<number> => {
                const id = await createUser(hub.postgres, email)
                memberIds.push(id)
                await createOrganizationMembership(hub.postgres, organizationId, id)
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE posthog_user SET email = $1, is_active = true, is_email_verified = true WHERE id = $2',
                    [email, id],
                    'test:verify-sandbox-member'
                )
                return id
            }
            const createOtherOrganization = async (): Promise<string> => {
                const id = await createOrganization(hub.postgres)
                extraOrganizationIds.push(id)
                return id
            }
            const hasQueriedMembers = (queries: jest.SpyInstance): boolean =>
                queries.mock.calls.some(
                    ([, sql]) => typeof sql === 'string' && sql.includes('posthog_organizationmembership')
                )
            let sandboxRedisClients: Redis.Redis[]
            let dailyCapLimiter: RateLimiterService
            const createSandboxLimiter = async (name: string): Promise<RateLimiterService> => {
                const client = await hub.redisPool.acquire()
                sandboxRedisClients.push(client)
                defineLuaTokenBucketV2(client)
                defineLuaTokenBucketV3(client)
                const redis: RedisV2 = {
                    useClient: async (_options, callback) => callback(client as unknown as RedisClient),
                    usePipeline: async (_options, callback) => {
                        const pipeline = client.pipeline() as RedisClientPipeline
                        callback(pipeline)
                        return pipeline.exec()
                    },
                }
                return new RateLimiterService(redis, { name })
            }
            const createSandboxService = (
                enabled: boolean,
                {
                    tierLimiter = null,
                    messageAssetsService,
                    membersPostgres = hub.postgres,
                    capLimiter = dailyCapLimiter,
                    dailyTeamCap = 100,
                    dailyRecipientCap = 100,
                }: {
                    tierLimiter?: RateLimiterService | null
                    messageAssetsService?: MessageAssetsService
                    membersPostgres?: PostgresRouter
                    capLimiter?: RateLimiterService | null
                    dailyTeamCap?: number
                    dailyRecipientCap?: number
                } = {}
            ): EmailService => {
                const sandboxService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                        teamEmailCapMode: 'enforce',
                        teamEmailTierHourlyCaps: [1],
                        teamEmailTierDailyCaps: [1],
                    },
                    hub.integrationManager,
                    new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    messageAssetsService,
                    null,
                    tierLimiter,
                    new SandboxEmailSender(
                        {
                            enabled,
                            tenantName: 'sandbox-tenant',
                            configurationSetName: 'sandbox-email',
                            fromAddress: 'fixed-sandbox@example.com',
                            dailyTeamCap,
                            dailyRecipientCap,
                        },
                        hub.teamManager,
                        capLimiter
                    ),
                    new OrganizationMembersService(membersPostgres)
                )
                sendEmailSpy = jest.spyOn(sandboxService.sesV2Client!, 'send') as jest.SpyInstance
                sendEmailSpy.mockResolvedValue({ MessageId: 'sandbox-message-id' })
                return sandboxService
            }

            beforeEach(async () => {
                capture = jest.spyOn(posthog, 'captureTeamEvent').mockImplementation(() => {})
                sandboxRedisClients = []
                dailyCapLimiter = await createSandboxLimiter('sandbox-daily-cap-test')
                memberIds = []
                extraOrganizationIds = []
                memberId = await createMember(memberEmail())
                await createMember(memberEmail('cc'))
                await createMember(memberEmail('bcc'))
                await insertIntegration(hub.postgres, team.id, {
                    id: getIntegrationId(4),
                    kind: 'email',
                    config: {
                        provider: 'sandbox',
                        email: 'sandbox@example.com',
                        domain: 'example.com',
                        name: 'Example organization via PostHog',
                        verified: true,
                    },
                })
                invocation.queueParameters = createSandboxParams({
                    from: { integrationId: 4 },
                })
            })

            afterEach(async () => {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'DELETE FROM posthog_messagesuppression WHERE team_id = $1',
                    [team.id],
                    'test:delete-sandbox-suppressions'
                )
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'DELETE FROM posthog_organizationmembership WHERE user_id = ANY($1::integer[])',
                    [memberIds],
                    'test:delete-sandbox-memberships'
                )
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'DELETE FROM posthog_user WHERE id = ANY($1::integer[])',
                    [memberIds],
                    'test:delete-sandbox-members'
                )
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'DELETE FROM posthog_organization WHERE id = ANY($1::uuid[])',
                    [extraOrganizationIds],
                    'test:delete-sandbox-organizations'
                )
                capture.mockRestore()
                for (const client of sandboxRedisClients) {
                    await hub.redisPool.release(client)
                }
            })

            it.each([false, true])('blocks a non-member To address (isTest=%s)', async (isTest) => {
                service = createSandboxService(true)
                invocation.queueParameters = createSandboxParams({
                    from: { integrationId: 4 },
                    to: { email: 'outside@example.com' },
                })

                const result = await service.executeSendEmail(invocation, isTest)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result).toMatchObject({ finished: true, skipped: true, metrics: [] })
                expect(result.error).toBeUndefined()
                expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
                expect(result.logs).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            level: 'info',
                            message:
                                'Skipping send: the sandbox sender only sends to active organization members with verified email addresses. Blocked addresses: outside@example.com. Verify your own domain to send to anyone.',
                        }),
                    ])
                )
                expect(capture).toHaveBeenCalledWith(
                    expect.objectContaining({ id: team.id }),
                    'workflows sandbox email blocked',
                    { reason: 'recipient_not_member', is_test: isTest, blocked_recipient_count: 1 }
                )
            })

            it.each(
                [false, true].flatMap((isTest) => [false, true].map((checkFailed) => [isTest, checkFailed] as const))
            )(
                'packs all blocked addresses and guidance into few long log rows (isTest=%s, checkFailed=%s)',
                async (isTest, checkFailed) => {
                    const outside = Array.from(
                        { length: 200 },
                        (_, index) =>
                            `${'a'.repeat(60)}${index}@${'b'.repeat(48)}.${'c'.repeat(48)}.${'d'.repeat(48)}.example.com`
                    )
                    const membersPostgres = checkFailed ? new PostgresRouter(hub) : hub.postgres
                    if (checkFailed) {
                        await membersPostgres.end()
                    }
                    service = createSandboxService(true, { membersPostgres })
                    invocation.queueParameters = createSandboxParams({
                        from: { integrationId: 4 },
                        cc: outside.slice(0, 100).join(', '),
                        bcc: outside.slice(100).join(', '),
                    })

                    const result = await service.executeSendEmail(invocation, isTest)

                    expect(sendEmailSpy).not.toHaveBeenCalled()
                    expect(result).toMatchObject({ finished: true, skipped: true, metrics: [], messageAssets: [] })
                    expect(result.error).toBeUndefined()
                    expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
                    const messages = result.logs.map(({ message }) => message).join('\n')
                    for (const email of checkFailed ? [memberEmail(), ...outside] : outside) {
                        expect(messages).toContain(email)
                    }
                    expect(
                        result.logs.filter(({ message }) => outside.some((email) => message.includes(email)))
                    ).toHaveLength(5)
                    expect(messages.toLowerCase()).toContain('verify your own domain to send to anyone.')
                    expect(messages).not.toContain('(truncated)')
                    expect(capture).toHaveBeenCalledTimes(1)
                    expect(capture).toHaveBeenCalledWith(
                        expect.objectContaining({ id: team.id }),
                        'workflows sandbox email blocked',
                        {
                            reason: checkFailed ? 'check_failed' : 'recipient_not_member',
                            is_test: isTest,
                            blocked_recipient_count: checkFailed ? 201 : 200,
                        }
                    )
                }
            )

            it.each(
                [false, true].flatMap((isTest) =>
                    [
                        'cc',
                        'bcc',
                        'cc list',
                        'bcc list',
                        'multiple',
                        'unverified',
                        'legacy',
                        'inactive',
                        'other organization',
                    ].map((recipient) => [isTest, recipient] as const)
                )
            )('blocks all delivery for %s / %s', async (isTest, recipient) => {
                let blocked = ['outside@example.com']
                let params = createSandboxParams({ from: { integrationId: 4 } })
                if (recipient === 'cc' || recipient === 'bcc') {
                    params = { ...params, [recipient]: 'Outside member <OUTSIDE@example.com>' }
                    blocked = ['OUTSIDE@example.com']
                } else if (recipient === 'cc list' || recipient === 'bcc list') {
                    const field = recipient === 'cc list' ? 'cc' : 'bcc'
                    params = { ...params, [field]: `"Example, colleague" <${memberEmail(field)}>, outside@example.com` }
                } else if (recipient === 'multiple') {
                    params = { ...params, cc: 'outside@example.com', bcc: 'another@example.com' }
                    blocked = ['outside@example.com', 'another@example.com']
                } else if (recipient === 'other organization') {
                    blocked = [memberEmail('outside')]
                    await createMember(blocked[0], await createOtherOrganization())
                    params = { ...params, to: { email: blocked[0] } }
                } else {
                    blocked = [memberEmail()]
                    await hub.postgres.query(
                        PostgresUse.COMMON_WRITE,
                        'UPDATE posthog_user SET is_active = $1, is_email_verified = $2 WHERE id = $3',
                        [recipient !== 'inactive', recipient === 'legacy' ? null : recipient === 'inactive', memberId],
                        'test:change-sandbox-member-status'
                    )
                }
                service = createSandboxService(true)
                invocation.queueParameters = params

                const result = await service.executeSendEmail(invocation, isTest)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result).toMatchObject({ finished: true, skipped: true, metrics: [], messageAssets: [] })
                expect(result.error).toBeUndefined()
                expect(result.invocation.queueScheduledAt).toBeUndefined()
                expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
                expect(result.logs).toContainEqual(
                    expect.objectContaining({
                        level: 'info',
                        message: `Skipping send: the sandbox sender only sends to active organization members with verified email addresses. Blocked addresses: ${blocked.join(', ')}. Verify your own domain to send to anyone.`,
                    })
                )
                expect(capture).toHaveBeenCalledTimes(1)
                expect(capture).toHaveBeenCalledWith(
                    expect.objectContaining({ id: team.id }),
                    'workflows sandbox email blocked',
                    { reason: 'recipient_not_member', is_test: isTest, blocked_recipient_count: blocked.length }
                )
                expect(result.capturedPostHogEvents).toEqual([])
            })

            it.each(
                [false, true].flatMap((isTest) =>
                    [
                        'Example colleague',
                        '"member@example.com"',
                        '"Example, colleague"',
                        '"Example" Colleague',
                    ].flatMap((name) =>
                        [false, true].map((storedMixedCase) => [isTest, name, storedMixedCase] as const)
                    )
                )
            )(
                'matches bare addresses without case sensitivity (isTest=%s, name=%s, storedMixedCase=%s)',
                async (isTest, name, storedMixedCase) => {
                    if (storedMixedCase) {
                        await hub.postgres.query(
                            PostgresUse.COMMON_WRITE,
                            'UPDATE posthog_user SET email = initcap(email) WHERE id = ANY($1::integer[])',
                            [memberIds],
                            'test:store-mixed-case-sandbox-members'
                        )
                    }
                    service = createSandboxService(true)
                    invocation.queueParameters = createSandboxParams({
                        from: { integrationId: 4 },
                        to: { email: memberEmail().toUpperCase() },
                        cc: `${name} <${memberEmail('cc').toUpperCase()}>`,
                        bcc: ` ${name} <${memberEmail('bcc').toUpperCase()}> `,
                    })

                    const result = await service.executeSendEmail(invocation, isTest)

                    expect(result).toMatchObject({ finished: true })
                    expect(result.skipped).not.toBe(true)
                    expect(result.error).toBeUndefined()
                    expect(result.invocation.state.vmState?.stack).toEqual([{ success: true }])
                    expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                    expect((sendEmailSpy.mock.calls[0][0] as SendEmailCommand).input.Destination).toEqual({
                        ToAddresses: [memberEmail().toUpperCase()],
                        CcAddresses: [memberEmail('cc').toUpperCase()],
                        BccAddresses: [memberEmail('bcc').toUpperCase()],
                    })
                    expect(capture).toHaveBeenCalledWith(
                        expect.objectContaining({ id: team.id }),
                        'workflows sandbox email sent',
                        { recipient_count: 3, source: isTest ? 'test' : 'workflow', is_test: isTest }
                    )
                }
            )

            it.each(
                [false, true].flatMap((isTest) =>
                    ['cc', 'bcc'].flatMap((field) => [false, true].map((list) => [isTest, field, list] as const))
                )
            )('accepts escaped quoted display names (isTest=%s, field=%s, list=%s)', async (isTest, field, list) => {
                service = createSandboxService(true)
                invocation.queueParameters = createSandboxParams({
                    from: { integrationId: 4 },
                    [field]: `"Example \\"colleague, teammate\\"" <${memberEmail(field)}>${list ? `, ${memberEmail(field === 'cc' ? 'bcc' : 'cc')}` : ''}`,
                })
                const result = await service.executeSendEmail(invocation, isTest)
                expect(result.error).toBeUndefined()
                expect(result.skipped).not.toBe(true)
                expect(result.invocation.state.vmState?.stack).toEqual([{ success: true }])
                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                const destination = (sendEmailSpy.mock.calls[0][0] as SendEmailCommand).input.Destination
                expect(field === 'cc' ? destination?.CcAddresses : destination?.BccAddresses).toEqual([
                    memberEmail(field),
                    ...(list ? [memberEmail(field === 'cc' ? 'bcc' : 'cc')] : []),
                ])
                expect(capture).toHaveBeenCalledWith(
                    expect.objectContaining({ id: team.id }),
                    'workflows sandbox email sent',
                    { recipient_count: list ? 3 : 2, source: isTest ? 'test' : 'workflow', is_test: isTest }
                )
            })

            it.each(
                [false, true].flatMap((isTest) =>
                    ['cc', 'bcc'].flatMap((field) =>
                        [false, true].flatMap((suppressed) =>
                            [false, true].map((wrapped) => [isTest, field, suppressed, wrapped] as const)
                        )
                    )
                )
            )(
                'keeps a quoted mailbox intact (isTest=%s, field=%s, suppressed=%s, wrapped=%s)',
                async (isTest, field, suppressed, wrapped) => {
                    const email = `"example,<${team.id}>"@example.com`
                    await createMember(email)
                    if (suppressed) {
                        await new EmailSuppressionService(
                            hub.postgres,
                            emailSuppressionConfigFromEnv()
                        ).recordHardBounces(team.id, [email])
                    }
                    service = createSandboxService(true)
                    invocation.queueParameters = createSandboxParams({
                        from: { integrationId: 4 },
                        [field]: wrapped ? `Example colleague <${email}>` : email,
                    })
                    const result = await service.executeSendEmail(invocation, isTest)
                    expect(result.error).toBeUndefined()
                    expect(result.invocation.state.vmState?.stack).toEqual([{ success: !suppressed }])
                    if (suppressed) {
                        expect(sendEmailSpy).not.toHaveBeenCalled()
                        expect(result.logs).toContainEqual(
                            expect.objectContaining({ message: expect.stringContaining(email) })
                        )
                        expect(capture).not.toHaveBeenCalled()
                    } else {
                        expect(result.skipped).not.toBe(true)
                        expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                        const destination = (sendEmailSpy.mock.calls[0][0] as SendEmailCommand).input.Destination
                        expect(field === 'cc' ? destination?.CcAddresses : destination?.BccAddresses).toEqual([email])
                        expect(capture).toHaveBeenCalledWith(
                            expect.objectContaining({ id: team.id }),
                            'workflows sandbox email sent',
                            { recipient_count: 2, source: isTest ? 'test' : 'workflow', is_test: isTest }
                        )
                    }
                }
            )

            it.each([false, true])('rechecks membership after slow send preparation (isTest=%s)', async (isTest) => {
                const now = Date.now()
                const clock = jest.spyOn(Date, 'now').mockReturnValue(now)
                const queries = jest.spyOn(hub.postgres, 'query')
                try {
                    service = createSandboxService(true)
                    const first = await service.executeSendEmail(invocation, isTest)
                    expect(first.error).toBeUndefined()
                    expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                    await hub.postgres.query(
                        PostgresUse.COMMON_WRITE,
                        'DELETE FROM posthog_organizationmembership WHERE user_id = $1',
                        [memberId],
                        'test:revoke-sandbox-member-before-preparation'
                    )
                    queries.mockClear()
                    clock.mockImplementation(
                        () =>
                            now +
                            (queries.mock.calls.some(
                                ([, sql]) => typeof sql === 'string' && sql.includes('posthog_messagesuppression')
                            )
                                ? 63_000
                                : 58_000)
                    )
                    invocation.queueParameters = createSandboxParams({
                        from: { integrationId: 4 },
                        cc: memberEmail('cc'),
                    })
                    const result = await service.executeSendEmail(invocation, isTest)
                    expect(result).toMatchObject({ finished: true, skipped: true, metrics: [], messageAssets: [] })
                    expect(result.error).toBeUndefined()
                    expect(result.invocation.state.vmState?.stack.at(-1)).toEqual({ success: false })
                    expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                    expect(capture).toHaveBeenLastCalledWith(
                        expect.objectContaining({ id: team.id }),
                        'workflows sandbox email blocked',
                        { reason: 'recipient_not_member', is_test: isTest, blocked_recipient_count: 1 }
                    )
                } finally {
                    clock.mockRestore()
                    queries.mockRestore()
                }
            })

            it.each([false, true].flatMap((isTest) => [false, true].map((warm) => [isTest, warm] as const)))(
                'fails closed when member SQL fails (isTest=%s, warm=%s)',
                async (isTest, warm) => {
                    const membersPostgres = new PostgresRouter({
                        DATABASE_URL: hub.DATABASE_URL,
                        POSTGRES_CONNECTION_POOL_SIZE: 1,
                    })
                    const now = Date.now()
                    const clock = jest.spyOn(Date, 'now').mockReturnValue(now)
                    try {
                        await membersPostgres.query(
                            PostgresUse.COMMON_WRITE,
                            'CREATE TEMP TABLE posthog_team AS SELECT id, organization_id FROM public.posthog_team WHERE id = $1',
                            [team.id],
                            'test:own-sandbox-team-lookup'
                        )
                        service = createSandboxService(true, { membersPostgres })
                        if (warm) {
                            const first = await service.executeSendEmail(invocation, isTest)
                            expect(first.error).toBeUndefined()
                            expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                            clock.mockReturnValue(now + 61_000)
                        }
                        await membersPostgres.query(
                            PostgresUse.COMMON_WRITE,
                            'SET search_path = pg_temp',
                            [],
                            'test:fail-sandbox-member-lookup'
                        )
                        const { rows } = await membersPostgres.query<{ organization_id: string }>(
                            PostgresUse.COMMON_WRITE,
                            'SELECT organization_id FROM posthog_team WHERE id = $1',
                            [team.id],
                            'test:confirm-sandbox-team-lookup'
                        )
                        expect(rows).toEqual([{ organization_id: team.organization_id }])
                        invocation.queueParameters = createSandboxParams({
                            from: { integrationId: 4 },
                            cc: memberEmail('cc'),
                            bcc: memberEmail('bcc'),
                        })
                        const result = await service.executeSendEmail(invocation, isTest)
                        expect(result).toMatchObject({ finished: true, skipped: true, metrics: [], messageAssets: [] })
                        expect(result.error).toBeUndefined()
                        expect(result.invocation.state.vmState?.stack.at(-1)).toEqual({ success: false })
                        expect(sendEmailSpy).toHaveBeenCalledTimes(warm ? 1 : 0)
                        expect(result.logs).toContainEqual(
                            expect.objectContaining({
                                message: `Skipping send: could not check organization members for these addresses: ${memberEmail()}, ${memberEmail('cc')}, ${memberEmail('bcc')}. Try again, or verify your own domain to send to anyone.`,
                            })
                        )
                        expect(capture).toHaveBeenLastCalledWith(
                            expect.objectContaining({ id: team.id }),
                            'workflows sandbox email blocked',
                            { reason: 'check_failed', is_test: isTest, blocked_recipient_count: 3 }
                        )
                    } finally {
                        clock.mockRestore()
                        await membersPostgres.end()
                    }
                }
            )

            it.each([false, true])(
                'blocks previous organization members after a project transfer (isTest=%s)',
                async (isTest) => {
                    const otherOrganization = await createOtherOrganization()
                    const now = Date.now()
                    const clock = jest.spyOn(Date, 'now').mockReturnValue(now)
                    try {
                        service = createSandboxService(true)
                        const first = await service.executeSendEmail(invocation, isTest)
                        expect(first.error).toBeUndefined()
                        expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                        await hub.postgres.query(
                            PostgresUse.COMMON_WRITE,
                            'UPDATE posthog_team SET organization_id = $1 WHERE id = $2',
                            [otherOrganization, team.id],
                            'test:transfer-sandbox-team'
                        )
                        clock.mockReturnValue(now + 61_000)
                        invocation.queueParameters = createSandboxParams({ from: { integrationId: 4 } })

                        const transferred = await service.executeSendEmail(invocation, isTest)

                        expect(transferred).toMatchObject({ finished: true, skipped: true, metrics: [] })
                        expect(transferred.error).toBeUndefined()
                        expect(transferred.invocation.state.vmState?.stack.at(-1)).toEqual({ success: false })
                        expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                        expect(transferred.logs).toContainEqual(
                            expect.objectContaining({
                                message: `Skipping send: the sandbox sender only sends to active organization members with verified email addresses. Blocked addresses: ${memberEmail()}. Verify your own domain to send to anyone.`,
                            })
                        )
                        expect(capture).toHaveBeenLastCalledWith(
                            expect.objectContaining({ id: team.id }),
                            'workflows sandbox email blocked',
                            { reason: 'recipient_not_member', is_test: isTest, blocked_recipient_count: 1 }
                        )
                    } finally {
                        clock.mockRestore()
                        await hub.postgres.query(
                            PostgresUse.COMMON_WRITE,
                            'UPDATE posthog_team SET organization_id = $1 WHERE id = $2',
                            [team.organization_id, team.id],
                            'test:restore-sandbox-team'
                        )
                    }
                }
            )

            it('includes member query latency in the maximum cache age', async () => {
                const membersPostgres = new PostgresRouter(hub)
                const queries = jest.spyOn(membersPostgres, 'query')
                const now = Date.now()
                const clock = jest
                    .spyOn(Date, 'now')
                    .mockImplementation(() => now + (hasQueriedMembers(queries) ? 5_000 : 0))
                try {
                    service = createSandboxService(true, { membersPostgres })
                    const first = await service.executeSendEmail(invocation)
                    expect(first.error).toBeUndefined()
                    expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                    await hub.postgres.query(
                        PostgresUse.COMMON_WRITE,
                        'DELETE FROM posthog_organizationmembership WHERE user_id = $1',
                        [memberId],
                        'test:remove-member-after-slow-lookup'
                    )
                    clock.mockReturnValue(now + 60_000)
                    invocation.queueParameters = createSandboxParams({ from: { integrationId: 4 } })

                    const expired = await service.executeSendEmail(invocation)

                    expect(expired).toMatchObject({ finished: true, skipped: true, metrics: [] })
                    expect(expired.error).toBeUndefined()
                    expect(expired.invocation.state.vmState?.stack.at(-1)).toEqual({ success: false })
                    expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                    expect(capture).toHaveBeenLastCalledWith(
                        expect.objectContaining({ id: team.id }),
                        'workflows sandbox email blocked',
                        {
                            reason: 'recipient_not_member',
                            is_test: false,
                            blocked_recipient_count: 1,
                        }
                    )
                } finally {
                    clock.mockRestore()
                    queries.mockRestore()
                    await membersPostgres.end()
                }
            })

            it.each(
                [
                    { failure: 'a closed member connection', closeConnection: true, memberQueryMs: 0 },
                    { failure: 'a member query that takes a minute', closeConnection: false, memberQueryMs: 60_000 },
                ].flatMap((failure) => [false, true].map((isTest) => ({ ...failure, isTest })))
            )(
                'fails closed on $failure and bypasses it for own senders (isTest=$isTest)',
                async ({ closeConnection, memberQueryMs, isTest }) => {
                    const membersPostgres = new PostgresRouter(hub)
                    if (closeConnection) {
                        await membersPostgres.end()
                    }
                    const memberQueries = jest.spyOn(membersPostgres, 'query')
                    const now = Date.now()
                    const clock = jest
                        .spyOn(Date, 'now')
                        .mockImplementation(() => now + (hasQueriedMembers(memberQueries) ? memberQueryMs : 0))
                    try {
                        service = createSandboxService(true, { membersPostgres })

                        const result = await service.executeSendEmail(invocation, isTest)

                        expect(sendEmailSpy).not.toHaveBeenCalled()
                        expect(result).toMatchObject({ finished: true, skipped: true, metrics: [], messageAssets: [] })
                        expect(result.error).toBeUndefined()
                        expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
                        expect(result.logs).toContainEqual(
                            expect.objectContaining({
                                level: 'info',
                                message: `Skipping send: could not check organization members for these addresses: ${memberEmail()}. Try again, or verify your own domain to send to anyone.`,
                            })
                        )
                        expect(capture).toHaveBeenCalledWith(
                            expect.objectContaining({ id: team.id }),
                            'workflows sandbox email blocked',
                            { reason: 'check_failed', is_test: isTest, blocked_recipient_count: 1 }
                        )

                        invocation.queueParameters = createSandboxParams({ from: { integrationId: 1 } })
                        memberQueries.mockClear()
                        const ownSender = await service.executeSendEmail(invocation, isTest)
                        expect(ownSender.error).toBeUndefined()
                        expect(ownSender.skipped).not.toBe(true)
                        expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                        expect(memberQueries).not.toHaveBeenCalled()
                    } finally {
                        clock.mockRestore()
                        memberQueries.mockRestore()
                        if (!closeConnection) {
                            await membersPostgres.end()
                        }
                    }
                }
            )

            it.each(['membership', 'verification', 'active status', 'lookup failure'])(
                'refreshes cached members within a minute after %s changes',
                async (change) => {
                    const membersPostgres = new PostgresRouter(hub)
                    const now = Date.now()
                    const clock = jest.spyOn(Date, 'now').mockReturnValue(now)
                    let databaseClosed = false
                    try {
                        service = createSandboxService(true, { membersPostgres })
                        const params = createSandboxParams({ from: { integrationId: 4 } })
                        const first = await service.executeSendEmail(invocation)
                        expect(first.error).toBeUndefined()
                        expect(first.skipped).not.toBe(true)
                        expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                        if (change === 'membership') {
                            await hub.postgres.query(
                                PostgresUse.COMMON_WRITE,
                                'DELETE FROM posthog_organizationmembership WHERE user_id = $1 AND organization_id = $2',
                                [memberId, team.organization_id],
                                'test:remove-sandbox-member'
                            )
                        } else if (change !== 'lookup failure') {
                            await hub.postgres.query(
                                PostgresUse.COMMON_WRITE,
                                'UPDATE posthog_user SET is_active = $1, is_email_verified = $2 WHERE id = $3',
                                [change !== 'active status', change === 'verification' ? null : true, memberId],
                                'test:revoke-sandbox-member'
                            )
                        }
                        clock.mockReturnValue(now + 30_000)
                        invocation.queueParameters = params
                        const cached = await service.executeSendEmail(invocation)
                        expect(cached.error).toBeUndefined()
                        expect(cached.skipped).not.toBe(true)
                        expect(sendEmailSpy).toHaveBeenCalledTimes(2)

                        if (change === 'lookup failure') {
                            await membersPostgres.end()
                            databaseClosed = true
                        }
                        clock.mockReturnValue(now + 60_000)
                        invocation.queueParameters = params
                        const expired = await service.executeSendEmail(invocation)
                        expect(expired).toMatchObject({ finished: true, skipped: true, metrics: [] })
                        expect(expired.error).toBeUndefined()
                        expect(expired.invocation.state.vmState?.stack.at(-1)).toEqual({ success: false })
                        expect(sendEmailSpy).toHaveBeenCalledTimes(2)
                        expect(capture).toHaveBeenLastCalledWith(
                            expect.objectContaining({ id: team.id }),
                            'workflows sandbox email blocked',
                            {
                                reason: change === 'lookup failure' ? 'check_failed' : 'recipient_not_member',
                                is_test: false,
                                blocked_recipient_count: 1,
                            }
                        )
                    } finally {
                        clock.mockRestore()
                        if (!databaseClosed) {
                            await membersPostgres.end()
                        }
                    }
                }
            )

            it.each(['cc', 'bcc'] as const)(
                'blocks ambiguous %s mailboxes rather than sending a partially checked list',
                async (field) => {
                    service = createSandboxService(true)
                    invocation.queueParameters = createSandboxParams({
                        from: { integrationId: 4 },
                        [field]: `Example <${memberEmail('cc')}> <outside@example.com>`,
                    })
                    const result = await service.executeSendEmail(invocation)
                    expect(sendEmailSpy).not.toHaveBeenCalled()
                    expect(result).toMatchObject({ finished: true, skipped: true })
                    expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
                    expect(result.logs).toContainEqual(
                        expect.objectContaining({
                            message: expect.stringContaining('outside@example.com'),
                        })
                    )
                }
            )

            it('sends only the checked address when the To display name contains mailbox syntax', async () => {
                service = createSandboxService(true)
                invocation.queueParameters = createSandboxParams({
                    from: { integrationId: 4 },
                    to: { email: memberEmail(), name: 'Example" <outside@example.com>, "Example' },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                expect((sendEmailSpy.mock.calls[0][0] as SendEmailCommand).input.Destination?.ToAddresses).toEqual([
                    `"Example outside@example.com, Example" <${memberEmail()}>`,
                ])
            })

            it.each([
                [false, {}],
                [true, {}],
                [false, { verified: false }],
                [false, { name: '' }],
            ] as const)('skips with the global switch off (isTest=%s, identity=%j)', async (isTest, senderConfig) => {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE posthog_integration SET config = config || $1::jsonb WHERE team_id = $2 AND id = $3',
                    [JSON.stringify(senderConfig), team.id, getIntegrationId(4)],
                    'test:update-sandbox-sender'
                )
                service = createSandboxService(false)
                const result = await service.executeSendEmail(invocation, isTest)

                expect(result).toMatchObject({ finished: true, skipped: true, metrics: [] })
                expect(result.error).toBeUndefined()
                expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.logs).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            level: 'info',
                            message:
                                'Skipping send: the sandbox sender is unavailable right now. Verify your own domain to keep sending.',
                        }),
                    ])
                )
                expect(capture).toHaveBeenCalledWith(
                    expect.objectContaining({ id: team.id }),
                    'workflows sandbox email blocked',
                    {
                        reason: 'switch_off',
                        is_test: isTest,
                        blocked_recipient_count: 0,
                    }
                )
            })

            it.each([
                [
                    false,
                    '<body>Hello <a href="https://example.com">there</a>.</body>',
                    'Hello <a href="https://example.com">there</a>.',
                ],
                [
                    true,
                    '<body>Hello <a href="https://example.com">there</a>.</body>',
                    'Hello <a href="https://example.com">there</a>.',
                ],
                [false, '<body><!-- </body> --><p>Hello</p></body>', '<!-- </body> --><p>Hello</p>'],
                [
                    false,
                    '<body><p>Hello</p><template><p>Example</p></template></body>',
                    '<p>Hello</p><template><p>Example</p></template>',
                    true,
                ],
                [
                    false,
                    '<body><p>Hello</p><script>const greeting = "Hello"</script></body>',
                    '<p>Hello</p><script>const greeting = "Hello"</script>',
                    true,
                ],
                [
                    false,
                    '<body><style>div { display: none } /* </body> */</style><p>Hello</p></body>',
                    '<style>div { display: none } /* </body> */</style><p>Hello</p>',
                ],
                [false, '<body><textarea>Hello </body>', '<textarea>Hello &lt;/body&gt;</textarea>'],
                [false, '<body><plaintext>Hello </body>', '<pre>Hello &lt;/body&gt;</pre>'],
                [
                    false,
                    '<body><p>Hello</p><template><plaintext>Example',
                    '<p>Hello</p><template><pre>Example</pre></template>',
                    true,
                ],
                [
                    false,
                    '<head><template><plaintext>Example',
                    '<head><template><pre>Example</pre></template></head>',
                    true,
                ],
                [
                    false,
                    '<body><p>Hello</p><noscript><style>p {color:blue}',
                    '<p>Hello</p><div><style>p {color:blue}</style></div>',
                    true,
                ],
                [
                    false,
                    '<body><p>Hello</p><noscript>&lt;plaintext&gt;Example</noscript></body>',
                    '<p>Hello</p><div>&lt;plaintext&gt;Example</div>',
                    true,
                ],
                [
                    false,
                    '<body><table><tbody><tr><td>Hello</td></tr></tbody></table></body>',
                    '<td>Hello</td>',
                    true,
                    '<textarea>Preview text',
                ],
                [false, '<body><p>Hello</p><noscript><style></noscript><!--', '<p>Hello</p>', true],
                [
                    false,
                    '<body><p>Hello</p><noscript><style>/* </noscript><plaintext> */ p {color:blue}</style></noscript>',
                    '<style>/* </noscript><plaintext> */ p {color:blue}</style>',
                    true,
                ],
                [
                    false,
                    '<body><p>Hello</p><noscript><p title="</noscript><style>">Fallback</p></noscript></body>',
                    '<p title="</noscript><style>">Fallback</p>',
                    true,
                ],
                [
                    false,
                    '<body><noscript><style></noscript><script></style></noscript>Hello',
                    '<style></noscript><script></style>',
                    true,
                ],
                [
                    false,
                    '<body style="background:#525252;color:white"><p>Hello</p></body>',
                    '<body style="background:#525252;color:white"><p>Hello</p>',
                    true,
                ],
            ] as const)(
                'sends untracked with the fixed identity and organization footer (isTest=%s, html=%s)',
                async (isTest, html, expectedContent, htmlOnly: boolean = false, preheader?: string) => {
                    const outputs = new IngestionOutputs({
                        message_assets: new SingleIngestionOutput(
                            'message_assets',
                            'message_assets',
                            new KafkaProducerWrapper(new HighLevelProducer({})),
                            'DEFAULT'
                        ),
                    })
                    service = createSandboxService(true, { messageAssetsService: new MessageAssetsService(outputs) })
                    invocation.state.actionId = 'send-email'
                    invocation.queueParameters = createSandboxParams({
                        from: { integrationId: 4, email: 'override@example.com', name: 'Custom sender' },
                        replyTo: 'reply@example.com',
                        cc: memberEmail('cc'),
                        bcc: memberEmail('bcc'),
                        text: htmlOnly ? undefined : 'Hello there.',
                        html,
                        preheader,
                    })
                    invocation.hogFunction.metadata = { message_category_type: 'marketing', tracking_enabled: true }

                    const result = await service.executeSendEmail(invocation, isTest)

                    expect(result.error).toBeUndefined()
                    expect(result.finished).toBe(true)
                    expect(result.skipped).not.toBe(true)
                    expect(result.invocation.state.vmState?.stack).toEqual([{ success: true }])
                    expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                    const input = (sendEmailSpy.mock.calls[0][0] as SendEmailCommand).input
                    const footer = `This email was sent by Example organization via PostHog with the PostHog sandbox sender. Organization ID: ${team.organization_id}.`
                    expect(input).toMatchObject({
                        TenantName: 'sandbox-tenant',
                        ConfigurationSetName: 'sandbox-email',
                        FromEmailAddress: '"Example organization via PostHog" <fixed-sandbox@example.com>',
                        FeedbackForwardingEmailAddress: 'fixed-sandbox@example.com',
                        Destination: {
                            ToAddresses: [`"Example member" <${memberEmail()}>`],
                            CcAddresses: [memberEmail('cc')],
                            BccAddresses: [memberEmail('bcc')],
                        },
                        Content: {
                            Simple: {
                                Body: {
                                    ...(htmlOnly
                                        ? {}
                                        : { Text: { Data: `Hello there.\n\n${footer}`, Charset: 'UTF-8' } }),
                                    Html: {
                                        Charset: 'UTF-8',
                                    },
                                },
                            },
                        },
                    })
                    const sentHtml = input.Content?.Simple?.Body?.Html?.Data
                    expect(sentHtml).toContain(expectedContent)
                    expect(sentHtml?.endsWith(`>${footer}</div></body></html>`)).toBe(true)
                    for (const scriptingEnabled of [false, true]) {
                        expect(parseFragment(sentHtml!, { scriptingEnabled }).childNodes.at(-1)).toMatchObject({
                            tagName: 'div',
                            childNodes: [{ nodeName: '#text', value: footer }],
                        })
                        const root = parse(sentHtml!, { scriptingEnabled }).childNodes.find(
                            defaultTreeAdapter.isElementNode
                        )
                        const body = root?.childNodes
                            .filter(defaultTreeAdapter.isElementNode)
                            .find((node) => node.tagName === 'body')
                        expect(body?.childNodes.at(-1)).toMatchObject({
                            tagName: 'div',
                            namespaceURI: 'http://www.w3.org/1999/xhtml',
                            childNodes: [{ nodeName: '#text', value: footer }],
                        })
                    }
                    if (preheader) {
                        expect(sentHtml).toContain('&lt;textarea&gt;Preview text')
                    }
                    if (htmlOnly) {
                        expect(input.Content?.Simple?.Body?.Text).toBeUndefined()
                    }
                    expect(sentHtml).toContain(
                        'display:block!important;visibility:visible!important;opacity:1!important'
                    )
                    expect(sentHtml).toContain('background:#fff!important')
                    expect(input.ReplyToAddresses).toBeUndefined()
                    const headerNames = input.Content?.Simple?.Headers?.map((header) => header.Name)
                    expect(headerNames).toContain('X-PostHog-Tracking-Code')
                    expect(headerNames).not.toContain('List-Unsubscribe')
                    expect(headerNames).not.toContain('List-Unsubscribe-Post')
                    expect(result.logs.filter((log) => log.message.startsWith('Ignoring custom sender'))).toEqual([
                        expect.objectContaining({
                            level: 'info',
                            message:
                                'Ignoring custom sender and Reply-To settings: the sandbox sender uses a fixed identity.',
                        }),
                    ])
                    expect(result.metrics.map((metric) => metric.metric_name)).toEqual(
                        isTest ? [] : ['email_sent', 'email_untracked', 'email_sandbox_sent']
                    )
                    expect(capture).toHaveBeenCalledWith(
                        expect.objectContaining({ id: team.id, organization_id: team.organization_id }),
                        'workflows sandbox email sent',
                        { is_test: isTest, recipient_count: 3, source: isTest ? 'test' : 'workflow' }
                    )
                    expect(result.messageAssets).toEqual(
                        isTest
                            ? []
                            : [
                                  expect.objectContaining({
                                      html: input.Content?.Simple?.Body?.Html?.Data,
                                  }),
                              ]
                    )
                }
            )

            it.each([
                [false, '<body><p>Hello</p><script><!--<script>'],
                [true, '<body><p>Hello</p><script><!--<script>'],
                [false, '<body><p>Hello</p><template><script><!--<script>'],
                [true, '<body><p>Hello</p><template><script><!--<script>'],
                [
                    false,
                    '',
                    '',
                    'The sandbox email template must include HTML or text content. Update the template and try again.',
                ],
                [
                    true,
                    '',
                    '',
                    'The sandbox email template must include HTML or text content. Update the template and try again.',
                ],
            ] as const)(
                'rejects HTML that cannot retain the identification footer (isTest=%s, html=%s)',
                async (
                    isTest,
                    html,
                    text: string | undefined = undefined,
                    expectedError: string = 'The sandbox email template could not retain its identification footer. Update the template and try again.'
                ) => {
                    const outputs = new IngestionOutputs({
                        message_assets: new SingleIngestionOutput(
                            'message_assets',
                            'message_assets',
                            new KafkaProducerWrapper(new HighLevelProducer({})),
                            'DEFAULT'
                        ),
                    })
                    const limiter = await createSandboxLimiter('sandbox-rejected-html-budget-test')
                    service = createSandboxService(true, {
                        tierLimiter: limiter,
                        messageAssetsService: new MessageAssetsService(outputs),
                    })
                    invocation.state.actionId = 'send-email'
                    const params = createSandboxParams({ from: { integrationId: 4 }, text, html })
                    invocation.queueParameters = params

                    const result = await service.executeSendEmail(invocation, isTest)

                    expect(sendEmailSpy).not.toHaveBeenCalled()
                    expect(result).toMatchObject({
                        finished: true,
                        error: expectedError,
                        messageAssets: [],
                    })
                    expect(result.skipped).not.toBe(true)
                    expect(result.invocation.queueScheduledAt).toBeUndefined()
                    expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
                    expect(result.logs).toContainEqual(
                        expect.objectContaining({ level: 'error', message: result.error })
                    )
                    expect(result.logs.some((log) => log.message.startsWith('Email sent to'))).toBe(false)
                    expect(result.metrics.map((metric) => metric.metric_name)).toEqual(isTest ? [] : ['email_failed'])
                    expect(capture).not.toHaveBeenCalled()
                    expect(result.capturedPostHogEvents.some((event) => event.event === '$workflows_email_sent')).toBe(
                        false
                    )
                    expect(params).toEqual(createSandboxParams({ from: { integrationId: 4 }, text, html }))

                    invocation.queueParameters = createSandboxParams({ from: { integrationId: 1 } })
                    const ownSender = await service.executeSendEmail(invocation)
                    expect(ownSender.error).toBeUndefined()
                    expect(ownSender.finished).toBe(true)
                    expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                }
            )

            it('sends untracked with the fixed identity and organization footer for text-only content', async () => {
                service = createSandboxService(true)
                invocation.queueParameters = createSandboxParams({
                    from: { integrationId: 4 },
                    html: '',
                    text: 'Hello there.',
                })

                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(true)
                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                const input = (sendEmailSpy.mock.calls[0][0] as SendEmailCommand).input
                const textBody = input.Content?.Simple?.Body
                expect(textBody).toEqual({
                    Text: {
                        Data:
                            'Hello there.\n\nThis email was sent by Example organization via PostHog with the PostHog sandbox sender. Organization ID: ' +
                            team.organization_id +
                            '.',
                        Charset: 'UTF-8',
                    },
                })
                expect(capture).toHaveBeenCalledWith(
                    expect.objectContaining({ id: team.id, organization_id: team.organization_id }),
                    'workflows sandbox email sent',
                    { is_test: false, recipient_count: 1, source: 'workflow' }
                )
            })

            it.each([
                ['provider rejection', new Error('Message rejected'), true],
                ['provider throttle', new ThrottlingException('Rate exceeded'), false],
                ['missing message ID', null, true],
            ] as const)('does not report SES %s as a sandbox send', async (_name, error, finished) => {
                service = createSandboxService(true)
                if (error) {
                    sendEmailSpy.mockRejectedValue(error)
                } else {
                    sendEmailSpy.mockResolvedValue({})
                }

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                expect(result.finished).toBe(finished)
                expect(capture).not.toHaveBeenCalled()
                expect(result.metrics.map((metric) => metric.metric_name)).toEqual(finished ? ['email_failed'] : [])
                expect(result.invocation.state.vmState?.stack).toEqual(finished ? [{ success: false }] : [])
                if (finished) {
                    expect(result.error).toContain('Failed to send email via SES')
                } else {
                    expect(result.error).toBeUndefined()
                    expect(result.invocation.queueScheduledAt).toBeDefined()
                    expect(result.invocation.queueParameters).toMatchObject({ text: 'Test Text', html: 'Test HTML' })
                }
            })

            it('bypasses an exhausted sending tier and leaves its budget for own senders', async () => {
                const limiter = await createSandboxLimiter('sandbox-tier-budget-test')
                service = createSandboxService(true, { tierLimiter: limiter })
                const sandbox = await service.executeSendEmail(invocation)
                expect(sandbox).toMatchObject({ finished: true })
                expect(sandbox.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalledTimes(1)

                invocation.queueParameters = createSandboxParams({ from: { integrationId: 1 } })
                const ownSender = await service.executeSendEmail(invocation)
                expect(ownSender).toMatchObject({ finished: true })
                expect(ownSender.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalledTimes(2)

                const exhausted = await service.executeSendEmail(invocation)
                expect(exhausted.finished).toBe(false)
                expect(sendEmailSpy).toHaveBeenCalledTimes(2)

                invocation.queueParameters = createSandboxParams({ from: { integrationId: 4 } })
                const afterExhaustion = await service.executeSendEmail(invocation)
                expect(afterExhaustion).toMatchObject({ finished: true })
                expect(afterExhaustion.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalledTimes(3)
            })

            describe('daily caps', () => {
                const TEAM_CAP_REACHED =
                    "Skipping send: this project reached the sandbox sender's daily limit. Verify your own domain to send more."
                const recipientCapReached = (addresses: string): string =>
                    `Skipping send: these addresses reached the sandbox sender's daily limit per address: ${addresses}. Verify your own domain to send more.`
                const CAP_CHECK_FAILED =
                    "Skipping send: could not check the sandbox sender's daily limit. Try again later, or verify your own domain to send more."

                const send = async (
                    isTest: boolean,
                    params: Partial<CyclotronInvocationQueueParametersEmailType>
                ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> => {
                    invocation.state.vmState = { stack: [] } as any
                    invocation.queueParameters = createSandboxParams({ from: { integrationId: 4 }, ...params })
                    return await service.executeSendEmail(invocation, isTest)
                }
                const expectSent = (result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>): void => {
                    expect(result.error).toBeUndefined()
                    expect(result.skipped).not.toBe(true)
                    expect(result.invocation.state.vmState?.stack).toEqual([{ success: true }])
                }
                const expectSkipped = (
                    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
                    isTest: boolean,
                    message: string,
                    blocked: { reason: 'cap_reached' | 'check_failed'; blocked_recipient_count: number }
                ): void => {
                    expect(result).toMatchObject({ finished: true, skipped: true, metrics: [], messageAssets: [] })
                    expect(result.error).toBeUndefined()
                    expect(result.invocation.queueScheduledAt).toBeUndefined()
                    expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
                    expect(result.logs).toContainEqual(expect.objectContaining({ level: 'info', message }))
                    expect(capture).toHaveBeenLastCalledWith(
                        expect.objectContaining({ id: team.id }),
                        'workflows sandbox email blocked',
                        { ...blocked, is_test: isTest }
                    )
                }

                it.each([false, true])(
                    'holds the project to its daily cap without charging denied or own-sender sends (isTest=%s)',
                    async (isTest) => {
                        service = createSandboxService(true, { dailyTeamCap: 3 })

                        expectSent(await send(isTest, { from: { integrationId: 1 } }))
                        expectSent(await send(isTest, { to: { email: memberEmail() } }))
                        expectSkipped(
                            await send(isTest, {
                                to: { email: memberEmail() },
                                cc: memberEmail('cc'),
                                bcc: memberEmail('bcc'),
                            }),
                            isTest,
                            TEAM_CAP_REACHED,
                            { reason: 'cap_reached', blocked_recipient_count: 3 }
                        )
                        expectSent(await send(isTest, { to: { email: memberEmail('cc') } }))
                        expectSent(await send(isTest, { to: { email: memberEmail('bcc') } }))
                        expectSkipped(await send(isTest, { to: { email: memberEmail() } }), isTest, TEAM_CAP_REACHED, {
                            reason: 'cap_reached',
                            blocked_recipient_count: 1,
                        })
                        expect(sendEmailSpy).toHaveBeenCalledTimes(4)
                    }
                )

                it.each([false, true])(
                    'skips a send with one recipient at the daily cap and leaves the others their budget (isTest=%s)',
                    async (isTest) => {
                        service = createSandboxService(true, { dailyRecipientCap: 1 })

                        expectSent(await send(isTest, { to: { email: memberEmail('cc') } }))
                        expectSkipped(
                            await send(isTest, { to: { email: memberEmail() }, cc: memberEmail('cc').toUpperCase() }),
                            isTest,
                            recipientCapReached(memberEmail('cc').toUpperCase()),
                            { reason: 'cap_reached', blocked_recipient_count: 1 }
                        )
                        expectSent(await send(isTest, { to: { email: memberEmail() } }))
                        expect(sendEmailSpy).toHaveBeenCalledTimes(2)
                    }
                )

                it.each([
                    [
                        'the limiter is unreachable',
                        false,
                        {
                            capLimiter: new RateLimiterService(
                                {
                                    useClient: () => Promise.reject(new Error('Connection is closed.')),
                                    usePipeline: () => Promise.reject(new Error('Connection is closed.')),
                                },
                                { name: 'sandbox-unreachable-test' }
                            ),
                        },
                    ],
                    ['no limiter is configured', true, { capLimiter: null }],
                    ['the project cap is unset', false, { dailyTeamCap: NaN }],
                    ['the recipient cap is unset', true, { dailyRecipientCap: NaN }],
                    ['the project cap is zero', true, { dailyTeamCap: 0 }],
                    ['the recipient cap is fractional', false, { dailyRecipientCap: 1.5 }],
                ] as const)('skips every send when %s (isTest=%s)', async (_name, isTest, options) => {
                    service = createSandboxService(true, options)

                    expectSkipped(await send(isTest, { cc: memberEmail('cc') }), isTest, CAP_CHECK_FAILED, {
                        reason: 'check_failed',
                        blocked_recipient_count: 2,
                    })
                    expect(sendEmailSpy).not.toHaveBeenCalled()
                })
            })
        })
        describe('integration validation', () => {
            beforeEach(async () => {
                await insertIntegration(hub.postgres, team.id, {
                    id: getIntegrationId(2),
                    kind: 'email',
                    config: {
                        email: 'test@other-domain.com',
                        name: 'Test User',
                        domain: 'other-domain.com',
                        verified: false,
                    },
                })
                await insertIntegration(hub.postgres, team.id, {
                    id: getIntegrationId(3),
                    kind: 'slack',
                    config: {},
                })
            })
            it('should validate if the integration is not found', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 100 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(
                    `"Email integration not found. The sender configured for this step no longer exists — select a new sender in the workflow's email step."`
                )
            })
            it('should validate if the integration is not an email integration', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 3 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(
                    `"The integration configured for this step is not an email channel — select an email sender in the workflow's email step."`
                )
            })
            it('should validate if the integration is not the correct team', async () => {
                invocation.teamId = 100
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(
                    `"Email integration not found. The sender configured for this step no longer exists — select a new sender in the workflow's email step."`
                )
            })
            it('should validate if the email domain is not verified', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 2 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toMatchInlineSnapshot(`"The selected email integration domain is not verified"`)
            })
            it('should send identical from and feedback forwarding args', async () => {
                // This test is important for spam classification - feedback forwarding email MUST match from email
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalled()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.FromEmailAddress).toBe('"Test User" <test@posthog.com>')
                expect(sentCommand.input.FeedbackForwardingEmailAddress).toBe('test@posthog.com')
            })
            it('should allow a valid email integration and domain', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
            })

            it('uses and logs the sender selected for this workflow invocation', async () => {
                await insertIntegration(hub.postgres, team.id, {
                    id: getIntegrationId(4),
                    kind: 'email',
                    config: {
                        email: 'second@posthog.com',
                        name: 'Second Sender',
                        domain: 'posthog.com',
                        verified: true,
                        provider: 'ses',
                    },
                })
                invocation.id = Array.from({ length: 10 }, (_, index) => `invocation-${index}`).find(
                    (id) =>
                        selectEmailSenderIntegrationId(id, {
                            integrationId: getIntegrationId(1),
                            integrationIds: [getIntegrationId(1), getIntegrationId(4)],
                        }) === getIntegrationId(4)
                )!
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, integrationIds: [1, 4] },
                })

                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.FromEmailAddress).toBe('"Second Sender" <second@posthog.com>')
                expect(result.logs.map((log) => log.message)).toContain(
                    'Email sent to test@example.com from Second Sender <second@posthog.com>'
                )
            })
        })
        describe('from overrides', () => {
            it.each<[string, { email?: string; name?: string }, string, string]>([
                [
                    'address on the verified domain',
                    { email: 'community@posthog.com' },
                    '"Test User" <community@posthog.com>',
                    'community@posthog.com',
                ],
                [
                    'address with different domain casing',
                    { email: 'community@POSTHOG.com' },
                    '"Test User" <community@POSTHOG.com>',
                    'community@POSTHOG.com',
                ],
                ['name only', { name: 'Community Team' }, '"Community Team" <test@posthog.com>', 'test@posthog.com'],
                [
                    'name and address',
                    { email: 'community@posthog.com', name: 'Community Team' },
                    '"Community Team" <community@posthog.com>',
                    'community@posthog.com',
                ],
                [
                    'empty overrides fall back to the integration sender',
                    { email: '', name: '' },
                    '"Test User" <test@posthog.com>',
                    'test@posthog.com',
                ],
                [
                    'name with header-breaking characters is sanitized',
                    { name: '"Evil" <fake@evil.com>,\r\n Bcc:' },
                    '"Evil fake@evil.com, Bcc:" <test@posthog.com>',
                    'test@posthog.com',
                ],
            ])('applies the %s', async (_desc, fromOverride, expectedFrom, expectedFeedback) => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, ...fromOverride },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.FromEmailAddress).toBe(expectedFrom)
                expect(sentCommand.input.FeedbackForwardingEmailAddress).toBe(expectedFeedback)
            })

            it.each([
                ['an address on an unverified domain', 'someone@evil.com'],
                ['an address on a subdomain of the verified domain', 'someone@sub.posthog.com'],
                ['a list of addresses', 'a@posthog.com, b@posthog.com'],
                ['an RFC-822 formatted address', '"Name" <a@posthog.com>'],
                ['a value that is not an email address', 'not-an-email'],
            ])('discards %s and sends from the integration sender', async (_desc, email) => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, email },
                })
                const result = await service.executeSendEmail(invocation)
                // Failing the send would break every step still carrying the placeholder address
                // an old sender picker wrote, so an unusable override degrades to the integration's
                // own sender. The unverified address must never reach the provider either way.
                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.FromEmailAddress).toBe('"Test User" <test@posthog.com>')
                expect(result.logs.some((log) => log.level === 'warn' && log.message.includes(email))).toBe(true)
            })
        })
        describe('email sending', () => {
            it('should send an email', async () => {
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(sendEmailSpy).toHaveBeenCalled()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input).toMatchObject({
                    FromEmailAddress: '"Test User" <test@posthog.com>',
                    FeedbackForwardingEmailAddress: 'test@posthog.com',
                    Destination: {
                        ToAddresses: ['"Test User" <test@example.com>'],
                    },
                    Content: {
                        Simple: {
                            Subject: {
                                Data: 'Test Subject',
                            },
                            Body: {
                                Text: {
                                    Data: 'Test Text',
                                },
                            },
                        },
                    },
                })
            })
        })
        describe('SES throttle handling', () => {
            // SES throttle responses become reschedule-with-backoff rather than
            // permanent failures. The local Valkey bucket already gates dequeue;
            // this path is the safety net for when SES disagrees with our estimate.
            // Retryable: TooManyRequestsException (SES v2's rate-limit class) and
            // ThrottlingException (generic AWS SDK throttle name surfaced from
            // the transport layer). SendingPausedException is *not* retryable —
            // it signals a reputation/account-state issue that needs operator
            // attention, not a 500ms reschedule.
            const throttleCases: Array<[string, () => Error]> = [
                [
                    'TooManyRequestsException',
                    () => new TooManyRequestsException({ $metadata: {}, message: 'Too many requests' }),
                ],
                ['ThrottlingException', () => new ThrottlingException('Rate exceeded')],
            ]
            it.each(throttleCases)('reschedules instead of failing when SES returns %s', async (_name, makeError) => {
                sendEmailSpy.mockRejectedValueOnce(makeError())

                const before = Date.now()
                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                // Jittered 500–1000ms retry: must land in the future but never further
                // than the upper bound + scheduler overhead.
                expect(scheduledMs).toBeGreaterThanOrEqual(before + 400)
                expect(scheduledMs).toBeLessThan(before + 2000)
                // No business metric emitted on throttle — the eventual retry
                // will produce email_sent.
                expect(result.metrics ?? []).toEqual([])
            })

            it('keeps the send priority class across a throttle reschedule', async () => {
                // A bulk send enters the email queue at priority 1. On an SES throttle the job is
                // rescheduled on the email queue, so its priority must stay 1 — resetting it to the
                // fast-lane value 0 would let throttled bulk bursts jump ahead of transactional sends,
                // which is exactly the traffic the fast lane exists to protect.
                invocation.queuePriority = 1
                sendEmailSpy.mockRejectedValueOnce(
                    new TooManyRequestsException({ $metadata: {}, message: 'Too many requests' })
                )

                const result = await service.executeSendEmail(invocation)

                expect(result.finished).toBe(false)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                expect(result.invocation.queuePriority).toBe(1)
            })

            it('hard-fails (not retry) when SES returns SendingPausedException', async () => {
                // Reputation/account-state pause won't recover in 500ms; retrying
                // just burns reschedules. Hard-fail so the failure surfaces via
                // email_failed and an operator can investigate.
                sendEmailSpy.mockRejectedValueOnce(
                    new SendingPausedException({ $metadata: {}, message: 'Sending paused' })
                )

                const result = await service.executeSendEmail(invocation)

                expect(result.finished).toBe(true)
                expect(result.error).toMatch(/Failed to send email via SES: Sending paused/)
                expect(result.metrics).toEqual(
                    expect.arrayContaining([expect.objectContaining({ metric_name: 'email_failed' })])
                )
            })

            it('still fails the job for non-throttle SES errors', async () => {
                sendEmailSpy.mockRejectedValueOnce(
                    new MessageRejected({ $metadata: {}, message: 'something else broke' })
                )

                const result = await service.executeSendEmail(invocation)

                expect(result.finished).toBe(true)
                expect(result.error).toMatch(/Failed to send email via SES: something else broke/)
                // Business metric should record the failure.
                expect(result.metrics).toEqual(
                    expect.arrayContaining([expect.objectContaining({ metric_name: 'email_failed' })])
                )
            })
        })

        describe('workflow sending rate limit', () => {
            let claimOrReserve: jest.Mock
            let limitedService: EmailService
            let limitedSendSpy: jest.SpyInstance

            beforeEach(() => {
                claimOrReserve = jest.fn().mockResolvedValue({ granted: 1, retryAfterMs: null, reserved: false })
                limitedService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                    },
                    hub.integrationManager,
                    new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    undefined,
                    { claimOrReserve } as unknown as RateLimiterService
                )
                limitedSendSpy = jest.spyOn(limitedService.sesV2Client!, 'send') as any
                limitedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.hogFunction.metadata = {
                    email_sending_rate_limit: { count: 120, period: 'minute' },
                }
            })

            it.each([
                // A reserved slot means "your turn is at this exact time". Park on it as-is:
                // wake earlier and the token is not there yet, so the send gets denied again
                // and goes to the back of the line.
                ['exactly at the reserved slot', 5000, true, 5000, 5000],
                // Sub-second slots too: flooring them to 1s would push the wake off its
                // slot and collide it with the slot behind.
                ['exactly at a sub-second reserved slot', 500, true, 500, 500],
                // Past the horizon there are no slots left and everyone gets the same "come
                // back in an hour", so those wakes get spread out (1x-2x) instead.
                [
                    'with spread when re-contending at the horizon',
                    60 * 60 * 1000,
                    false,
                    60 * 60 * 1000,
                    2 * 60 * 60 * 1000,
                ],
                // No horizon at all (error-path denial) falls back to the clamped token
                // interval: 120/minute refills every 500ms, clamped to [1s, 2s] jittered.
                ['on the clamped token interval when the limiter could not reserve', null, false, 1000, 2000],
            ])('reschedules a denied send %s', async (_name, retryAfterMs, reserved, minDelayMs, maxDelayMs) => {
                claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs, reserved })

                const before = Date.now()
                const result = await limitedService.executeSendEmail(invocation)
                const after = Date.now()

                expect(limitedSendSpy).not.toHaveBeenCalled()
                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                // The reschedule must carry the email payload forward: without queueParameters the
                // retry has nothing to send and the throttled email is dropped rather than delayed.
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                // Bracketed against both ends of the call, so the bounds hold the delay itself
                // and not the time the call took.
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + minDelayMs)
                expect(scheduledMs).toBeLessThanOrEqual(after + maxDelayMs)
                // No business metric on a pacing delay — the eventual send produces email_sent.
                expect(result.metrics ?? []).toEqual([])
            })

            it('parks consecutive denials on their exact reserved slots', async () => {
                // At 30/minute the limiter hands out slots 2s apart. Each send has to wake at
                // its own slot, exactly. If one wake moves even a little earlier, its token is
                // not there yet and the send goes to the back of the line.
                invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 30, period: 'minute' } }
                const slotMs = 2000

                for (let i = 1; i <= 3; i++) {
                    claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs: i * slotMs, reserved: true })

                    const before = Date.now()
                    const denied = await limitedService.executeSendEmail(invocation)
                    const after = Date.now()

                    expect(denied.finished).toBe(false)
                    const parkedAt = denied.invocation.queueScheduledAt!.toMillis()
                    expect(parkedAt).toBeGreaterThanOrEqual(before + i * slotMs)
                    expect(parkedAt).toBeLessThanOrEqual(after + i * slotMs)
                }
            })

            it('scatters a backlog that overflows the reservation horizon', async () => {
                // When the backlog is deeper than one hour of refill there are no slots left:
                // every remaining send gets "come back in an hour". If they all came back at
                // the same moment they would pile up at the front of the queue again, so their
                // wakes get spread out over the hour.
                claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs: 60 * 60 * 1000, reserved: false })

                const parkedAt: number[] = []
                for (let i = 0; i < 20; i++) {
                    const denied = await limitedService.executeSendEmail(invocation)
                    expect(denied.finished).toBe(false)
                    parkedAt.push(denied.invocation.queueScheduledAt!.toMillis())
                }

                // The wakes must cover a real part of the hour, not one narrow window:
                // 20 of them spread over an hour should easily span more than 10 minutes.
                const spreadMs = Math.max(...parkedAt) - Math.min(...parkedAt)
                expect(spreadMs).toBeGreaterThan(10 * 60 * 1000)
            })

            it('claims one token scoped to the workflow and sends when granted', async () => {
                const result = await limitedService.executeSendEmail(invocation)

                expect(claimOrReserve).toHaveBeenCalledWith(
                    {
                        key: `@posthog/workflow-email-rate/${team.id}/function-1`,
                        requested: 1,
                        // Burst capacity is ~1s of budget (not the count), so the first period can't
                        // send ~2x the limit and an idle-expired bucket can't re-burst.
                        capacity: 2,
                        refillPerSecond: 2,
                    },
                    60 * 60 * 1000
                )
                expect(result.finished).toBe(true)
                expect(limitedSendSpy).toHaveBeenCalled()
            })

            it.each([
                ['no rate limit is configured', (): void => void (invocation.hogFunction.metadata = {})],
                [
                    'the configured value is malformed',
                    (): void =>
                        void (invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 'lots' } }),
                ],
            ])('does not consult the bucket when %s', async (_name, setup) => {
                setup()

                const result = await limitedService.executeSendEmail(invocation)

                expect(claimOrReserve).not.toHaveBeenCalled()
                expect(result.finished).toBe(true)
                expect(limitedSendSpy).toHaveBeenCalled()
            })

            it('skips the limit for test sends', async () => {
                claimOrReserve.mockResolvedValue({ granted: 0, retryAfterMs: 5000 })

                const result = await limitedService.executeSendEmail(invocation, true)

                expect(claimOrReserve).not.toHaveBeenCalled()
                expect(result.finished).toBe(true)
                expect(limitedSendSpy).toHaveBeenCalled()
            })
        })

        // A workflow over its sending limit must not crowd out anyone else: every denied
        // send parks on its own future slot instead of retrying every second, and a
        // workflow without a limit keeps sending right past the parked backlog.
        describe('a denied backlog cannot crowd out other sends', () => {
            it('spreads denied sends over distinct future slots and leaves unlimited workflows untouched', async () => {
                const redis = createRedisV2PoolFromConfig({
                    connection: hub.CDP_REDIS_HOST
                        ? {
                              url: hub.CDP_REDIS_HOST,
                              options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                          }
                        : { url: hub.REDIS_URL },
                    poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                    poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
                })
                const realLimitedService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                    },
                    hub.integrationManager,
                    new TeamWorkflowsConfigService(hub.postgres, hub.pubSub),
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    undefined,
                    new RateLimiterService(redis, { name: 'workflow-email-backlog-test' })
                )
                const realSendSpy = jest.spyOn(realLimitedService.sesV2Client!, 'send') as any
                realSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                // 6/minute: refill 0.1 tokens/s, burst capacity 1. Slow enough that the test's
                // own wall-clock time cannot refill a token between the denials below.
                invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 6, period: 'minute' } }

                const first = await realLimitedService.executeSendEmail(invocation)
                expect(first.finished).toBe(true)

                const parkedAt: number[] = []
                for (let i = 0; i < 4; i++) {
                    const denied = await realLimitedService.executeSendEmail(invocation)
                    expect(denied.finished).toBe(false)
                    parkedAt.push(denied.invocation.queueScheduledAt!.toMillis())
                }

                // Each denial must hold its own slot, one token interval (10s) apart. If the
                // parks all landed in the same window, the gaps between them would be near
                // zero or negative and the backlog would wake as one herd.
                for (let i = 1; i < parkedAt.length; i++) {
                    const gapMs = parkedAt[i] - parkedAt[i - 1]
                    expect(gapMs).toBeGreaterThan(9_000)
                    expect(gapMs).toBeLessThan(11_000)
                }

                // A workflow without a limit on the same team sends immediately, regardless of
                // the backlog next to it.
                const other = createExampleInvocation({ team_id: team.id, id: 'function-b' })
                other.id = 'invocation-b'
                other.state.vmState = { stack: [] } as any
                other.queueParameters = createEmailParams({ from: { integrationId: 1 } })
                const otherResult = await realLimitedService.executeSendEmail(other)

                expect(otherResult.finished).toBe(true)
                expect(realSendSpy).toHaveBeenCalledTimes(2)
            })
        })

        describe('team sending cap (enforce mode)', () => {
            let claimAllOrNothingPair: jest.Mock
            let cappedService: EmailService
            let cappedSendSpy: jest.SpyInstance

            beforeEach(() => {
                claimAllOrNothingPair = jest.fn()
                const configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
                jest.spyOn(configService, 'getEmailSendingTier').mockResolvedValue(0)
                cappedService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                        teamEmailCapMode: 'enforce',
                        teamEmailTierHourlyCaps: [100],
                        teamEmailTierDailyCaps: [200],
                    },
                    hub.integrationManager,
                    configService,
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    undefined,
                    null,
                    { claimAllOrNothingPair } as unknown as RateLimiterService
                )
                cappedSendSpy = jest.spyOn(cappedService.sesV2Client!, 'send') as any
                cappedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            })

            afterEach(() => {
                jest.restoreAllMocks()
            })

            it.each([
                // A reserved slot is exclusive and is parked on exactly; spreading it would
                // collide it with the slot in front.
                ['parks exactly on a reserved slot', 30 * 60 * 1000, true, 30 * 60 * 1000, 30 * 60 * 1000],
                // Past the horizon nothing is reserved: every overflow caller gets the same
                // wake back and spreads itself 1x-2x across the horizon.
                [
                    'spreads an overflow wake across the horizon',
                    60 * 60 * 1000,
                    false,
                    60 * 60 * 1000,
                    2 * 60 * 60 * 1000,
                ],
            ])('%s', async (_name, retryAfterMs, reserved, minMs, maxMs) => {
                claimAllOrNothingPair.mockResolvedValue({ granted: false, deniedIndex: 1, retryAfterMs, reserved })

                const before = Date.now()
                const result = await cappedService.executeSendEmail(invocation)

                expect(cappedSendSpy).not.toHaveBeenCalled()
                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                // The reschedule must carry the email payload forward, same as the workflow limit.
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + minMs)
                expect(scheduledMs).toBeLessThan(before + maxMs + 5000)
                // A real denial names the cap it hit, which is what makes the limiter-fault case
                // above distinguishable to the customer reading the run's logs.
                expect(result.logs.map((log) => log.message).join(' ')).toContain('reached its email sending limit of')
            })

            it('retries on the token bucket cadence when the limiter reports no horizon', async () => {
                // A Valkey fault denies with no horizon. Parking on the daily cap's pacing
                // interval would hold the email long after the limiter recovered.
                jest.spyOn(Math, 'random').mockReturnValue(0)
                claimAllOrNothingPair.mockResolvedValue({
                    granted: false,
                    deniedIndex: null,
                    retryAfterMs: null,
                    reserved: false,
                })

                const before = Date.now()
                const result = await cappedService.executeSendEmail(invocation)

                expect(cappedSendSpy).not.toHaveBeenCalled()
                expect(result.finished).toBe(false)
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + 5 * 60 * 1000)
                expect(scheduledMs).toBeLessThan(before + 5 * 60 * 1000 + 5000)
                // No bucket denied, so the customer must not be told they hit a cap they never hit.
                const messages = result.logs.map((log) => log.message).join(' ')
                expect(messages).not.toContain('reached its email sending limit')
                expect(messages).toContain("Could not check this project's email sending limit")
            })

            it('sends when the claim is granted', async () => {
                claimAllOrNothingPair.mockResolvedValue({
                    granted: true,
                    deniedIndex: null,
                    retryAfterMs: null,
                    reserved: false,
                })

                const result = await cappedService.executeSendEmail(invocation)

                // The reservation horizon must reach the limiter, or denials fall back to
                // shared-horizon wakes and a denied backlog re-herds.
                expect(claimAllOrNothingPair).toHaveBeenCalledWith(
                    expect.anything(),
                    expect.any(Number),
                    60 * 60 * 1000
                )
                expect(result.finished).toBe(true)
                expect(cappedSendSpy).toHaveBeenCalled()
            })

            // A team over its tier cap must not slow anyone else down: its denied sends get
            // their own future slots instead of all waking together, and another team's send
            // goes straight out. Runs against the real limiter.
            it('spreads a capped team over distinct slots while another team keeps sending', async () => {
                const hourlyCap = 360
                const dailyCap = 8640
                const redis = createRedisV2PoolFromConfig({
                    connection: hub.CDP_REDIS_HOST
                        ? {
                              url: hub.CDP_REDIS_HOST,
                              options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                          }
                        : { url: hub.REDIS_URL },
                    poolMinSize: hub.REDIS_POOL_MIN_SIZE,
                    poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
                })
                const limiter = new RateLimiterService(redis, { name: 'team-email-cap-test' })
                const configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
                jest.spyOn(configService, 'getEmailSendingTier').mockResolvedValue(0)
                const enforcedService = new EmailService(
                    {
                        sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                        sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                        sesRegion: hub.SES_REGION,
                        sesEndpoint: hub.SES_ENDPOINT,
                        sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                        sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                        teamEmailCapMode: 'enforce',
                        teamEmailTierHourlyCaps: [hourlyCap],
                        teamEmailTierDailyCaps: [dailyCap],
                    },
                    hub.integrationManager,
                    configService,
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL,
                    new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
                    new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
                    new RecipientsManagerService(hub.postgres),
                    undefined,
                    null,
                    limiter
                )
                const enforcedSendSpy = jest.spyOn(enforcedService.sesV2Client!, 'send') as any
                enforcedSendSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                // Drain the capped team's hourly bucket so every send below is a denial. The
                // 0.1 tokens/s refill makes the slot spacing 10s, far above test wall-clock.
                const buckets = teamEmailCapBuckets(team.id, hourlyCap, dailyCap)
                await limiter.claimUpTo({
                    key: buckets[0].key,
                    requested: hourlyCap,
                    capacity: buckets[0].capacity,
                    refillPerSecond: buckets[0].refillPerSecond,
                })

                const parkedAt: number[] = []
                for (let i = 0; i < 4; i++) {
                    const denied = await enforcedService.executeSendEmail(invocation)
                    expect(denied.finished).toBe(false)
                    parkedAt.push(denied.invocation.queueScheduledAt!.toMillis())
                }
                // Distinct slots one token interval apart, not a herd at the shared horizon.
                for (let i = 1; i < parkedAt.length; i++) {
                    const gapMs = parkedAt[i] - parkedAt[i - 1]
                    expect(gapMs).toBeGreaterThan(9_000)
                    expect(gapMs).toBeLessThan(11_000)
                }

                // A second team's buckets are cold, so its send goes straight out. Tier caps
                // isolate per team; the capped team's backlog must not reach anyone else.
                const otherTeam = (await createTestTeamFixture(hub.postgres)).team
                await insertIntegration(hub.postgres, otherTeam.id, {
                    id: otherTeam.id + 1,
                    kind: 'email',
                    config: {
                        email: 'test@posthog.com',
                        name: 'Test User',
                        domain: 'posthog.com',
                        verified: true,
                        provider: 'ses',
                    },
                })
                const other = createExampleInvocation({ team_id: otherTeam.id, id: 'function-other-team' })
                other.id = 'invocation-other-team'
                other.state.vmState = { stack: [] } as any
                other.queueParameters = createEmailParams()
                other.queueParameters.from = { integrationId: otherTeam.id + 1 }
                const otherResult = await enforcedService.executeSendEmail(other)

                expect(otherResult.finished).toBe(true)
                expect(enforcedSendSpy).toHaveBeenCalledTimes(1)
            })
        })
    })
    describe('native email sending with maildev', () => {
        let invocation: CyclotronJobInvocationHogFunction
        const mailDevAPI = new MailDevAPI()
        beforeEach(async () => {
            const actualFetch = jest.requireActual('~/common/utils/request').fetch as jest.Mock
            mockFetch.mockImplementation((...args: any[]): Promise<any> => {
                return actualFetch(...args) as any
            })
            await insertIntegration(hub.postgres, team.id, {
                id: getIntegrationId(1),
                kind: 'email',
                config: {
                    email: 'test@posthog.com',
                    name: 'Test User',
                    domain: 'posthog.com',
                    verified: true,
                    provider: 'maildev',
                },
            })
            invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = {
                stack: [],
            } as any
            invocation.queueParameters = createEmailParams({ from: { integrationId: 1 } })
            await mailDevAPI.clearEmails()
        })
        it('should send an email', async () => {
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            await waitForExpect(async () => expect(mailDevAPI.getEmails()).resolves.toHaveLength(1))
            const emails = await mailDevAPI.getEmails()
            expect(emails).toHaveLength(1)
            expect(emails[0]).toMatchObject({
                from: [{ address: 'test@posthog.com', name: 'Test User' }],
                html: 'Test HTML',
                subject: 'Test Subject',
                text: 'Test Text',
                to: [{ address: 'test@example.com', name: 'Test User' }],
            })
        })
        it('should include tracking code in the email with distinct_id', async () => {
            invocation.queueParameters = createEmailParams({
                html: '<body>Hi! <a href="https://example.com">Click me</a></body>',
            })
            await service.executeSendEmail(invocation)
            await waitForExpect(async () => expect(mailDevAPI.getEmails()).resolves.toHaveLength(1))
            const emails = await mailDevAPI.getEmails()
            expect(emails).toHaveLength(1)
            // ph_id may be unsigned (base64url only) or signed (base64url + `.` + signature) depending on
            // ENCRYPTION_SALT_KEYS. Match the structure, not the exact value.
            expect(emails[0].html).toMatch(
                /^<body>Hi! <a href="http:\/\/localhost:8010\/public\/m\/redirect\?ph_id=[A-Za-z0-9._-]+&target=https%3A%2F%2Fexample\.com">Click me<\/a><img src="http:\/\/localhost:8010\/public\/m\/pixel\?ph_id=[A-Za-z0-9._-]+" style="display: none;" \/><\/body>$/
            )
        })
    })
    describe('native email sending with ses', () => {
        let invocation: CyclotronJobInvocationHogFunction
        let sendEmailSpy: jest.SpyInstance
        beforeEach(async () => {
            const actualFetch = jest.requireActual('~/common/utils/request').fetch as jest.Mock
            mockFetch.mockImplementation((...args: any[]): Promise<any> => {
                return actualFetch(...args) as any
            })
            await insertIntegration(hub.postgres, team.id, {
                id: getIntegrationId(1),
                kind: 'email',
                config: {
                    email: 'test@posthog-test.com',
                    name: 'Test User',
                    domain: 'posthog-test.com',
                    verified: true,
                    provider: 'ses',
                },
            })
            invocation = createExampleInvocation({ team_id: team.id, id: 'function-1' })
            invocation.id = 'invocation-1'
            invocation.state.vmState = {
                stack: [],
            } as any
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            sendEmailSpy = jest.spyOn(service.sesV2Client!, 'send')
        })

        it('should error if not verified', async () => {
            sendEmailSpy.mockRejectedValue(new Error('Email address not verified "Test User" <test@posthog-test.com>'))
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toEqual(
                'Failed to send email via SES: Email address not verified "Test User" <test@posthog-test.com>'
            )
        })

        it('should send an email if verified', async () => {
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            expect(sendEmailSpy).toHaveBeenCalledTimes(1)
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            // The SES tag carries the short unsigned code (no dot); the signed code (with distinct_id)
            // rides in the header.
            expect(sentCommand.input).toMatchObject({
                ConfigurationSetName: 'posthog-messaging',
                Content: {
                    Simple: {
                        Body: {
                            Html: { Charset: 'UTF-8', Data: 'Test HTML' },
                            Text: { Charset: 'UTF-8', Data: 'Test Text' },
                        },
                        Subject: { Charset: 'UTF-8', Data: 'Test Subject' },
                    },
                },
                Destination: { ToAddresses: ['"Test User" <test@example.com>'] },
                EmailTags: [{ Name: 'ph_id', Value: expect.stringMatching(/^[A-Za-z0-9_-]+$/) }],
                FeedbackForwardingEmailAddress: 'test@posthog-test.com',
                FromEmailAddress: '"Test User" <test@posthog-test.com>',
            })
        })

        it('records a send-time metric for normal sends but not for test sends', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

            const normal = await service.executeSendEmail(invocation)
            expect(normal.metrics.map((m) => m.metric_name)).toContain('email_sent')

            const testSend = await service.executeSendEmail(invocation, true)
            expect(testSend.metrics).toEqual([])
        })

        describe('suppression enforcement at send time', () => {
            // Guards the "email hog function destination bypasses shouldSkipAction, so suppression
            // isn't enforced on that path" gap. executeSendEmail is the single choke point every
            // outbound send goes through — the suppression check has to live here so it can't be
            // skipped just by choosing a different upstream code path.
            it('does not call SES when the recipient is on the suppression list', async () => {
                const isSuppressedSpy = jest
                    .spyOn(service['emailSuppressionService'], 'isSuppressed')
                    .mockResolvedValue(true)
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(isSuppressedSpy).toHaveBeenCalled()
                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_suppressed')
                expect(result.metrics.map((m) => m.metric_name)).not.toContain('email_sent')
            })

            it('calls SES when the recipient is not suppressed', async () => {
                jest.spyOn(service['emailSuppressionService'], 'isSuppressed').mockResolvedValue(false)
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_sent')
            })
        })

        describe('SES tenant attribution', () => {
            it('attributes the send to the team tenant', async () => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.TenantName).toEqual(`team-${team.id}`)
            })

            it('attributes test-panel sends too — they are real SES sends', async () => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation, true)

                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.TenantName).toEqual(`team-${team.id}`)
            })
        })

        describe('team suspension enforcement at send time', () => {
            // Guards both suspension switches: while a team is suspended, no send path may
            // reach SES — including editor test sends, which count against the tenant too.
            // These write a real config row so they also cover the service's SELECT; mocking
            // getEmailSendingSuspension would pass with the column missing from the query.
            const suspendTeam = async (): Promise<void> => {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO workflows_teamworkflowsconfig
                        (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                         email_sending_suspended_at, email_sending_suspension_reason)
                     VALUES ($1, false, 'off', now(), 'testing suspension')
                     ON CONFLICT (team_id) DO UPDATE SET email_sending_suspended_at = now()`,
                    [team.id],
                    'test-suspend-email-sending'
                )
            }

            it('does not call SES while the team is suspended and records email_suspended', async () => {
                await suspendTeam()
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics.map((m) => m.metric_name)).toEqual(['email_suspended'])
                expect(invocation.state.vmState?.stack).toEqual([{ success: false }])
            })

            it('blocks editor test sends while suspended without recording metrics', async () => {
                await suspendTeam()
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation, true)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics).toEqual([])
            })

            // A per-workflow pause holds one workflow's email while the rest of the project keeps
            // sending. Same choke point as the team switch above, so no upstream route bypasses it.
            it('does not call SES while the workflow is paused and records email_paused', async () => {
                invocation.hogFunction.metadata = {
                    email_sending_paused_at: '2026-01-01T00:00:00Z',
                    email_sending_paused_reason: 'Spam complaints reached 2% of the 400 emails sent.',
                }
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics.map((m) => m.metric_name)).toEqual(['email_paused'])
                expect(invocation.state.vmState?.stack).toEqual([{ success: false }])
                expect(result.logs.map((l) => l.message).join(' ')).toContain('Spam complaints reached 2%')
                // Flags the skip so the flow-level billing gate charges nothing for a send that never sent.
                expect(result.skipped).toBe(true)
            })

            it('tells a staff-paused workflow to contact support instead of the resume button', async () => {
                invocation.hogFunction.metadata = {
                    email_sending_paused_at: '2026-01-01T00:00:00Z',
                    email_sending_paused_reason:
                        "PostHog staff paused this workflow's email to protect delivery for everyone.",
                    email_sending_paused_by: 'staff',
                }
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                const messages = result.logs.map((l) => l.message).join(' ')
                expect(messages).toContain('Contact support')
                expect(messages).not.toContain('Resume it from the workflow page')
            })

            it('blocks editor test sends while the workflow is paused without recording metrics', async () => {
                invocation.hogFunction.metadata = { email_sending_paused_at: '2026-01-01T00:00:00Z' }
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation, true)

                expect(sendEmailSpy).not.toHaveBeenCalled()
                expect(result.metrics).toEqual([])
            })

            it('sends once the workflow pause is cleared', async () => {
                invocation.hogFunction.metadata = {
                    email_sending_paused_at: null,
                    email_sending_paused_reason: null,
                }
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_sent')
            })

            const setProviderTenantStatus = async (status: string): Promise<void> => {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    // email_sending_suspension_reason is NOT NULL and its default is Django-side,
                    // not on the column, so a raw INSERT has to supply it.
                    `INSERT INTO workflows_teamworkflowsconfig
                        (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                         email_sending_suspension_reason, ses_tenant_sending_status)
                     VALUES ($1, false, 'off', '', $2)
                     ON CONFLICT (team_id) DO UPDATE SET ses_tenant_sending_status = $2`,
                    [team.id, status],
                    'test-set-ses-tenant-sending-status'
                )
            }

            // A paused provider tenant rejects every send, so the send path has to read the stored
            // state. Only DISABLED blocks: REINSTATED is what a tenant the provider has restored
            // reads, so treating any non-ENABLED status as paused would withhold accepted sends.
            it.each([
                ['DISABLED', 0, 'email_suspended'],
                ['REINSTATED', 1, 'email_sent'],
            ])('provider tenant status %s: %i SES calls, records %s', async (status, sesCalls, metricName) => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                await setProviderTenantStatus(status as string)

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).toHaveBeenCalledTimes(sesCalls as number)
                expect(result.metrics.map((m) => m.metric_name)).toContain(metricName)
            })

            // The send path caches this row for minutes, so a pause that lands after the first read
            // would keep sending — and a reinstatement would keep blocking — until the entry aged
            // out. The provider state sync announces each change to close that window.
            it('picks up a provider status change announced while the config is cached', async () => {
                const configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
                await setProviderTenantStatus('ENABLED')
                expect(await configService.getEmailSendingSuspension(team.id)).toBeNull()

                await setProviderTenantStatus('DISABLED')

                await waitForExpect(async () => {
                    // Republished every poll: subscribing is asynchronous, so the first publish can
                    // land before this subscriber is listening. Marking for refresh is idempotent.
                    await hub.pubSub.publish('reload-team-workflows-config', JSON.stringify({ teamId: team.id }))
                    expect(await configService.getEmailSendingSuspension(team.id)).toEqual('provider')
                }, 3000)
            })

            it('fails open when the suspension lookup errors', async () => {
                // The config lookup rejecting must never block a legitimate send. Rejects once:
                // the suspension check is the first config read; later reads use the real loader.
                jest.spyOn(service['teamWorkflowsConfigService'], 'get').mockRejectedValueOnce(new Error('pg down'))
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })

                const result = await service.executeSendEmail(invocation)

                expect(sendEmailSpy).toHaveBeenCalledTimes(1)
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_sent')
            })
        })

        it('should include cc addresses in SES destination', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                cc: 'cc1@example.com, cc2@example.com',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.Destination.CcAddresses).toEqual(['cc1@example.com', 'cc2@example.com'])
        })

        it('should include bcc addresses in SES destination', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                bcc: 'bcc@example.com',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.Destination.BccAddresses).toEqual(['bcc@example.com'])
        })

        it('should not include cc/bcc in SES destination when not provided', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.Destination.CcAddresses).toBeUndefined()
            expect(sentCommand.input.Destination.BccAddresses).toBeUndefined()
        })

        it('should not include cc/bcc in SES destination when empty strings', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                cc: '',
                bcc: '  ',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.Destination.CcAddresses).toBeUndefined()
            expect(sentCommand.input.Destination.BccAddresses).toBeUndefined()
        })

        it('should not include replyTo if not in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.ReplyToAddresses).toBeUndefined()
        })

        it('should include single replyTo address if in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                replyTo: 'Customer Service <reply@example.com>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.ReplyToAddresses).toEqual(['Customer Service <reply@example.com>'])
        })

        it('should split multiple comma-separated replyTo addresses', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                replyTo: 'reply1@example.com, reply2@example.com, Customer Service <reply3@example.com>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(sentCommand.input.ReplyToAddresses).toEqual([
                'reply1@example.com',
                'reply2@example.com',
                'Customer Service <reply3@example.com>',
            ])
        })

        it.each([
            ['text only', { html: '', text: 'Hello, this is a plain text email.' }, ['Text']],
            ['html only, no text', { html: '<p>Hello</p>', text: undefined }, ['Html']],
            ['html only, empty text', { html: '<p>Hello</p>', text: '' }, ['Html']],
        ])('sends only the parts that have content: %s', async (_name, content, expectedParts) => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            invocation.queueParameters = CyclotronInvocationQueueParametersEmailSchema.parse(
                createEmailParams({ from: { integrationId: 1 }, ...content })
            )
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            expect(Object.keys(sentCommand.input.Content.Simple.Body)).toEqual(expectedParts)
            if (content.text) {
                expect(sentCommand.input.Content.Simple.Body.Text).toEqual({ Data: content.text, Charset: 'UTF-8' })
            }
        })

        it('should not include preheader span if not in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                html: '<tbody>Test email content</tbody>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const htmlData = sentCommand.input.Content.Simple.Body.Html.Data
            expect(htmlData).not.toContain('<tbody><span')
        })

        it('should include preheader at top of HTML if in params', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                html: '<tbody>Test email content</tbody>',
                preheader: 'This is a preview text',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const htmlData = sentCommand.input.Content.Simple.Body.Html.Data
            expect(htmlData).toMatch(/<tbody><span style=".*">This is a preview text<\/span>/)
        })

        it('should include unsubscribe headers for non-transactional emails', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'marketing' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const headers = sentCommand.input.Content.Simple.Headers
            expect(headers).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ Name: 'List-Unsubscribe' }),
                    expect.objectContaining({ Name: 'List-Unsubscribe-Post' }),
                ])
            )
        })

        it('should not include unsubscribe headers for transactional emails (but tracking-code header is still set)', async () => {
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const headerNames = (sentCommand.input.Content.Simple.Headers ?? []).map((h: { Name: string }) => h.Name)
            expect(headerNames).not.toContain('List-Unsubscribe')
            expect(headerNames).not.toContain('List-Unsubscribe-Post')
            expect(headerNames).toContain('X-PostHog-Tracking-Code')
        })

        it.each(['transactional', 'marketing'])(
            'marks a %s send as auto-generated so autoresponders do not answer it',
            async (categoryType) => {
                // Without this an autoresponder answers the workflow, and when the address it
                // answers is a support inbox the reply re-enters the same workflow as a new ticket.
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.hogFunction.metadata = { message_category_type: categoryType }
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.Content.Simple.Headers).toEqual(
                    expect.arrayContaining([{ Name: 'Auto-Submitted', Value: 'auto-generated' }])
                )
            }
        )

        it('attaches the X-PostHog-Tracking-Code header carrying the full signed code', async () => {
            // The header is the authoritative tracking-code carrier (the EmailTag is the
            // bounded backwards-compat fallback). It rides on every outbound message,
            // regardless of transactional vs. marketing category.
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
            const trackingHeader = sentCommand.input.Content.Simple.Headers.find(
                (h: { Name: string }) => h.Name === 'X-PostHog-Tracking-Code'
            )
            expect(trackingHeader).toBeDefined()
            expect(typeof trackingHeader.Value).toBe('string')
            expect(trackingHeader.Value.length).toBeGreaterThan(0)
            // The SES EmailTag carries a *different* (shorter, unsigned) code so it stays under the
            // 256-char tag-value limit even when distinct_id is long.
            expect(sentCommand.input.EmailTags[0].Value).not.toEqual(trackingHeader.Value)
        })

        describe('per-send tracking gate (tracking_enabled)', () => {
            // Would be tracked if the gate regressed: has an anchor to rewrite and a </body> to pixel.
            const trackableHtml = '<body>Hi! <a href="https://example.com">Click me</a></body>'

            beforeEach(() => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.queueParameters = createEmailParams({ from: { integrationId: 1 }, html: trackableHtml })
                invocation.hogFunction.metadata = { tracking_enabled: false }
            })

            it('skips pixel and link rewriting and uses the untracked configuration set when tracking is off', async () => {
                service['sesConfig'].sesUntrackedConfigurationSet = 'posthog-messaging-untracked'
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.ConfigurationSetName).toEqual('posthog-messaging-untracked')
                expect(sentCommand.input.Content.Simple.Body.Html.Data).toEqual(trackableHtml)
                // Delivery/bounce attribution must survive tracking-off: the untracked configuration
                // set still emits delivery events, and the webhook needs this header to attribute them.
                const headerNames = sentCommand.input.Content.Simple.Headers.map((h: { Name: string }) => h.Name)
                expect(headerNames).toContain('X-PostHog-Tracking-Code')
            })

            it('falls back to the tracked configuration set when no untracked set is configured, still untracked HTML', async () => {
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentCommand = sendEmailSpy.mock.calls[0][0] as { input: any }
                expect(sentCommand.input.ConfigurationSetName).toEqual('posthog-messaging')
                expect(sentCommand.input.Content.Simple.Body.Html.Data).toEqual(trackableHtml)
            })

            it('records an email_untracked app metric for untracked sends but not for test sends', async () => {
                const normal = await service.executeSendEmail(invocation)
                expect(normal.metrics.map((m) => m.metric_name)).toEqual(
                    expect.arrayContaining(['email_sent', 'email_untracked'])
                )

                const testSend = await service.executeSendEmail(invocation, true)
                expect(testSend.metrics).toEqual([])
            })

            it('marks the captured send event as untracked so customer-built engagement rates can exclude it', async () => {
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'shouldCaptureEngagementEvents'
                ).mockResolvedValue(true)
                const result = await service.executeSendEmail(invocation)
                expect(result.capturedPostHogEvents[0].properties).toMatchObject({
                    $email_tracking_enabled: false,
                })
            })
        })

        describe('recipient tracking consent', () => {
            const trackableHtml = '<body>Hi! <a href="https://example.com">Click me</a></body>'

            const setConsentState = (
                mode: 'off' | 'opt_out' | 'opt_in',
                storedConsent: 'OPTED_IN' | 'OPTED_OUT' | null
            ): void => {
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'getEmailTrackingConsentMode'
                ).mockResolvedValue(mode)
                jest.spyOn((service as any).recipientsManager, 'get').mockResolvedValue(
                    storedConsent
                        ? {
                              id: 'pref-1',
                              team_id: team.id,
                              identifier: 'test@example.com',
                              preferences: { $email_tracking: storedConsent },
                              created_at: '',
                              updated_at: '',
                          }
                        : null
                )
            }

            beforeEach(() => {
                sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
                invocation.queueParameters = createEmailParams({ from: { integrationId: 1 }, html: trackableHtml })
                invocation.hogFunction.metadata = { message_category_type: 'marketing' }
            })

            it.each([
                ['off mode ignores consent entirely', 'off', null, true],
                ['opt_out mode tracks recipients with no stored preference', 'opt_out', null, true],
                ['opt_out mode does not track recipients who opted out', 'opt_out', 'OPTED_OUT', false],
                ['opt_in mode does not track recipients with no stored preference', 'opt_in', null, false],
                ['opt_in mode tracks recipients who opted in', 'opt_in', 'OPTED_IN', true],
            ] as [string, 'off' | 'opt_out' | 'opt_in', 'OPTED_IN' | 'OPTED_OUT' | null, boolean][])(
                '%s',
                async (_name, mode, storedConsent, expectTracked) => {
                    setConsentState(mode, storedConsent)
                    const result = await service.executeSendEmail(invocation)
                    expect(result.error).toBeUndefined()
                    const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html
                        .Data
                    if (expectTracked) {
                        // SES sends tag each anchor and let SES report the click, instead of
                        // rewriting the href to a redirect URL. The open pixel is unchanged.
                        expect(sentHtml).toContain('ses:tags="phl:')
                        expect(sentHtml).toContain('ph_id=')
                    } else {
                        expect(sentHtml).toEqual(trackableHtml)
                    }
                }
            )

            it('transactional emails are exempt from consent enforcement', async () => {
                invocation.hogFunction.metadata = { message_category_type: 'transactional' }
                setConsentState('opt_in', null)
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toContain('ses:tags="phl:')
                expect(sentHtml).toContain('ph_id=')
            })

            it('the step-level toggle wins over consent: tracking_enabled false is untracked even for opted-in recipients', async () => {
                invocation.hogFunction.metadata = { message_category_type: 'marketing', tracking_enabled: false }
                setConsentState('opt_in', 'OPTED_IN')
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('sends untracked when the consent lookup fails (fail closed)', async () => {
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'getEmailTrackingConsentMode'
                ).mockResolvedValue('opt_out')
                jest.spyOn((service as any).recipientsManager, 'get').mockRejectedValue(new Error('db down'))
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('sends untracked when the consent-mode lookup fails (fail closed)', async () => {
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'getEmailTrackingConsentMode'
                ).mockRejectedValue(new Error('db down'))
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('honors a cc recipient tracking opt-out for the whole send', async () => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                    html: trackableHtml,
                    cc: 'cc@example.com',
                })
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'getEmailTrackingConsentMode'
                ).mockResolvedValue('opt_out')
                jest.spyOn((service as any).recipientsManager, 'get').mockImplementation(
                    (options: unknown): Promise<any> => {
                        const { identifier } = options as { identifier: string }
                        return Promise.resolve(
                            identifier === 'cc@example.com'
                                ? {
                                      id: 'pref-1',
                                      team_id: team.id,
                                      identifier,
                                      preferences: { $email_tracking: 'OPTED_OUT' },
                                      created_at: '',
                                      updated_at: '',
                                  }
                                : null
                        )
                    }
                )
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = (sendEmailSpy.mock.calls[0][0] as { input: any }).input.Content.Simple.Body.Html.Data
                expect(sentHtml).toEqual(trackableHtml)
            })
        })

        it('should report a missing message id', async () => {
            sendEmailSpy.mockResolvedValue({})
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toMatchInlineSnapshot(`"Failed to send email via SES: No messageId returned from SES"`)
        })

        it('should capture a $workflows_email_sent PostHog event on success', async () => {
            // Engagement capture is team-opt-in; enable it for this team so the captured event is emitted.
            jest.spyOn((service as any).teamWorkflowsConfigService, 'shouldCaptureEngagementEvents').mockResolvedValue(
                true
            )
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            expect(result.capturedPostHogEvents).toHaveLength(1)
            expect(result.capturedPostHogEvents[0]).toMatchObject({
                team_id: team.id,
                distinct_id: 'distinct_id',
                event: '$workflows_email_sent',
                properties: {
                    $workflow_id: invocation.functionId,
                    $workflow_action_id: invocation.state.actionId,
                    $email_to: 'test@example.com',
                    $email_subject: 'Test Subject',
                    $email_tracking_enabled: true,
                },
            })
        })

        it('does not capture a PostHog event when engagement capture is disabled for the team', async () => {
            // Default config has capture_workflows_engagement_events=false, so even on success no event is queued.
            sendEmailSpy.mockResolvedValue({ MessageId: 'test-message-id' })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            expect(result.capturedPostHogEvents).toHaveLength(0)
        })

        it('should capture a $workflows_email_failed PostHog event on failure', async () => {
            jest.spyOn((service as any).teamWorkflowsConfigService, 'shouldCaptureEngagementEvents').mockResolvedValue(
                true
            )
            sendEmailSpy.mockRejectedValue(new Error('SES error'))
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeDefined()
            expect(result.capturedPostHogEvents).toHaveLength(1)
            expect(result.capturedPostHogEvents[0]).toMatchObject({
                event: '$workflows_email_failed',
                distinct_id: 'distinct_id',
            })
        })
    })
})
