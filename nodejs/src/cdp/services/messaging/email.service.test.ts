import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'
import { KafkaConsumer, Message, Metadata, TopicPartitionOffset } from 'node-rdkafka'
import { randomUUID } from 'node:crypto'
import { register } from 'prom-client'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import {
    BucketProxy,
    DeliveredEmail,
    StoredFile,
    attachmentFile,
    deliveredTo,
    sesClientFor,
    uploadAttachment,
} from '~/cdp/_tests/email-delivery-fakes'
import { FakeSes, FakeSesAttachment, FakeSesFault, startFakeSes } from '~/cdp/_tests/fake-ses'
import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { postgresThatDropsConnections } from '~/cdp/_tests/postgres-that-drops-connections'
import { getDefaultCdpConfig } from '~/cdp/config'
import { EMAIL_STATUS_OUTPUT } from '~/cdp/outputs/outputs'
import {
    CdpProducerName,
    WAREHOUSE_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER,
} from '~/cdp/outputs/producers'
import { createCdpOutputsRegistry } from '~/cdp/outputs/registry'
import {
    CyclotronInvocationQueueParametersEmailSchema,
    CyclotronInvocationQueueParametersEmailType,
} from '~/cdp/schema/cyclotron'
import { CyclotronV2DequeuedJob } from '~/cdp/services/cyclotron-v2/types'
import { TRANSACTIONAL_EMAIL_EVENT } from '~/cdp/services/hogflows/hogflow-sensitivity'
import { v2JobToInvocation } from '~/cdp/services/job-queue/job-queue-postgres-v2'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { KAFKA_EMAIL_STATUS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { MESSAGE_ASSETS_OUTPUT } from '~/common/outputs'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { waitForExpect } from '~/tests/helpers/expectations'
import { ensureKafkaTopics } from '~/tests/helpers/kafka'
import { createRecordingIngestionOutputs } from '~/tests/helpers/recording-ingestion-outputs'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { INVALID_TEAM_ID_KEYS } from '~/tests/helpers/team'

import { Hub, Team } from '../../../types'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { WorkflowsActivationReporter } from '../monitoring/workflows-activation-reporter'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { AttachmentStore } from './attachment-store'
import { selectEmailSenderIntegrationId } from './email-sender-selection'
import { EmailStatusService } from './email-status.service'
import { EmailSuppressionService, emailSuppressionConfigFromEnv } from './email-suppression.service'
import {
    EmailService,
    EmailServiceConfig,
    formatMailbox,
    parseAddressList,
    parseTierCaps,
    sanitizeEmailSubject,
    teamEmailCapBucket,
} from './email.service'
import { MailDevAPI, mailDevWebUrl } from './helpers/maildev'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'
import { InFlightRegistry } from './in-flight-registry'
import { MessageAssetsService } from './message-assets.service'
import { RecipientTokensService } from './recipient-tokens.service'

async function metricValue(name: string, labels: Record<string, string>, metricName = name): Promise<number> {
    const metric = await register.getSingleMetric(name)!.get()
    const values: { labels: Partial<Record<string, string | number>>; value: number; metricName?: string }[] =
        metric.values
    const sample = values.find(
        (value) =>
            (value.metricName ?? name) === metricName &&
            Object.entries(labels).every(([key, labelValue]) => value.labels[key] === labelValue)
    )
    return sample?.value ?? 0
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

describe('formatMailbox', () => {
    it.each([
        ['no name', undefined, 'a@example.com'],
        ['an empty name', '  ', 'a@example.com'],
        ['a plain name', 'Dry Run', '"Dry Run" <a@example.com>'],
        ['an apostrophe and ampersand', "O'Brien & Co", `"O'Brien & Co" <a@example.com>`],
        ['a double quote', 'The "Real" Dry', '"The \\"Real\\" Dry" <a@example.com>'],
        ['a backslash', 'Dry\\Run', '"Dry\\\\Run" <a@example.com>'],
        [
            'a line break that would start a header',
            'Dry\r\nBcc: x@example.com',
            '"DryBcc: x@example.com" <a@example.com>',
        ],
        [
            'a non-ASCII name as an RFC 2047 encoded word',
            'Café Müller',
            '=?UTF-8?Q?Caf=C3=A9_M=C3=BCller?= <a@example.com>',
        ],
    ])('formats %s', (_name, name, expected) => {
        expect(formatMailbox(name, 'a@example.com')).toEqual(expected)
    })

    it.each([
        ['CJK name with a character outside the emoji range', '株式会社山田商事部𠮷田'.repeat(4)],
        ['emoji name', 'Launch party 🎉🚀 '.repeat(5)],
    ])('keeps a long %s intact across encoded words', (_desc, name) => {
        const [displayName, address] = formatMailbox(name, 'a@example.com').split(' <')
        const encodedWords = displayName.split(' ')

        expect(encodedWords.map(decodeEncodedWord).join('')).toEqual(name.trim())
        expect(address).toEqual('a@example.com>')
        expect(encodedWords.length).toBeGreaterThan(1)
        expect(Math.max(...encodedWords.map((word) => word.length))).toBeLessThanOrEqual(75)
    })
})

function decodeEncodedWord(word: string): string {
    const [, encoding, text] = word.match(/^=\?UTF-8\?([BQ])\?(.*)\?=$/i)!
    const bytes =
        encoding.toUpperCase() === 'B'
            ? Buffer.from(text, 'base64')
            : Buffer.from(
                  text
                      .replace(/_/g, ' ')
                      .replace(/=([0-9A-F]{2})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16))),
                  'latin1'
              )
    return bytes.toString('utf8')
}

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
const oneRetryAfter = (delayMs: number): any => {
    const token = (retries: number): { getRetryCount: () => number; getRetryDelay: () => number } => ({
        getRetryCount: () => retries,
        getRetryDelay: () => delayMs,
    })
    return {
        acquireInitialRetryToken: () => Promise.resolve(token(0)),
        refreshRetryTokenForRetry: (previous: ReturnType<typeof token>) =>
            previous.getRetryCount() > 0 ? Promise.reject(new Error('no retries left')) : Promise.resolve(token(1)),
        recordSuccess: () => {},
    }
}

describe('EmailService', () => {
    let service: EmailService
    let hub: Hub
    let team: Team
    let workflowsActivationReporter: WorkflowsActivationReporter
    let activationEvents: { teamId: number; event: string; properties: Record<string, unknown> }[]
    let ses: FakeSes
    const createService = (
        config: Partial<EmailServiceConfig> = {},
        limiters: { workflowEmailRateLimiter?: RateLimiterService; teamEmailRateLimiter?: RateLimiterService } = {},
        collaborators: {
            attachmentStore?: AttachmentStore
            teamConfigDb?: PostgresRouter
            emailStatusService?: EmailStatusService
        } = {}
    ): EmailService =>
        new EmailService(
            {
                sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                sesRegion: hub.SES_REGION,
                sesEndpoint: hub.SES_ENDPOINT,
                sesTrackedConfigurationSet: hub.SES_TRACKED_CONFIGURATION_SET,
                sesUntrackedConfigurationSet: hub.SES_UNTRACKED_CONFIGURATION_SET,
                ...config,
            },
            hub.integrationManager,
            new TeamWorkflowsConfigService(collaborators.teamConfigDb ?? hub.postgres, hub.pubSub),
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
            new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv()),
            new RecipientsManagerService(hub.postgres),
            collaborators.emailStatusService ?? null,
            workflowsActivationReporter,
            undefined,
            limiters.workflowEmailRateLimiter ?? null,
            limiters.teamEmailRateLimiter ?? null,
            collaborators.attachmentStore ?? null
        )
    // The limiter's script reads the time from Redis, which a test cannot freeze. This client answers
    // TIME from Date.now instead, so a test that freezes Date.now also stops the bucket's refill.
    const limiterTimeCall = "redis.call('TIME')"
    const onTestClock = (redis: RedisV2): RedisV2 => ({
        ...redis,
        useClient: (options, callback) =>
            redis.useClient(options, (client) =>
                callback(
                    new Proxy(client, {
                        get: (target, property, receiver) =>
                            property === 'eval'
                                ? (script: string, ...args: [number, ...string[]]) => {
                                      if (!script.includes(limiterTimeCall)) {
                                          throw new Error('The limiter script no longer reads the time from Redis')
                                      }
                                      const nowMs = Date.now()
                                      const time = `{'${Math.floor(nowMs / 1000)}', '${(nowMs % 1000) * 1000}'}`
                                      return target.eval(script.replace(limiterTimeCall, time), ...args)
                                  }
                                : Reflect.get(target, property, receiver),
                    })
                )
            ),
    })
    let limiterRedis: RedisV2 | undefined
    const createRateLimiter = (name: string): RateLimiterService => {
        limiterRedis ??= createRedisV2PoolFromConfig({
            connection: hub.CDP_REDIS_HOST
                ? {
                      url: hub.CDP_REDIS_HOST,
                      options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
        return new RateLimiterService(onTestClock(limiterRedis), { name })
    }
    const unreachableValkey: RedisV2 = {
        useClient: () => Promise.reject(new Error('connect ECONNREFUSED')),
        usePipeline: () => Promise.reject(new Error('connect ECONNREFUSED')),
    }
    const sendsLeftInTheTeamBudget = async (sender: EmailService): Promise<number> => {
        for (let sent = 0; sent < 3; sent++) {
            const another = createExampleInvocation({ team_id: team.id, id: new UUIDT().toString() })
            another.state.vmState = { stack: [] } as any
            another.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                to: { email: `${randomUUID()}@example.com`, name: 'Another Recipient' },
            })
            if (!(await sender.executeSendEmail(another)).finished) {
                return sent
            }
        }
        throw new Error('the team budget did not run out')
    }
    const settledActivationEvents = async (): Promise<typeof activationEvents> => {
        await new Promise((resolve) => setImmediate(resolve))
        return activationEvents
    }
    beforeEach(async () => {
        hub = await createHub({})
        ses = await startFakeSes({
            [hub.SES_TRACKED_CONFIGURATION_SET]: { tracking: true },
            [hub.SES_UNTRACKED_CONFIGURATION_SET]: { tracking: false },
        })
        hub.SES_ENDPOINT = ses.endpoint
        team = (await createTestTeamFixture(hub.postgres)).team
        integrationIdBase = team.id
        await hub.teamManager.getTeam(team.id)
        activationEvents = []
        workflowsActivationReporter = new WorkflowsActivationReporter(
            hub.teamManager,
            (capturedTeam, event, properties = {}) => {
                activationEvents.push({ teamId: capturedTeam.id, event, properties })
            }
        )
        service = createService()
        mockFetch.mockClear()
    })
    afterEach(async () => {
        await ses.close()
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
                new RecipientsManagerService(hub.postgres),
                null,
                workflowsActivationReporter
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
            invocation.queueMetadata = { originQueue: 'hogflow', originPriority: 2 }
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
            it.each([
                ['a workflow send', true, false, 1],
                ['a workflow test send', true, true, 0],
                ['a hog function send', false, false, 0],
            ])(
                'should fail on an unverified email domain and report it only for a real workflow send: %s',
                async (_name, fromWorkflow, isTest, reports) => {
                    invocation.queueParameters = createEmailParams({
                        from: { integrationId: 2 },
                    })
                    const sentInvocation = fromWorkflow
                        ? { ...invocation, hogFlow: new FixtureHogFlowBuilder().withTeamId(team.id).build() }
                        : invocation
                    const result = await service.executeSendEmail(sentInvocation, isTest)
                    expect(result.error).toMatchInlineSnapshot(
                        `"The selected email integration domain is not verified"`
                    )
                    expect(await settledActivationEvents()).toEqual(
                        Array(reports).fill({
                            teamId: team.id,
                            event: 'workflows send failed',
                            properties: {
                                reason: 'unverified_domain',
                                channel: 'email',
                                workflow_id: invocation.functionId,
                            },
                        })
                    )
                }
            )
            it.each([
                ['unsupported', 'Email delivery mode not supported'],
                [
                    'mailjet',
                    "The sender's email provider is not recognized. Select a different sender in the workflow's email step.",
                ],
            ])('fails the send and reports email_failed when the provider is %s', async (provider, error) => {
                await insertIntegration(hub.postgres, team.id, {
                    id: getIntegrationId(4),
                    kind: 'email',
                    config: {
                        email: 'test@posthog.com',
                        name: 'Test User',
                        domain: 'posthog.com',
                        verified: true,
                        provider,
                    },
                })
                invocation.queueParameters = createEmailParams({ from: { integrationId: 4 } })

                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBe(error)
                expect(result.metrics.map((metric) => metric.metric_name)).toEqual(['email_failed'])
                expect(ses.sent).toEqual([])
            })
            it.each([
                { budget: 'workflow', workflowLimit: true, teamCap: false },
                { budget: 'team', workflowLimit: false, teamCap: true },
            ])(
                'fails an unrecognized provider without spending the $budget sending budget',
                async ({ workflowLimit, teamCap }) => {
                    await insertIntegration(hub.postgres, team.id, {
                        id: getIntegrationId(4),
                        kind: 'email',
                        config: {
                            email: 'test@posthog.com',
                            name: 'Test User',
                            domain: 'posthog.com',
                            verified: true,
                            provider: 'mailjet',
                        },
                    })
                    const limitedService = createService(
                        { teamEmailCapMode: teamCap ? 'enforce' : 'off', teamEmailTierDailyCaps: [1] },
                        {
                            workflowEmailRateLimiter: createRateLimiter('unknown-provider-workflow-budget-test'),
                            teamEmailRateLimiter: createRateLimiter('unknown-provider-team-budget-test'),
                        }
                    )
                    if (workflowLimit) {
                        invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 1, period: 'hour' } }
                    }

                    invocation.queueParameters = createEmailParams({ from: { integrationId: 4 } })
                    const failed = await limitedService.executeSendEmail(invocation)
                    invocation.queueParameters = createEmailParams({ from: { integrationId: 1 } })
                    const sent = await limitedService.executeSendEmail(invocation)

                    expect(failed.error).toBe(
                        "The sender's email provider is not recognized. Select a different sender in the workflow's email step."
                    )
                    expect(sent.finished).toBe(true)
                    expect(sent.error).toBeUndefined()
                    expect(sent.metrics.map((metric) => metric.metric_name)).toContain('email_sent')
                    expect(ses.sent.map((message) => message.from)).toEqual(['"Test User" <test@posthog.com>'])
                }
            )
            it('should send identical from and feedback forwarding args', async () => {
                // This test is important for spam classification - feedback forwarding email MUST match from email
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(ses.sent).toHaveLength(1)
                const [sent] = ses.sent
                expect(sent.from).toBe('"Test User" <test@posthog.com>')
                expect(sent.feedbackForwardingAddress).toBe('test@posthog.com')
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
                const [sent] = ses.sent
                expect(sent.from).toBe('"Second Sender" <second@posthog.com>')
                expect(result.logs.map((log) => log.message)).toContain(
                    'Email sent to test@example.com from Second Sender <second@posthog.com>'
                )
            })
        })
        describe('from overrides', () => {
            const maxLengthEmail = `${'a'.repeat(242)}@posthog.com`

            it.each<[string, { email?: string; name?: string }, string, string]>([
                [
                    'address on the verified domain',
                    { email: 'community@posthog.com' },
                    '"Test User" <community@posthog.com>',
                    'community@posthog.com',
                ],
                [
                    'address at the maximum length',
                    { email: maxLengthEmail },
                    `"Test User" <${maxLengthEmail}>`,
                    maxLengthEmail,
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
                    'name with quotes, angle brackets and a line break kept inside the quoted name',
                    { name: '"Evil" <fake@evil.com>,\r\n Bcc:\\' },
                    '"\\"Evil\\" <fake@evil.com>, Bcc:\\\\" <test@posthog.com>',
                    'test@posthog.com',
                ],
                [
                    'non-ASCII name with quotes as an RFC 2047 encoded word',
                    { name: 'Café "Müller"' },
                    '=?UTF-8?Q?Caf=C3=A9_=22M=C3=BCller=22?= <test@posthog.com>',
                    'test@posthog.com',
                ],
            ])('applies the %s', async (_desc, fromOverride, expectedFrom, expectedFeedback) => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, ...fromOverride },
                })
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const [sent] = ses.sent
                expect(sent.from).toBe(expectedFrom)
                expect(sent.feedbackForwardingAddress).toBe(expectedFeedback)
            })

            it.each<[string, string, string?]>([
                ['an address on an unverified domain', 'someone@evil.com'],
                ['an address on a subdomain of the verified domain', 'someone@sub.posthog.com'],
                ['a list of addresses', 'a@posthog.com, b@posthog.com'],
                ['an RFC-822 formatted address', '"Name" <a@posthog.com>'],
                ['a value that is not an email address', 'not-an-email'],
                [
                    'an address longer than the maximum length',
                    `${'a'.repeat(243)}@posthog.com`,
                    '254 characters or fewer',
                ],
                ['an overlong value that is not an email address', 'a'.repeat(255), '254 characters or fewer'],
            ])('discards %s and sends from the integration sender', async (_desc, email, expectedWarning = email) => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1, email },
                })
                const result = await service.executeSendEmail(invocation)
                // Failing the send would break every step still carrying the placeholder address
                // an old sender picker wrote, so an unusable override degrades to the integration's
                // own sender. The unverified address must never reach the provider either way.
                expect(result.error).toBeUndefined()
                const [sent] = ses.sent
                expect(sent.from).toBe('"Test User" <test@posthog.com>')
                expect(result.logs.some((log) => log.level === 'warn' && log.message.includes(expectedWarning))).toBe(
                    true
                )
            })
        })
        describe('email sending', () => {
            it('should send an email', async () => {
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                expect(ses.sent).toEqual([
                    expect.objectContaining({
                        from: '"Test User" <test@posthog.com>',
                        feedbackForwardingAddress: 'test@posthog.com',
                        to: ['"Test User" <test@example.com>'],
                        subject: 'Test Subject',
                        text: 'Test Text',
                    }),
                ])
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
            // The SDK retries a throttle by itself before it gives up, so SES throttles every attempt here.
            const tooManyRequests: FakeSesFault = {
                status: 429,
                type: 'TooManyRequestsException',
                message: 'Too many requests',
            }
            const throttleCases: Array<[string, FakeSesFault]> = [
                ['TooManyRequestsException', tooManyRequests],
                ['ThrottlingException', { status: 400, type: 'ThrottlingException', message: 'Rate exceeded' }],
            ]
            it.each(throttleCases)('reschedules instead of failing when SES returns %s', async (_name, fault) => {
                ses.failWith(fault)
                // Only the clock is frozen, so the SDK still waits between its own retries,
                // and the reschedule lands exactly the jittered 500 to 1000ms past `now`.
                const now = Date.now()
                const clock = jest.spyOn(Date, 'now').mockReturnValue(now)
                const result = await service.executeSendEmail(invocation).finally(() => clock.mockRestore())

                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(now + 500)
                expect(scheduledMs).toBeLessThan(now + 1000)
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                expect(result.invocation.queueMetadata).toEqual(invocation.queueMetadata)
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
                ses.failWith(tooManyRequests)

                const result = await service.executeSendEmail(invocation)

                expect(result.finished).toBe(false)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                expect(result.invocation.queuePriority).toBe(1)
            })

            it('hard-fails (not retry) when SES returns SendingPausedException', async () => {
                // Reputation/account-state pause won't recover in 500ms; retrying
                // just burns reschedules. Hard-fail so the failure surfaces via
                // email_failed and an operator can investigate.
                ses.failWith({ status: 400, type: 'SendingPausedException', message: 'Sending paused' })

                const result = await service.executeSendEmail(invocation)

                expect(result.finished).toBe(true)
                expect(result.error).toMatch(/Failed to send email via SES: Sending paused/)
                expect(result.metrics).toEqual(
                    expect.arrayContaining([expect.objectContaining({ metric_name: 'email_failed' })])
                )
            })

            it.each<[string, string, FakeSesFault]>([
                ...throttleCases.map(([name, fault]): [string, string, FakeSesFault] => [name, 'throttled', fault]),
                [
                    'SendingPausedException',
                    'SendingPausedException',
                    { status: 400, type: 'SendingPausedException', message: 'Sending paused' },
                ],
                ['a dropped connection', 'other', 'drop-connection'],
            ])('counts an SES send that fails with %s as %s', async (_name, expectedResult, fault) => {
                const labels = { result: expectedResult }
                const before = await metricValue('cdp_ses_send_results_total', labels)
                ses.failWith(fault)

                await service.executeSendEmail(invocation)

                expect(await metricValue('cdp_ses_send_results_total', labels)).toBe(before + 1)
            })

            it('still fails the job for non-throttle SES errors', async () => {
                ses.failWith({ status: 400, type: 'MessageRejected', message: 'something else broke' })

                const result = await service.executeSendEmail(invocation)

                expect(result.finished).toBe(true)
                expect(result.error).toMatch(/Failed to send email via SES: something else broke/)
                // Business metric should record the failure.
                expect(result.metrics).toEqual(
                    expect.arrayContaining([expect.objectContaining({ metric_name: 'email_failed' })])
                )
            })
        })

        describe('queue-to-send latency', () => {
            // The job was created a minute ago and rescheduled after a throttle, so it became due again 5 seconds ago.
            // Running the email step clones the invocation, which resets queueScheduledAt before the send.
            const transactionalSend = (): void => {
                invocation.state.globals.event.event = '$transactional_email'
                invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            }

            it.each([
                ['workflow', 'bulk', 'false', 'its rescheduled time', (): void => {}, 5_000, 60_000],
                ['transactional_api', 'fast', 'false', 'its creation', transactionalSend, 60_000, Infinity],
                // Alerts leave out a wait that the team sending cap causes on purpose.
                [
                    'transactional_api',
                    'fast',
                    'true',
                    'its creation after a team cap delay',
                    (): void => {
                        transactionalSend()
                        invocation.queueMetadata = { teamCapped: true }
                    },
                    60_000,
                    Infinity,
                ],
            ])(
                'observes the wait of a retried %s send on the %s lane with team_capped=%s from %s',
                async (source, priorityClass, teamCapped, _from, setUp, minWaitMs, maxWaitMs) => {
                    setUp()
                    invocation.queue = 'email'
                    invocation.queueCreatedAt = DateTime.utc().minus({ seconds: 60 })
                    invocation.queueDueAt = DateTime.utc().minus({ seconds: 5 })
                    invocation.queueScheduledAt = undefined
                    const name = 'cdp_email_queue_to_send_ms'
                    const labels = { source, priority_class: priorityClass, team_capped: teamCapped }
                    const countBefore = await metricValue(name, labels, `${name}_count`)
                    const sumBefore = await metricValue(name, labels, `${name}_sum`)

                    await service.executeSendEmail(invocation)

                    expect(await metricValue(name, labels, `${name}_count`)).toBe(countBefore + 1)
                    const waitMs = (await metricValue(name, labels, `${name}_sum`)) - sumBefore
                    expect(waitMs).toBeGreaterThanOrEqual(minWaitMs)
                    expect(waitMs).toBeLessThan(maxWaitMs)
                }
            )
        })

        describe('workflow sending rate limit', () => {
            let limitedService: EmailService

            beforeEach(() => {
                limitedService = createService(
                    {},
                    { workflowEmailRateLimiter: createRateLimiter('workflow-email-rate-test') }
                )
            })

            const limitTo = (count: number, period: 'minute' | 'hour'): void => {
                invocation.hogFunction.metadata = { email_sending_rate_limit: { count, period } }
            }

            type TimedSend = {
                result: Awaited<ReturnType<EmailService['executeSendEmail']>>
                before: number
                after: number
            }

            const timedSend = async (
                send: () => ReturnType<EmailService['executeSendEmail']> = () =>
                    limitedService.executeSendEmail(invocation)
            ): Promise<TimedSend> => {
                const before = Date.now()
                const result = await send()
                return { result, before, after: Date.now() }
            }

            const sendUntilDenied = async (): Promise<TimedSend> => {
                for (let attempt = 0; attempt < 5; attempt++) {
                    const send = await timedSend()
                    if (!send.result.finished) {
                        return send
                    }
                }
                throw new Error('The workflow sending limit never denied a send')
            }

            const parkedAt = (send: TimedSend): number => send.result.invocation.queueScheduledAt!.toMillis()

            let frozenClock: jest.SpyInstance | undefined
            const freezeClock = (): void => {
                frozenClock = jest.spyOn(Date, 'now').mockReturnValue(Date.now())
            }

            afterEach(() => {
                frozenClock?.mockRestore()
                frozenClock = undefined
            })

            it('reschedules a denied send with its email payload and no business metric', async () => {
                freezeClock()
                limitTo(30, 'minute')

                const denied = await sendUntilDenied()
                const { result } = denied

                expect(ses.sent).toHaveLength(1)
                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                // The reschedule must carry the email payload forward: without queueParameters the
                // retry has nothing to send and the throttled email is dropped rather than delayed.
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                expect(result.invocation.queueMetadata).toEqual(invocation.queueMetadata)
                expect(parkedAt(denied)).toBeGreaterThan(denied.before)
                expect(parkedAt(denied)).toBeLessThanOrEqual(denied.after + 2000)
                expect(result.metrics ?? []).toEqual([])
            })

            it.each([
                ['2s slots at 30 a minute', 30, 2000],
                ['sub-second slots at 120 a minute', 120, 500],
            ])('parks consecutive denials exactly one slot apart: %s', async (_name, count, slotMs) => {
                freezeClock()
                limitTo(count, 'minute')

                const first = await sendUntilDenied()
                const next = [await timedSend(), await timedSend()]

                next.forEach((denied, index) => {
                    expect(denied.result.finished).toBe(false)
                    const driftMs = parkedAt(denied) - parkedAt(first) - (index + 1) * slotMs
                    const callMs = first.after - first.before + (denied.after - denied.before)
                    expect(Math.abs(driftMs)).toBeLessThanOrEqual(callMs + 1)
                })
            })

            it('scatters a backlog that overflows the reservation horizon', async () => {
                limitTo(1, 'hour')
                await sendUntilDenied()

                const parks: number[] = []
                for (let i = 0; i < 20; i++) {
                    const denied = await timedSend()
                    expect(denied.result.finished).toBe(false)
                    expect(parkedAt(denied)).toBeGreaterThanOrEqual(denied.before + 60 * 60 * 1000)
                    expect(parkedAt(denied)).toBeLessThanOrEqual(denied.after + 2 * 60 * 60 * 1000)
                    parks.push(parkedAt(denied))
                }

                expect(Math.max(...parks) - Math.min(...parks)).toBeGreaterThan(10 * 60 * 1000)
            })

            it('retries on the clamped token interval when the limiter cannot be reached', async () => {
                limitedService = createService(
                    {},
                    { workflowEmailRateLimiter: new RateLimiterService(unreachableValkey, { name: 'unreachable' }) }
                )
                limitTo(120, 'minute')

                const denied = await timedSend()

                expect(ses.sent).toEqual([])
                expect(denied.result.finished).toBe(false)
                expect(parkedAt(denied)).toBeGreaterThanOrEqual(denied.before + 1000)
                expect(parkedAt(denied)).toBeLessThanOrEqual(denied.after + 2000)
            })

            it('sends a burst of one second of budget, then parks only the workflow over its limit', async () => {
                freezeClock()
                limitTo(61, 'minute')

                const burst = [await timedSend(), await timedSend()]
                const denied = await timedSend()

                expect(burst.map((send) => send.result.finished)).toEqual([true, true])
                expect(denied.result.finished).toBe(false)
                expect(parkedAt(denied)).toBeLessThanOrEqual(denied.after + 1000)

                const otherWorkflow = createExampleInvocation({ team_id: team.id, id: 'function-2' })
                otherWorkflow.state.vmState = { stack: [] } as any
                otherWorkflow.queueParameters = createEmailParams({ from: { integrationId: 1 } })
                otherWorkflow.hogFunction.metadata = invocation.hogFunction.metadata
                const other = await limitedService.executeSendEmail(otherWorkflow)

                expect(other.finished).toBe(true)
                expect(ses.sent).toHaveLength(3)
            })

            it.each([
                ['no rate limit is configured', (): void => void (invocation.hogFunction.metadata = {})],
                [
                    'the configured value is malformed',
                    (): void =>
                        void (invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 'lots' } }),
                ],
            ])('sends without pacing when %s', async (_name, setup) => {
                setup()

                const results = [
                    await limitedService.executeSendEmail(invocation),
                    await limitedService.executeSendEmail(invocation),
                ]

                expect(results.map((result) => [result.finished, result.error])).toEqual([
                    [true, undefined],
                    [true, undefined],
                ])
                expect(ses.sent).toHaveLength(2)
            })

            it('skips the limit for test sends', async () => {
                limitTo(1, 'minute')
                await sendUntilDenied()

                const testSend = await timedSend(() => limitedService.executeSendEmail(invocation, true))

                expect(testSend.result.finished).toBe(true)
                expect(ses.sent).toHaveLength(2)
            })
        })

        // A workflow over its sending limit must not crowd out anyone else: every denied
        // send parks on its own future slot instead of retrying every second, and a
        // workflow without a limit keeps sending right past the parked backlog.
        describe('a denied backlog cannot crowd out other sends', () => {
            it('spreads denied sends over distinct future slots and leaves unlimited workflows untouched', async () => {
                const realLimitedService = createService(
                    {},
                    { workflowEmailRateLimiter: createRateLimiter('workflow-email-backlog-test') }
                )

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
                expect(ses.sent).toHaveLength(2)
            })
        })

        describe('parseTierCaps', () => {
            it.each([
                ['a whole table', '50,200', [50, 200]],
                // A decimal cap would make a claim fractional, and the limiter floors its grant
                // while the caller compares against the unfloored request. The claim then charges
                // the bucket and reads back as a denial, which starves the team on every retry.
                ['a decimal cap', '50,2.5', []],
                ['a zero cap', '50,0', []],
                ['nonsense', 'fifty', []],
            ])('%s', (_name, value, expected) => {
                expect(parseTierCaps(value)).toEqual(expected)
            })
        })

        describe('team sending cap (enforce mode)', () => {
            let limiter: RateLimiterService

            beforeEach(() => {
                limiter = createRateLimiter('team-email-cap-test')
            })

            afterEach(() => {
                jest.restoreAllMocks()
            })

            // A team without a workflows config row is on tier 0, so its cap is the first entry.
            const createCappedService = (dailyCap: number, teamLimiter = limiter): EmailService =>
                createService(
                    { teamEmailCapMode: 'enforce', teamEmailTierDailyCaps: [dailyCap] },
                    { teamEmailRateLimiter: teamLimiter }
                )

            const drainTeamCap = async (teamId: number, dailyCap: number, tokensLeft = 0): Promise<void> => {
                const bucket = teamEmailCapBucket(teamId, dailyCap)
                await limiter.claimUpTo({ ...bucket, requested: dailyCap - tokensLeft })
            }

            it.each([
                ['parks exactly on a reserved slot', 200, 432_000, 432_000],
                ['spreads an overflow wake across the horizon', 10, 60 * 60 * 1000, 2 * 60 * 60 * 1000],
            ])('%s', async (_name, dailyCap, minMs, maxMs) => {
                const cappedService = createCappedService(dailyCap)
                const drainedAt = Date.now()
                await drainTeamCap(team.id, dailyCap)

                const result = await cappedService.executeSendEmail(invocation)
                const after = Date.now()

                expect(ses.sent).toEqual([])
                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(false)
                // The reschedule must carry the email payload forward, same as the workflow limit.
                expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                // The flag labels the eventual send's queue wait, so alerts can leave out the cap delay.
                expect(result.invocation.queueMetadata).toEqual({ ...invocation.queueMetadata, teamCapped: true })
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(drainedAt + minMs)
                expect(scheduledMs).toBeLessThanOrEqual(after + maxMs)
                // A real denial names the cap it hit, which is what makes the limiter-fault case
                // below distinguishable to the customer reading the run's logs.
                expect(result.logs.map((log) => log.message).join(' ')).toContain('reached its email sending limit of')
            })

            describe('a job the previous release rescheduled', () => {
                it.each([
                    ['a team cap delay', { originQueue: 'hogflow', originPriority: 2, teamCapped: true }],
                    [
                        'a failed suppression lookup',
                        { originQueue: 'hogflow', originPriority: 2, suppressionLookupAttempts: 1 },
                    ],
                    ['an SES throttle', { originQueue: 'hogflow', originPriority: 2 }],
                ])(
                    'is charged to the team budget and sent after %s',
                    async (_name, queueMetadataWrittenByThePreviousRelease) => {
                        const sender = createCappedService(2)
                        const storedByThePreviousRelease = Buffer.from(
                            JSON.stringify({
                                state: invocation.state,
                                queueParameters: invocation.queueParameters,
                                queueMetadata: queueMetadataWrittenByThePreviousRelease,
                            })
                        )
                        const dequeued = v2JobToInvocation({
                            id: invocation.id,
                            teamId: invocation.teamId,
                            functionId: invocation.functionId,
                            queueName: 'email',
                            priority: 0,
                            scheduled: DateTime.now(),
                            created: DateTime.now(),
                            parentRunId: null,
                            transitionCount: 1,
                            state: storedByThePreviousRelease,
                            distinctId: null,
                            personId: null,
                            actionId: null,
                            cancelRequestedAt: null,
                        } as unknown as CyclotronV2DequeuedJob)

                        const result = await sender.executeSendEmail({
                            ...invocation,
                            queueParameters:
                                dequeued.queueParameters as CyclotronJobInvocationHogFunction['queueParameters'],
                            queueMetadata: dequeued.queueMetadata,
                        })

                        expect(result.error).toBeUndefined()
                        expect(result.finished).toBe(true)
                        expect(deliveredTo(ses, 'test@example.com')).toHaveLength(1)
                        expect(await sendsLeftInTheTeamBudget(sender)).toBe(1)
                    }
                )
            })

            it('retries on the token bucket cadence when the limiter cannot be reached', async () => {
                // An unreachable Valkey denies with no horizon. Parking on the daily cap's pacing
                // interval would hold the email long after the limiter recovered.
                jest.spyOn(Math, 'random').mockReturnValue(0)
                const cappedService = createCappedService(
                    200,
                    new RateLimiterService(unreachableValkey, { name: 'unreachable' })
                )

                const before = Date.now()
                const result = await cappedService.executeSendEmail(invocation)
                const after = Date.now()

                expect(ses.sent).toEqual([])
                expect(result.finished).toBe(false)
                const scheduledMs = result.invocation.queueScheduledAt!.toMillis()
                expect(scheduledMs).toBeGreaterThanOrEqual(before + 5 * 60 * 1000)
                expect(scheduledMs).toBeLessThanOrEqual(after + 5 * 60 * 1000)
                // No cap was reached, so the customer must not be told they hit one.
                const messages = result.logs.map((log) => log.message).join(' ')
                expect(messages).not.toContain('reached its email sending limit')
                expect(messages).toContain("Could not check this project's email sending limit")
            })

            it('sends while the team has budget left', async () => {
                const result = await createCappedService(200).executeSendEmail(invocation)

                expect(result.finished).toBe(true)
                expect(ses.sent).toHaveLength(1)
            })

            // A team over its tier cap must not slow anyone else down: its denied sends get
            // their own future slots instead of all waking together, and another team's send
            // goes straight out.
            it('spreads a capped team over distinct slots while another team keeps sending', async () => {
                const dailyCap = 8640
                const enforcedService = createCappedService(dailyCap)

                // Drain the capped team's bucket so every send below is a denial. The
                // 0.1 tokens/s refill makes the slot spacing 10s, far above test wall-clock.
                await drainTeamCap(team.id, dailyCap)

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
                expect(ses.sent).toHaveLength(1)
            })

            it('charges a transactional send against the bucket without delaying it', async () => {
                const dailyCap = 50
                const enforcedService = createCappedService(dailyCap)
                const sendFor = (id: string, transactional: boolean): CyclotronJobInvocationHogFunction => {
                    const next = createExampleInvocation({ team_id: team.id, id: `function-${id}` })
                    next.id = `invocation-${id}`
                    next.state.vmState = { stack: [] } as any
                    next.queueParameters = createEmailParams({ from: { integrationId: 1 } })
                    if (transactional) {
                        next.hogFunction.metadata = { message_category_type: 'transactional' }
                    }
                    return next
                }

                // Leave one token, so the next send can show the charge before the cap closes.
                await drainTeamCap(team.id, dailyCap, 1)

                // The charge: this send takes the last token rather than riding past the bucket.
                const charged = await enforcedService.executeSendEmail(sendFor('charged', true))
                expect(charged.finished).toBe(true)
                expect(ses.sent).toHaveLength(1)

                // Control: the cap really is closed now, so a marketing send parks.
                const marketing = await enforcedService.executeSendEmail(sendFor('marketing', false))
                expect(marketing.finished).toBe(false)
                expect(ses.sent).toHaveLength(1)

                // The exemption: a transactional send still goes out against the closed cap.
                const transactional = await enforcedService.executeSendEmail(sendFor('transactional', true))
                expect(transactional.finished).toBe(true)
                expect(transactional.invocation.queueScheduledAt).toBeUndefined()
                expect(ses.sent).toHaveLength(2)
                expect(transactional.logs.map((log) => log.message).join(' ')).not.toContain(
                    'reached its email sending limit'
                )
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
        it.each([
            ['a plain recipient name', 'Test User'],
            ['a non-ASCII recipient name', 'Café "Müller"'],
        ])('should send an email to %s', async (_desc, recipientName) => {
            invocation.queueParameters = createEmailParams({
                to: { email: 'test@example.com', name: recipientName },
            })
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
                to: [{ address: 'test@example.com', name: recipientName }],
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
                /^<body>Hi! <a href="http:\/\/localhost:8010\/public\/m\/redirect\?ph_id=[A-Za-z0-9._-]+&ph_sig=[A-Za-z0-9_-]+&target=https%3A%2F%2Fexample\.com">Click me<\/a><img src="http:\/\/localhost:8010\/public\/m\/pixel\?ph_id=[A-Za-z0-9._-]+" style="display: none;" \/><\/body>$/
            )
        })
    })
    describe('native email sending with ses', () => {
        let invocation: CyclotronJobInvocationHogFunction
        const captureEngagementEvents = async (): Promise<void> => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO workflows_teamworkflowsconfig
                    (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                     email_sending_suspension_reason, ses_tenant_sending_status, email_sending_tier)
                 VALUES ($1, true, 'off', '', '', 0)
                 ON CONFLICT (team_id) DO UPDATE SET capture_workflows_engagement_events = true`,
                [team.id],
                'test-capture-engagement-events'
            )
        }
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
        })

        it('should error if not verified', async () => {
            ses.failWith({
                status: 400,
                type: 'MessageRejected',
                message: 'Email address not verified "Test User" <test@posthog-test.com>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toEqual(
                'Failed to send email via SES: Email address not verified "Test User" <test@posthog-test.com>'
            )
        })

        it.each([
            ['an ordinary template', {}, '$pageview', { ph_id: expect.stringMatching(/^[A-Za-z0-9_-]+$/) }],
            [
                'a sensitive template',
                { sensitive: true },
                '$pageview',
                { ph_id: expect.stringMatching(/^[A-Za-z0-9_-]+$/), ph_sensitive: 'true' },
            ],
            [
                'a transactional email run',
                {},
                TRANSACTIONAL_EMAIL_EVENT,
                { ph_id: expect.stringMatching(/^[A-Za-z0-9_-]+$/), ph_email_status: 'true' },
            ],
        ])('should send an email if verified, for %s', async (_name, extraMetadata, triggerEvent, expectedTags) => {
            invocation.hogFunction.metadata = { message_category_type: 'transactional', ...extraMetadata }
            invocation.state.globals.event.event = triggerEvent
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            expect(result.emailSendResult).toEqual({ status: 'accepted' })
            // The SES tag carries the short unsigned code (no dot); the signed code (with distinct_id)
            // rides in the header.
            expect(ses.sent).toEqual([
                expect.objectContaining({
                    configurationSet: 'posthog-messaging',
                    html: 'Test HTML',
                    text: 'Test Text',
                    subject: 'Test Subject',
                    charsets: { subject: 'UTF-8', text: 'UTF-8', html: 'UTF-8' },
                    to: ['"Test User" <test@example.com>'],
                    tags: expectedTags,
                    feedbackForwardingAddress: 'test@posthog-test.com',
                    from: '"Test User" <test@posthog-test.com>',
                }),
            ])
        })

        const sesAccepts = (): void => {}
        const sesRejects = (): void => {
            ses.failWith({ status: 400, type: 'MessageRejected', message: 'SES error' })
        }
        const teamSuspended = (): void => {
            sesAccepts()
            jest.spyOn(service['teamWorkflowsConfigService'], 'getEmailSendingSuspension').mockResolvedValue('staff')
        }
        const workflowPaused = (): void => {
            sesAccepts()
            invocation.hogFunction.metadata = { email_sending_paused_at: '2026-01-01T00:00:00Z' }
        }
        const recipientMissing = (): void => {
            sesAccepts()
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                to: { email: '', name: 'Test User' },
            })
        }
        const recipientSuppressed = (): void => {
            sesAccepts()
            jest.spyOn(service['emailSuppressionService'], 'isSuppressed').mockResolvedValue(true)
        }
        describe('attachments', () => {
            let bucket: BucketProxy
            let pdf: StoredFile
            let logo: StoredFile
            let recipient: string
            let emailStatus: EmailStatusService
            let statusProducer: KafkaProducerWrapper
            let statusReader: KafkaConsumer
            let statusOffsetsBeforeSend: TopicPartitionOffset[]

            const send = (files: StoredFile[], integrationId = 1): void => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId },
                    to: { email: recipient, name: 'Test User' },
                    attachments: files.map((file) => file.metadata),
                })
            }
            const sender = ({
                teamDailyCap,
                teamConfigDb,
                attachmentSendDeadlineMs,
            }: {
                teamDailyCap?: number
                teamConfigDb?: PostgresRouter
                attachmentSendDeadlineMs?: number
            } = {}): EmailService =>
                createService(
                    {
                        ...(teamDailyCap
                            ? { teamEmailCapMode: 'enforce', teamEmailTierDailyCaps: [teamDailyCap] }
                            : {}),
                        attachmentSendDeadlineMs,
                    },
                    {
                        workflowEmailRateLimiter: createRateLimiter('workflow-email-test'),
                        teamEmailRateLimiter: createRateLimiter('team-email-test'),
                    },
                    { attachmentStore: bucket.store(), teamConfigDb, emailStatusService: emailStatus }
                )
            const sesThrottles: FakeSesFault = {
                status: 429,
                type: 'TooManyRequestsException',
                message: 'Maximum sending rate exceeded.',
            }
            const sendAsTransactionalEmail = (): void => {
                invocation.id = new UUIDT().toString()
                invocation.state.globals.event.event = TRANSACTIONAL_EMAIL_EVENT
            }
            const statusTopicEndOffsets = async (): Promise<TopicPartitionOffset[]> => {
                const metadata = await new Promise<Metadata>((resolve, reject) =>
                    statusReader.getMetadata({ topic: KAFKA_EMAIL_STATUS, timeout: 10_000 }, (error, data) =>
                        error ? reject(error) : resolve(data)
                    )
                )
                const partitions = metadata.topics.find((topic) => topic.name === KAFKA_EMAIL_STATUS)!.partitions
                return await Promise.all(
                    partitions.map(
                        ({ id: partition }) =>
                            new Promise<TopicPartitionOffset>((resolve, reject) =>
                                statusReader.queryWatermarkOffsets(
                                    KAFKA_EMAIL_STATUS,
                                    partition,
                                    10_000,
                                    (error, offsets) =>
                                        error
                                            ? reject(error)
                                            : resolve({
                                                  topic: KAFKA_EMAIL_STATUS,
                                                  partition,
                                                  offset: offsets.highOffset,
                                              })
                                )
                            )
                    )
                )
            }
            const recordedEmailStatuses = async (): Promise<Record<string, any>[]> => {
                await emailStatus.flush()
                await statusProducer.flush()
                const endOffsets = await statusTopicEndOffsets()
                const nextOffsets = new Map(statusOffsetsBeforeSend.map(({ partition, offset }) => [partition, offset]))
                const consumed: Message[] = []
                const deadline = Date.now() + 10_000
                statusReader.assign(statusOffsetsBeforeSend)
                try {
                    while (endOffsets.some(({ partition, offset }) => (nextOffsets.get(partition) ?? 0) < offset)) {
                        if (Date.now() > deadline) {
                            throw new Error(`email status rows up to ${JSON.stringify(endOffsets)} never arrived`)
                        }
                        const batch = await new Promise<Message[]>((resolve, reject) =>
                            statusReader.consume(100, (error, messages) => (error ? reject(error) : resolve(messages)))
                        )
                        for (const message of batch) {
                            nextOffsets.set(message.partition, message.offset + 1)
                            consumed.push(message)
                        }
                    }
                } finally {
                    statusReader.unassign()
                }
                return consumed
                    .map((message) => parseJSON(message.value!.toString()) as Record<string, any>)
                    .filter((row) => row.message_id === invocation.id)
            }
            const failedEmailStatus = (reason: string): Record<string, any> =>
                expect.objectContaining({
                    team_id: team.id,
                    message_id: invocation.id,
                    status: 'failed',
                    reason,
                    sending_domain: 'posthog-test.com',
                })
            const deliveredFiles = [
                () => ({
                    filename: 'report.pdf',
                    contentType: 'application/pdf',
                    contentId: undefined,
                    inline: false,
                    bytes: pdf.bytes,
                }),
                () => ({
                    filename: 'logo.png',
                    contentType: 'image/png',
                    contentId: 'logo',
                    inline: true,
                    bytes: logo.bytes,
                }),
            ]
            const maildevDelivered = async (): Promise<DeliveredEmail[]> => {
                const { fetch: get } = jest.requireActual('~/common/utils/request')
                const emails: any[] = await (await get(`${mailDevWebUrl}/email`)).json()
                const bytesOf = async (emailId: string, attachment: any): Promise<Buffer> =>
                    Buffer.from(
                        await (
                            await get(`${mailDevWebUrl}/email/${emailId}/attachment/${attachment.generatedFileName}`)
                        ).text()
                    )
                return await Promise.all(
                    emails
                        .filter((email) => email.to.some((to: { address: string }) => to.address === recipient))
                        .map(async (email) => ({
                            to: email.to.map((to: { address: string }) => to.address),
                            attachments: await Promise.all(
                                (email.attachments ?? []).map(async (attachment: any) => ({
                                    filename: attachment.fileName,
                                    contentType: attachment.contentType,
                                    contentId:
                                        attachment.contentDisposition === 'inline' ? attachment.contentId : undefined,
                                    inline: attachment.contentDisposition === 'inline',
                                    bytes: await bytesOf(email.id, attachment),
                                }))
                            ),
                        }))
                )
            }
            const untilDue = async (due: DateTime): Promise<void> => {
                await new Promise((resolve) => setTimeout(resolve, Math.max(0, due.toMillis() - Date.now() + 50)))
            }

            beforeAll(async () => {
                await ensureKafkaTopics([KAFKA_EMAIL_STATUS])
            })
            beforeEach(async () => {
                bucket = await BucketProxy.start()
                statusProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
                statusReader = new KafkaConsumer(
                    {
                        'group.id': `email-status-reader-${randomUUID()}`,
                        'metadata.broker.list': hub.KAFKA_HOSTS,
                        'enable.auto.commit': false,
                    },
                    {}
                )
                await new Promise((resolve, reject) =>
                    statusReader.connect({}, (error, data) => (error ? reject(error) : resolve(data)))
                )
                statusReader.setDefaultConsumeTimeout(100)
                statusOffsetsBeforeSend = await statusTopicEndOffsets()
                const cdpConfig = getDefaultCdpConfig()
                emailStatus = new EmailStatusService(
                    createCdpOutputsRegistry().build(
                        new KafkaProducerRegistry<CdpProducerName>({
                            [WARPSTREAM_INGESTION_PRODUCER]: statusProducer,
                            [WARPSTREAM_CYCLOTRON_PRODUCER]: statusProducer,
                            [WAREHOUSE_PRODUCER]: statusProducer,
                        }),
                        cdpConfig
                    ),
                    cdpConfig,
                    10_000
                )
                recipient = `${randomUUID()}@example.com`
                pdf = await uploadAttachment(team.id, { filename: 'report.pdf', contentType: 'application/pdf' })
                logo = await uploadAttachment(team.id, {
                    filename: 'logo.png',
                    contentType: 'image/png',
                    contentId: 'logo',
                })
                send([pdf, logo])
            })
            afterEach(async () => {
                await bucket.close()
                await statusProducer.disconnect()
                await new Promise((resolve, reject) =>
                    statusReader.disconnect((error, data) => (error ? reject(error) : resolve(data)))
                )
            })

            it.each([
                ['through SES', 'ses', null],
                ['through SES on the retry after SES throttled the first try', 'ses', 'sesThrottles'],
                ['through SES on the retry after the bucket failed the first try', 'ses', 'bucketRefuses'],
                ['through maildev', 'maildev', null],
            ])('delivers the stored files as attachments %s', async (_name, provider, firstTryFault) => {
                if (provider === 'maildev') {
                    await insertIntegration(hub.postgres, team.id, {
                        id: getIntegrationId(2),
                        kind: 'email',
                        config: {
                            email: 'test@posthog-test.com',
                            name: 'Test User',
                            domain: 'posthog-test.com',
                            verified: true,
                            provider: 'maildev',
                        },
                    })
                    send([pdf, logo], 2)
                }
                const emailService = sender()
                ses.failWith(firstTryFault === 'sesThrottles' ? sesThrottles : null)
                bucket.answer = firstTryFault === 'bucketRefuses' ? 'refuse' : 'pass'

                let result = await emailService.executeSendEmail(invocation)
                if (firstTryFault) {
                    expect(result.finished).toBe(false)
                    expect(result.error).toBeUndefined()
                    expect(result.invocation.queueScheduledAt!.toMillis()).toBeGreaterThan(Date.now())
                    ses.failWith(null)
                    bucket.answer = 'pass'
                    result = await emailService.executeSendEmail(result.invocation)
                }

                expect(result.error).toBeUndefined()
                expect(result.finished).toBe(true)
                const delivered =
                    provider === 'ses'
                        ? deliveredTo(ses, recipient)
                        : await waitForExpect(async () => {
                              const emails = await maildevDelivered()
                              expect(emails).toHaveLength(1)
                              return emails
                          })
                const inFilenameOrder = (files: FakeSesAttachment[]): FakeSesAttachment[] =>
                    [...files].sort((a, b) => a.filename.localeCompare(b.filename))
                expect(
                    delivered.map((email) => ({ ...email, attachments: inFilenameOrder(email.attachments) }))
                ).toEqual([
                    {
                        to: [expect.stringContaining(recipient)],
                        attachments: inFilenameOrder(deliveredFiles.map((file) => file())),
                    },
                ])
            })

            describe('team budget across load retries', () => {
                it.each([
                    ['charged it', false],
                    ['could not look up the tier', true],
                ])('charges it once when the first try %s', async (_name, tierLookupFails) => {
                    let firstTry = true
                    const teamConfigDb = await postgresThatDropsConnections(
                        hub.DATABASE_URL,
                        () => firstTry && tierLookupFails
                    )
                    const emailService = sender({ teamDailyCap: 2, teamConfigDb: teamConfigDb.postgres })
                    bucket.answer = 'refuse'

                    const retried = await emailService.executeSendEmail(invocation)
                    firstTry = false
                    bucket.answer = 'pass'
                    const result = await emailService.executeSendEmail(retried.invocation)
                    await teamConfigDb.close()

                    expect(retried.finished).toBe(false)
                    expect(result.error).toBeUndefined()
                    expect(result.finished).toBe(true)
                    expect(deliveredTo(ses, recipient)).toHaveLength(1)
                    expect(await sendsLeftInTheTeamBudget(emailService)).toBe(1)
                })

                it('keeps a retry that pacing denies queued with its budget paid, and sends it once pacing lets it', async () => {
                    const emailService = sender({ teamDailyCap: 2 })
                    invocation.hogFunction.metadata = { email_sending_rate_limit: { count: 30, period: 'minute' } }
                    bucket.answer = 'refuse'

                    const retried = await emailService.executeSendEmail(invocation)
                    bucket.answer = 'pass'
                    const paced = await emailService.executeSendEmail(retried.invocation)
                    expect(paced.finished).toBe(false)
                    expect(paced.invocation.queueScheduledAt!.toMillis()).toBeGreaterThan(Date.now())
                    await untilDue(paced.invocation.queueScheduledAt!)
                    const result = await emailService.executeSendEmail(paced.invocation)

                    expect(deliveredTo(ses, recipient)).toEqual([
                        { to: [expect.stringContaining(recipient)], attachments: deliveredFiles.map((file) => file()) },
                    ])
                    expect(result.error).toBeUndefined()
                    expect(result.finished).toBe(true)
                    expect(await sendsLeftInTheTeamBudget(emailService)).toBe(1)
                })
            })

            it.each([
                ['was never uploaded', () => Promise.resolve(attachmentFile())],
                ['belongs to another team', async () => await uploadAttachment(team.id + 1, { filename: 'a.pdf' })],
            ])(
                'fails as attachments_missing, sends nothing and stops the other downloads when a file %s',
                async (_name, otherFile) => {
                    sendAsTransactionalEmail()
                    send([pdf, await otherFile()])
                    bucket.answer = 'holdFilesItHas'

                    const result = await sender().executeSendEmail(invocation)

                    expect(result).toMatchObject({
                        finished: true,
                        error: expect.stringMatching(/^attachments_missing: /),
                    })
                    expect(ses.sent).toEqual([])
                    expect(await recordedEmailStatuses()).toEqual([failedEmailStatus('attachments_missing')])
                    await waitForExpect(() => expect(bucket.abandonedRequests).toBe(1), 3000)
                }
            )

            const inOneAdmission = async <T>(sends: () => Promise<T>): Promise<T> => {
                const registry = new InFlightRegistry({
                    budgetBytes: Number.MAX_SAFE_INTEGER,
                    heapLimitBytes: Number.MAX_SAFE_INTEGER,
                    maxInFlight: 1,
                })
                const admission = registry.tryStart(pdf.bytes.length, sends)
                return await (admission as Extract<typeof admission, { started: unknown }>).started
            }
            const outcomeOf = (result: Awaited<ReturnType<EmailService['executeSendEmail']>>) => ({
                finished: result.finished,
                error: result.error,
                retryLater: (result.invocation.queueScheduledAt?.toMillis() ?? 0) > Date.now(),
            })
            const sent = { finished: true, error: undefined, retryLater: false }
            const retriedLoad = { finished: false, error: undefined, retryLater: true }

            it('when a flow sends its next email inline after the email before abandoned a download mid-body, it loads its files and sends', async () => {
                const emailService = sender({ attachmentSendDeadlineMs: 2_000 })
                bucket.answer = 'stallFileBodies'

                const { first, second } = await inOneAdmission(async () => {
                    send([pdf, attachmentFile()])
                    const first = await emailService.executeSendEmail(invocation)
                    bucket.answer = 'pass'
                    send([pdf, logo])
                    return { first, second: await emailService.executeSendEmail(invocation) }
                })

                expect(first.error).toMatch(/^attachments_missing: /)
                await waitForExpect(() => expect(bucket.abandonedRequests).toBe(1), 3000)
                expect(outcomeOf(second)).toEqual(sent)
                expect(deliveredTo(ses, recipient)).toEqual([
                    { to: [expect.stringContaining(recipient)], attachments: deliveredFiles.map((file) => file()) },
                ])
            })

            it.each([
                [
                    'loads its files and sends only once that call settles',
                    true,
                    3_000,
                    sent,
                    () => [
                        { to: [expect.stringContaining(recipient)], attachments: deliveredFiles.map((file) => file()) },
                    ],
                ],
                ['reschedules as a load retry once its deadline passes', false, 1_000, retriedLoad, () => []],
            ])(
                'when a flow sends its next email inline while the SES call of the email before still waits for its credentials, it %s',
                async (_name, credentialsArrive, attachmentSendDeadlineMs, expected, inbox) => {
                    const emailService = sender({ attachmentSendDeadlineMs })
                    let giveCredentials!: () => void
                    const credentials = new Promise<{ accessKeyId: string; secretAccessKey: string }>((resolve) => {
                        giveCredentials = () =>
                            resolve({ accessKeyId: 'AKIDEXAMPLE', secretAccessKey: 'example-secret' })
                    })
                    emailService.sesV2Client = sesClientFor(ses, { credentials: () => credentials })

                    const { first, second } = await inOneAdmission(async () => {
                        const first = await emailService.executeSendEmail(invocation)
                        bucket.answer = 'refuse'
                        if (credentialsArrive) {
                            setTimeout(() => {
                                bucket.answer = 'pass'
                                giveCredentials()
                            }, 300)
                        }
                        return { first, second: await emailService.executeSendEmail(invocation) }
                    })

                    expect(outcomeOf(first)).toEqual(retriedLoad)
                    expect(outcomeOf(second)).toEqual(expected)
                    expect(deliveredTo(ses, recipient)).toEqual(inbox())
                }
            )

            it.each([
                [
                    'the bucket does not answer',
                    () => {
                        bucket.answer = 'hold'
                    },
                ],
                [
                    'the SES client never gets its credentials',
                    (emailService: EmailService) => {
                        emailService.sesV2Client = sesClientFor(ses, {
                            credentials: () => new Promise<never>(() => {}),
                        })
                    },
                ],
                [
                    'SES refuses with a throttle and the SDK is still backing off',
                    (emailService: EmailService) => {
                        ses.failWith(sesThrottles)
                        emailService.sesV2Client = sesClientFor(ses, { retryStrategy: oneRetryAfter(2_000) })
                    },
                ],
            ])(
                'when %s past the deadline, retries the send later and delivers it with its files once',
                async (_name, fault) => {
                    const emailService = sender({ attachmentSendDeadlineMs: 1000 })
                    const ownClient = emailService.sesV2Client
                    fault(emailService)

                    const retry = await emailService.executeSendEmail(invocation)
                    expect({
                        finished: retry.finished,
                        error: retry.error,
                        retryLater: retry.invocation.queueScheduledAt!.toMillis() > Date.now(),
                        delivered: deliveredTo(ses, recipient),
                    }).toEqual({ finished: false, error: undefined, retryLater: true, delivered: [] })

                    bucket.answer = 'pass'
                    ses.failWith(null)
                    emailService.sesV2Client = ownClient
                    const result = await emailService.executeSendEmail(retry.invocation)

                    expect(result.error).toBeUndefined()
                    expect(result.finished).toBe(true)
                    expect(deliveredTo(ses, recipient)).toEqual([
                        { to: [expect.stringContaining(recipient)], attachments: deliveredFiles.map((file) => file()) },
                    ])
                }
            )

            it.each([
                [
                    'SES receives the request and does not answer',
                    () => {
                        ses.failWith('no-answer')
                    },
                ],
                [
                    'SES answers 200 and its body stalls',
                    () => {
                        ses.failWith('stalled-body')
                    },
                ],
                [
                    'the connection drops after the request went out and the SDK is still backing off',
                    (emailService: EmailService) => {
                        ses.failWith('drop-connection')
                        emailService.sesV2Client = sesClientFor(ses, { retryStrategy: oneRetryAfter(2_000) })
                    },
                ],
            ])(
                'when %s past the deadline, fails the send without a retry, because SES may have sent it',
                async (_name, fault) => {
                    const emailService = sender({ attachmentSendDeadlineMs: 1000 })
                    fault(emailService)

                    const result = await emailService.executeSendEmail(invocation)

                    expect({
                        finished: result.finished,
                        error: result.error,
                        failed: result.metrics.some((metric) => metric.metric_name === 'email_failed'),
                        delivered: deliveredTo(ses, recipient),
                    }).toEqual({
                        finished: true,
                        error: expect.stringMatching(/^Failed to send email via SES: /),
                        failed: true,
                        delivered: [],
                    })
                }
            )

            it.each([
                [9, false, 'retries once more', false, undefined, null],
                [
                    10,
                    false,
                    'fails as attachment_unavailable',
                    true,
                    expect.stringMatching(/^attachment_unavailable: /),
                    'attachment_unavailable',
                ],
                [
                    0,
                    true,
                    'fails a test send at once as attachment_unavailable',
                    true,
                    expect.stringMatching(/^attachment_unavailable: .* in 1 try,/),
                    null,
                ],
            ])(
                'after %s load retries (test send: %s), %s when the bucket still does not answer',
                async (retriesSoFar, isTest, _outcome, finished, error, failedStatusReason) => {
                    sendAsTransactionalEmail()
                    invocation.queueMetadata = { attachmentLoadRetries: retriesSoFar }
                    bucket.answer = 'refuse'

                    const result = await sender().executeSendEmail(invocation, isTest)

                    expect(result.finished).toBe(finished)
                    expect(result.error).toEqual(error)
                    expect(ses.sent).toEqual([])
                    expect(await recordedEmailStatuses()).toEqual(
                        failedStatusReason ? [failedEmailStatus(failedStatusReason)] : []
                    )
                }
            )

            it('counts the load retries across reschedules and fails the send on the 11th try', async () => {
                const emailService = sender()
                bucket.answer = 'refuse'

                let result = await emailService.executeSendEmail(invocation)
                let tries = 1
                while (!result.finished && tries < 20) {
                    result = await emailService.executeSendEmail(result.invocation)
                    tries++
                }

                expect({ tries, finished: result.finished, error: result.error }).toEqual({
                    tries: 11,
                    finished: true,
                    error: expect.stringMatching(/^attachment_unavailable: .* in 11 tries,/),
                })
                expect(ses.sent).toEqual([])
            })

            it.each([
                ['$workflows_email_sent', null],
                [
                    '$workflows_email_failed',
                    { status: 400, type: 'MessageRejected', message: 'Email address is not verified.' },
                ],
            ] as const)('counts the files and their bytes on %s', async (event, sesFault) => {
                await captureEngagementEvents()
                ses.failWith(sesFault)

                const result = await sender().executeSendEmail(invocation)

                expect(result.capturedPostHogEvents).toEqual([
                    expect.objectContaining({
                        event,
                        properties: expect.objectContaining({
                            $email_attachment_count: 2,
                            $email_attachment_bytes: pdf.bytes.length + logo.bytes.length,
                        }),
                    }),
                ])
            })
        })

        it.each([
            ['a transactional email that SES accepts', TRANSACTIONAL_EMAIL_EVENT, false, sesAccepts, 'sent', ''],
            [
                'a transactional email that SES rejects',
                TRANSACTIONAL_EMAIL_EVENT,
                false,
                sesRejects,
                'failed',
                'provider_error',
            ],
            [
                'a transactional email skipped for a suspended team',
                TRANSACTIONAL_EMAIL_EVENT,
                false,
                teamSuspended,
                'failed',
                'sending_suspended',
            ],
            [
                'a transactional email skipped for a paused workflow',
                TRANSACTIONAL_EMAIL_EVENT,
                false,
                workflowPaused,
                'failed',
                'sending_paused',
            ],
            [
                'a transactional email skipped for a missing recipient',
                TRANSACTIONAL_EMAIL_EVENT,
                false,
                recipientMissing,
                'failed',
                'missing_recipient',
            ],
            [
                'a transactional email skipped for a suppressed recipient',
                TRANSACTIONAL_EMAIL_EVENT,
                false,
                recipientSuppressed,
                'failed',
                'recipient_suppressed',
            ],
            ['a test send of a transactional email', TRANSACTIONAL_EMAIL_EVENT, true, sesAccepts, null, null],
            [
                'a skipped test send of a transactional email',
                TRANSACTIONAL_EMAIL_EVENT,
                true,
                teamSuspended,
                null,
                null,
            ],
            ['a workflow email that SES accepts', '$pageview', false, sesAccepts, null, null],
            ['a workflow email that SES rejects', '$pageview', false, sesRejects, null, null],
            ['a skipped workflow email', '$pageview', false, recipientSuppressed, null, null],
        ])('records the status of %s', async (_name, triggerEvent, isTest, setup, status, reason) => {
            const kafka = createRecordingIngestionOutputs([EMAIL_STATUS_OUTPUT])
            const emailStatusService = new EmailStatusService(kafka.outputs, { EMAIL_STATUS_ENABLED: true })
            service['emailStatusService'] = emailStatusService
            invocation.id = new UUIDT().toString()
            invocation.state.globals.event.event = triggerEvent
            setup()

            await service.executeSendEmail(invocation, isTest)
            await emailStatusService.flush()

            const rows = kafka.produced(EMAIL_STATUS_OUTPUT)
            const sendingDomain = status === 'sent' || reason === 'provider_error' ? 'posthog-test.com' : ''
            expect(rows).toEqual(
                status
                    ? [
                          expect.objectContaining({
                              team_id: team.id,
                              message_id: invocation.id,
                              status,
                              reason,
                              sending_domain: sendingDomain,
                          }),
                      ]
                    : []
            )
        })

        it('records a send-time metric for normal sends but not for test sends', async () => {
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

                const result = await service.executeSendEmail(invocation)

                expect(isSuppressedSpy).toHaveBeenCalled()
                expect(ses.sent).toEqual([])
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_suppressed')
                expect(result.metrics.map((m) => m.metric_name)).not.toContain('email_sent')
            })

            it('moves the first deliverable cc address to To when the To address is suppressed', async () => {
                const suppressed = new Set(['test@example.com', 'cc-bounced@example.com', 'bcc-bounced@example.com'])
                jest.spyOn(service['emailSuppressionService'], 'isSuppressed').mockImplementation((_teamId, email) =>
                    Promise.resolve(suppressed.has(email))
                )
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                    cc: '"Bounced" <cc-bounced@example.com>, cc-1@example.com, cc-2@example.com',
                    bcc: 'bcc-bounced@example.com',
                })

                const result = await service.executeSendEmail(invocation)

                const [sent] = ses.sent
                expect(sent).toMatchObject({ to: ['cc-1@example.com'], cc: ['cc-2@example.com'], bcc: undefined })
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_sent')
                expect(result.logs.map((l) => l.message).join(' ')).toContain(
                    'test@example.com, cc-bounced@example.com, bcc-bounced@example.com'
                )
            })

            it.each([
                { isTest: false, priorAttempts: undefined, attempt: 1, minDelayMs: 30_000, maxDelayMs: 60_000 },
                { isTest: false, priorAttempts: 3, attempt: 4, minDelayMs: 240_000, maxDelayMs: 480_000 },
                { isTest: false, priorAttempts: 20, attempt: 21, minDelayMs: 3_600_000, maxDelayMs: 3_600_000 },
                { isTest: true, priorAttempts: undefined, attempt: undefined, minDelayMs: 0, maxDelayMs: 0 },
            ])(
                'holds or fails the email when the suppression list cannot be read (isTest: $isTest, prior attempts: $priorAttempts)',
                async ({ isTest, priorAttempts, attempt, minDelayMs, maxDelayMs }) => {
                    const query = hub.postgres.query.bind(hub.postgres)
                    jest.spyOn(hub.postgres, 'query').mockImplementation((target, sql, values, tag) =>
                        tag === 'loadSuppressed'
                            ? Promise.reject(new Error('column "hard_bounced_at" does not exist'))
                            : query(target, sql, values, tag)
                    )
                    const held = { ...invocation, queueMetadata: { suppressionLookupAttempts: priorAttempts } }

                    const before = Date.now()
                    const result = await service.executeSendEmail(held, isTest)
                    const after = Date.now()

                    expect(ses.sent).toEqual([])
                    expect(result.metrics).toEqual([])
                    if (isTest) {
                        expect(result.finished).toBe(true)
                        expect(result.error).toBe('Could not check the suppression list')
                        return
                    }
                    expect(result.error).toBeUndefined()
                    expect(result.finished).toBe(false)
                    expect(result.invocation.queueMetadata?.suppressionLookupAttempts).toBe(attempt)
                    expect(result.invocation.queueScheduledAt!.toMillis()).toBeGreaterThanOrEqual(before + minDelayMs)
                    expect(result.invocation.queueScheduledAt!.toMillis()).toBeLessThanOrEqual(after + maxDelayMs)
                    expect(result.invocation.queueParameters).toEqual(invocation.queueParameters)
                }
            )

            it('calls SES when the recipient is not suppressed', async () => {
                jest.spyOn(service['emailSuppressionService'], 'isSuppressed').mockResolvedValue(false)

                const result = await service.executeSendEmail(invocation)

                expect(ses.sent).toHaveLength(1)
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_sent')
            })
        })

        // A person without an email property renders an empty `to`. Counting that as email_failed
        // lets one project's data trip the platform send failure rate alert.
        it.each([
            ['an empty string', ''],
            ['only whitespace', '   '],
            ['no value', undefined],
        ])('skips the send without SES or email_failed when the recipient is %s', async (_label, email) => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                to: { email: email as string, name: 'Test User' },
            })

            const result = await service.executeSendEmail(invocation)

            expect(ses.sent).toEqual([])
            expect(result.error).toBeUndefined()
            expect(result.metrics.map((m) => m.metric_name)).toEqual(['email_missing_recipient'])
            expect(result.skipped).toBe(true)
            expect(result.emailSendResult).toEqual({
                status: 'skipped',
                reason: expect.stringContaining('the recipient has no email address'),
            })
            expect(invocation.state.vmState?.stack).toEqual([{ success: false }])
        })

        it.each([
            ['a workflow send', true, false, 1],
            ['a workflow test send', true, true, 0],
            ['a hog function send', false, false, 0],
        ])(
            'reports a missing recipient as a blocked send only for a real workflow send: %s',
            async (_name, fromWorkflow, isTest, reports) => {
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                    to: { email: '', name: 'Test User' },
                })
                const sentInvocation = fromWorkflow
                    ? { ...invocation, hogFlow: new FixtureHogFlowBuilder().withTeamId(team.id).build() }
                    : invocation

                await service.executeSendEmail(sentInvocation, isTest)

                expect(await settledActivationEvents()).toEqual(
                    Array(reports).fill({
                        teamId: team.id,
                        event: 'workflows send blocked',
                        properties: {
                            reason: 'missing_recipient',
                            channel: 'email',
                            workflow_id: invocation.functionId,
                        },
                    })
                )
            }
        )

        describe('SES tenant attribution', () => {
            it('attributes the send to the team tenant', async () => {
                const result = await service.executeSendEmail(invocation)

                expect(result.error).toBeUndefined()
                const [sent] = ses.sent
                expect(sent.tenant).toEqual(`team-${team.id}`)
            })

            it('attributes test-panel sends too — they are real SES sends', async () => {
                const result = await service.executeSendEmail(invocation, true)

                expect(result.error).toBeUndefined()
                const [sent] = ses.sent
                expect(sent.tenant).toEqual(`team-${team.id}`)
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

                const result = await service.executeSendEmail(invocation)

                expect(ses.sent).toEqual([])
                expect(result.metrics.map((m) => m.metric_name)).toEqual(['email_suspended'])
                expect(result.emailSendResult).toEqual({
                    status: 'skipped',
                    reason: 'Skipping send: email sending is suspended for this project. Contact support to get sending re-enabled.',
                })
                expect(invocation.state.vmState?.stack).toEqual([{ success: false }])
            })

            it('blocks editor test sends while suspended without recording metrics', async () => {
                await suspendTeam()

                const result = await service.executeSendEmail(invocation, true)

                expect(ses.sent).toEqual([])
                expect(result.metrics).toEqual([])
            })

            // A per-workflow pause holds one workflow's email while the rest of the project keeps
            // sending. Same choke point as the team switch above, so no upstream route bypasses it.
            it('does not call SES while the workflow is paused and records email_paused', async () => {
                invocation.hogFunction.metadata = {
                    email_sending_paused_at: '2026-01-01T00:00:00Z',
                    email_sending_paused_reason: 'Spam complaints reached 2% of the 400 emails sent.',
                }

                const result = await service.executeSendEmail(invocation)

                expect(ses.sent).toEqual([])
                expect(result.metrics.map((m) => m.metric_name)).toEqual(['email_paused'])
                expect(result.emailSendResult?.status).toBe('skipped')
                expect(result.emailSendResult?.reason).toContain('Resume it from the workflow page')
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

                const result = await service.executeSendEmail(invocation)

                expect(ses.sent).toEqual([])
                const messages = result.logs.map((l) => l.message).join(' ')
                expect(messages).toContain('Contact support')
                expect(messages).not.toContain('Resume it from the workflow page')
            })

            it('blocks editor test sends while the workflow is paused without recording metrics', async () => {
                invocation.hogFunction.metadata = { email_sending_paused_at: '2026-01-01T00:00:00Z' }

                const result = await service.executeSendEmail(invocation, true)

                expect(ses.sent).toEqual([])
                expect(result.metrics).toEqual([])
            })

            it('sends once the workflow pause is cleared', async () => {
                invocation.hogFunction.metadata = {
                    email_sending_paused_at: null,
                    email_sending_paused_reason: null,
                }

                const result = await service.executeSendEmail(invocation)

                expect(ses.sent).toHaveLength(1)
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
                await setProviderTenantStatus(status as string)

                const result = await service.executeSendEmail(invocation)

                expect(ses.sent).toHaveLength(sesCalls as number)
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

            // The suspension check fails open. A load that throws would therefore let a suspended team send.
            it.each(INVALID_TEAM_ID_KEYS)(
                'keeps a suspended team blocked when invalid team id %p shares its config load',
                async (key) => {
                    await suspendTeam()
                    const configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)

                    const [suspension, invalidTeamConfig] = await Promise.all([
                        configService.getEmailSendingSuspension(team.id),
                        configService.get(key as unknown as number),
                    ])

                    expect(suspension).toEqual('staff')
                    expect(invalidTeamConfig).toMatchObject({ email_sending_suspended: false })
                }
            )

            it('fails open when the suspension lookup errors', async () => {
                // The config lookup rejecting must never block a legitimate send. Rejects once:
                // the suspension check is the first config read; later reads use the real loader.
                jest.spyOn(service['teamWorkflowsConfigService'], 'get').mockRejectedValueOnce(new Error('pg down'))

                const result = await service.executeSendEmail(invocation)

                expect(ses.sent).toHaveLength(1)
                expect(result.metrics.map((m) => m.metric_name)).toContain('email_sent')
            })
        })

        it('should include cc addresses in SES destination', async () => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                cc: 'cc1@example.com, cc2@example.com',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent.cc).toEqual(['cc1@example.com', 'cc2@example.com'])
        })

        it('should include bcc addresses in SES destination', async () => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                bcc: 'bcc@example.com',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent.bcc).toEqual(['bcc@example.com'])
        })

        it('should not include cc/bcc in SES destination when not provided', async () => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent.cc).toBeUndefined()
            expect(sent.bcc).toBeUndefined()
        })

        it('should not include cc/bcc in SES destination when empty strings', async () => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                cc: '',
                bcc: '  ',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent.cc).toBeUndefined()
            expect(sent.bcc).toBeUndefined()
        })

        it('should not include replyTo if not in params', async () => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent.replyTo).toBeUndefined()
        })

        it('should include single replyTo address if in params', async () => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                replyTo: 'Customer Service <reply@example.com>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent.replyTo).toEqual(['Customer Service <reply@example.com>'])
        })

        it('should split multiple comma-separated replyTo addresses', async () => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                replyTo: 'reply1@example.com, reply2@example.com, Customer Service <reply3@example.com>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent.replyTo).toEqual([
                'reply1@example.com',
                'reply2@example.com',
                'Customer Service <reply3@example.com>',
            ])
        })

        it.each([
            ['uses the sender default when the step has none', undefined, ['support@posthog-test.com']],
            ['uses the sender default when the step has no parsed addresses', ' , ', ['support@posthog-test.com']],
            ['keeps the step reply-to over the sender default', 'step@example.com', ['step@example.com']],
        ])('%s', async (_, replyTo, expected) => {
            await insertIntegration(hub.postgres, team.id, {
                id: getIntegrationId(2),
                kind: 'email',
                config: {
                    email: 'sender@posthog-test.com',
                    name: 'Test User',
                    domain: 'posthog-test.com',
                    verified: true,
                    provider: 'ses',
                    reply_to: 'support@posthog-test.com',
                },
            })
            invocation.queueParameters = createEmailParams({ from: { integrationId: 2 }, replyTo })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent.replyTo).toEqual(expected)
        })

        it.each([
            [
                'text only',
                { html: '', text: 'Hello, this is a plain text email.' },
                { text: 'Hello, this is a plain text email.', html: undefined },
            ],
            [
                'html only, no text',
                { html: '<p>Hello</p>', text: undefined },
                { text: undefined, html: expect.any(String) },
            ],
            [
                'html only, empty text',
                { html: '<p>Hello</p>', text: '' },
                { text: undefined, html: expect.any(String) },
            ],
        ])('sends only the parts that have content: %s', async (_name, content, expectedParts) => {
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            invocation.queueParameters = CyclotronInvocationQueueParametersEmailSchema.parse(
                createEmailParams({ from: { integrationId: 1 }, ...content })
            )
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent).toMatchObject(expectedParts)
            if (content.text) {
                expect(sent.charsets.text).toEqual('UTF-8')
            }
        })

        it('should not include preheader span if not in params', async () => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                html: '<tbody>Test email content</tbody>',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            const htmlData = sent.html
            expect(htmlData).not.toContain('mso-hide:all')
        })

        it.each([
            [
                'a document',
                '<html><body class="email"><table><tbody><tr><td>Hi</td></tr></tbody></table></body></html>',
                /^<html><body class="email"><span style=".*">This is a preview text<\/span><table>/,
            ],
            ['a fragment without tbody', '<p>Hi</p>', /^<span style=".*">This is a preview text<\/span><p>Hi<\/p>$/],
        ])('should include preheader at the start of the body of %s', async (_name, html, expected) => {
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                html,
                preheader: 'This is a preview text',
            })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            expect(sent.html).toMatch(expected)
        })

        it.each([
            { name: 'a hog function send', fromHogFlow: false, parentRunId: null, expectedSource: {} },
            {
                name: 'a workflow send',
                fromHogFlow: true,
                parentRunId: null,
                expectedSource: {
                    app_source_id: 'function-1',
                    instance_id: 'action-email',
                    workflow_id: 'function-1',
                    invocation_id: 'invocation-1',
                    workflow_version: 4,
                },
            },
            {
                name: 'a broadcast send',
                fromHogFlow: true,
                parentRunId: 'batch-run-1',
                expectedSource: {
                    app_source_id: 'batch-run-1',
                    instance_id: 'action-email',
                    workflow_id: 'function-1',
                    invocation_id: 'invocation-1',
                    workflow_version: 4,
                },
            },
        ])(
            'includes unsubscribe headers for $name, attributed to the email it came from',
            async ({ fromHogFlow, parentRunId, expectedSource }) => {
                invocation.hogFunction.metadata = { message_category_type: 'marketing' }
                if (fromHogFlow) {
                    Object.assign(invocation, { hogFlow: { id: 'function-1', version: 1 }, parentRunId })
                    invocation.state.actionId = 'action-email'
                    invocation.state.renderedWorkflowVersion = 4
                }
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const [sent] = ses.sent
                expect(sent.headers).toEqual(
                    expect.objectContaining({
                        'List-Unsubscribe': expect.any(String),
                        'List-Unsubscribe-Post': expect.any(String),
                    })
                )
                const token = sent.headers['List-Unsubscribe'].match(/messaging-preferences\/([^/]+)\//)![1]
                const validated = new RecipientTokensService(
                    hub.ENCRYPTION_SALT_KEYS,
                    hub.SITE_URL
                ).validatePreferencesToken(token)
                expect(validated).toEqual({
                    valid: true,
                    team_id: team.id,
                    identifier: 'test@example.com',
                    ...expectedSource,
                })
            }
        )

        it('drops the run claims when they would push List-Unsubscribe past the SES header limit', async () => {
            const flowId = '0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'
            const actionId = 'action_email_0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5c'
            const longAddress = `${'a'.repeat(64)}@${'b'.repeat(63)}.${'c'.repeat(63)}.example.com`
            invocation.hogFunction.metadata = { message_category_type: 'marketing' }
            invocation.queueParameters = createEmailParams({
                from: { integrationId: 1 },
                to: { email: longAddress, name: 'Test User' },
            })
            Object.assign(invocation, {
                id: '0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5d',
                functionId: flowId,
                hogFlow: { id: flowId, version: 1 },
                parentRunId: null,
            })
            invocation.state.actionId = actionId
            invocation.state.renderedWorkflowVersion = 17

            const result = await service.executeSendEmail(invocation)

            expect(result.error).toBeUndefined()
            const unsubscribeValue = ses.sent[0].headers['List-Unsubscribe']
            expect(unsubscribeValue.length).toBeLessThanOrEqual(870)
            const token = unsubscribeValue.match(/messaging-preferences\/([^/]+)\//)![1]
            expect(
                new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL).validatePreferencesToken(token)
            ).toEqual({
                valid: true,
                team_id: team.id,
                identifier: longAddress,
                app_source_id: flowId,
                instance_id: actionId,
            })
        })

        it('should not include unsubscribe headers for transactional emails (but tracking-code header is still set)', async () => {
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            const headerNames = Object.keys(sent.headers)
            expect(headerNames).not.toContain('List-Unsubscribe')
            expect(headerNames).not.toContain('List-Unsubscribe-Post')
            expect(headerNames).toContain('X-PostHog-Tracking-Code')
        })

        it.each(['transactional', 'marketing'])(
            'marks a %s send as auto-generated so autoresponders do not answer it',
            async (categoryType) => {
                // Without this an autoresponder answers the workflow, and when the address it
                // answers is a support inbox the reply re-enters the same workflow as a new ticket.
                invocation.hogFunction.metadata = { message_category_type: categoryType }
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const [sent] = ses.sent
                expect(sent.headers['Auto-Submitted']).toEqual('auto-generated')
            }
        )

        it('attaches the X-PostHog-Tracking-Code header carrying the full signed code', async () => {
            // The header is the authoritative tracking-code carrier (the EmailTag is the
            // bounded backwards-compat fallback). It rides on every outbound message,
            // regardless of transactional vs. marketing category.
            invocation.hogFunction.metadata = { message_category_type: 'transactional' }
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            const [sent] = ses.sent
            const trackingCode = sent.headers['X-PostHog-Tracking-Code']
            expect(typeof trackingCode).toBe('string')
            expect(trackingCode.length).toBeGreaterThan(0)
            // The SES EmailTag carries a *different* (shorter, unsigned) code so it stays under the
            // 256-char tag-value limit even when distinct_id is long.
            expect(sent.tags.ph_id).toEqual(expect.any(String))
            expect(sent.tags.ph_id).not.toEqual(trackingCode)
        })

        describe('per-send tracking gate (tracking_enabled)', () => {
            // Would be tracked if the gate regressed: has an anchor to rewrite and a </body> to pixel.
            const trackableHtml = '<body>Hi! <a href="https://example.com">Click me</a></body>'

            beforeEach(() => {
                invocation.queueParameters = createEmailParams({ from: { integrationId: 1 }, html: trackableHtml })
                invocation.hogFunction.metadata = { tracking_enabled: false }
            })

            it.each([
                {
                    case: 'delivers tracking-off mail without open or click tracking',
                    trackingEnabled: false,
                    untrackedSet: 'posthog-messaging-untracked',
                    error: undefined,
                    sent: [
                        expect.objectContaining({
                            to: ['"Test User" <test@example.com>'],
                            html: trackableHtml,
                            tracked: false,
                        }),
                    ],
                },
                {
                    case: 'fails tracking-off mail instead of sending it tracked when no untracked set is named',
                    trackingEnabled: false,
                    untrackedSet: '',
                    error: expect.stringContaining('SES_UNTRACKED_CONFIGURATION_SET is empty'),
                    sent: [],
                },
                {
                    case: 'delivers tracked mail when no untracked set is named',
                    trackingEnabled: true,
                    untrackedSet: '',
                    error: undefined,
                    sent: [
                        expect.objectContaining({
                            to: ['"Test User" <test@example.com>'],
                            html: expect.stringContaining('Click me'),
                            tracked: true,
                        }),
                    ],
                },
            ])('$case', async ({ trackingEnabled, untrackedSet, error, sent }) => {
                invocation.hogFunction.metadata = { tracking_enabled: trackingEnabled }
                const sesService = createService({ sesUntrackedConfigurationSet: untrackedSet })

                const result = await sesService.executeSendEmail(invocation)

                expect(result.error).toEqual(error)
                expect(ses.sent).toEqual(sent)
            })

            it.each([
                {
                    case: 'the workflow and step names',
                    utmParams: undefined,
                    query: 'utm_source=posthog&amp;utm_medium=email&amp;utm_campaign=Spring%20sale&amp;utm_content=Welcome',
                },
                {
                    case: 'rendered custom values',
                    utmParams: { utm_source: 'newsletter', utm_campaign: '{{ "pro" | upcase }}' },
                    query: 'utm_source=newsletter&amp;utm_medium=email&amp;utm_campaign=PRO&amp;utm_content=Welcome',
                },
                {
                    case: 'a rendered value with characters HTML escapes',
                    utmParams: { utm_campaign: '{{ "Starter & Premium" }}' },
                    query: 'utm_source=posthog&amp;utm_medium=email&amp;utm_campaign=Starter%20%26%20Premium&amp;utm_content=Welcome',
                },
                {
                    case: 'the default for a value with a Liquid error',
                    utmParams: { utm_campaign: '{{ person.properties.plan' },
                    query: 'utm_source=posthog&amp;utm_medium=email&amp;utm_campaign=Spring%20sale&amp;utm_content=Welcome',
                },
            ])('tags the links with $case when the step turns UTM tags on', async ({ utmParams, query }) => {
                invocation.hogFunction.metadata = {
                    tracking_enabled: false,
                    utm_tags_enabled: true,
                    utm_params: utmParams,
                    hog_flow_name: 'Spring sale',
                    hog_flow_action_name: 'Welcome',
                }
                invocation.state.actionId = 'action-email'
                const kafka = createRecordingIngestionOutputs([MESSAGE_ASSETS_OUTPUT])
                const messageAssets = new MessageAssetsService(kafka.outputs)
                service['messageAssetsService'] = messageAssets
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                messageAssets.queueInvocationResults([result])
                await messageAssets.flush()
                const [sent] = ses.sent
                const taggedHtml = `<body>Hi! <a href="https://example.com?${query}">Click me</a></body>`
                expect(sent.html).toEqual(taggedHtml)
                // The stored copy behind "View email" shows the links the recipient got.
                expect(kafka.produced(MESSAGE_ASSETS_OUTPUT)).toEqual([expect.objectContaining({ html: taggedHtml })])
            })

            it.each([
                { case: 'an empty list', list: (): string => '', fixedScanner: false },
                { case: 'a list with this team', list: (): string => `${team.id}`, fixedScanner: true },
                { case: 'a list with another team', list: (): string => `${team.id + 1}`, fixedScanner: false },
                { case: 'every team', list: (): string => '*', fixedScanner: true },
            ])('picks the UTM link scanner from $case', async ({ list, fixedScanner }) => {
                service['sesConfig'].utmLinkScannerTeams = list()
                invocation.queueParameters = createEmailParams({
                    from: { integrationId: 1 },
                    html: '<body><a href=https://example.com/pricing>Click me</a></body>',
                })
                invocation.hogFunction.metadata = {
                    tracking_enabled: false,
                    utm_tags_enabled: true,
                    hog_flow_name: 'Spring sale',
                    hog_flow_action_name: 'Welcome',
                }
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const [sent] = ses.sent
                expect(sent.html).toEqual(
                    fixedScanner
                        ? '<body><a href="https://example.com/pricing?utm_source=posthog&amp;utm_medium=email&amp;utm_campaign=Spring%20sale&amp;utm_content=Welcome">Click me</a></body>'
                        : '<body><a href=https://example.com/pricing>Click me</a></body>'
                )
            })

            it.each([
                {
                    case: 'tags the links of a tracked send',
                    trackingEnabled: true,
                    allowlisted: true,
                    isTest: false,
                    sensitive: false,
                    tagged: true,
                },
                {
                    case: 'leaves the links of a team off the allowlist',
                    trackingEnabled: true,
                    allowlisted: false,
                    isTest: false,
                    sensitive: false,
                    tagged: false,
                },
                {
                    case: 'leaves the links of an untracked send',
                    trackingEnabled: false,
                    allowlisted: true,
                    isTest: false,
                    sensitive: false,
                    tagged: false,
                },
                {
                    case: 'leaves the links of a test send',
                    trackingEnabled: true,
                    allowlisted: true,
                    isTest: true,
                    sensitive: false,
                    tagged: false,
                },
                {
                    case: 'leaves the links of a sensitive email',
                    trackingEnabled: true,
                    allowlisted: true,
                    isTest: false,
                    sensitive: true,
                    tagged: false,
                },
            ])(
                '$case with the workflow run id',
                async ({ trackingEnabled, allowlisted, isTest, sensitive, tagged }) => {
                    const taggingService = createService({
                        workflowRunLinkTagTeams: allowlisted ? String(team.id) : '',
                    })
                    invocation.hogFunction.metadata = { tracking_enabled: trackingEnabled, sensitive }
                    invocation.queueParameters = createEmailParams({
                        from: { integrationId: 1 },
                        html: '<a href="https://app.posthog-test.com/">a</a><a href="https://example.com/">b</a>',
                    })
                    const result = await taggingService.executeSendEmail(invocation, isTest)
                    expect(result.error).toBeUndefined()
                    const sentHtml = ses.sent[0].html!
                    expect(sentHtml.match(/ph_workflow_run=[^"&]*/g) ?? []).toEqual(
                        tagged ? ['ph_workflow_run=invocation-1'] : []
                    )
                }
            )

            it('records an email_untracked app metric for untracked sends but not for test sends', async () => {
                invocation.state.renderedWorkflowVersion = 3
                const normal = await service.executeSendEmail(invocation)
                expect(normal.metrics.map((m) => m.metric_name)).toEqual(
                    expect.arrayContaining(['email_sent', 'email_untracked'])
                )
                expect(normal.metrics.find((m) => m.metric_name === 'email_untracked')?.app_source_version).toEqual({
                    id: invocation.functionId,
                    version: 3,
                })

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
                    const sentHtml = ses.sent[0].html
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
                const sentHtml = ses.sent[0].html
                expect(sentHtml).toContain('ses:tags="phl:')
                expect(sentHtml).toContain('ph_id=')
            })

            it('the step-level toggle wins over consent: tracking_enabled false is untracked even for opted-in recipients', async () => {
                invocation.hogFunction.metadata = { message_category_type: 'marketing', tracking_enabled: false }
                setConsentState('opt_in', 'OPTED_IN')
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = ses.sent[0].html
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
                const sentHtml = ses.sent[0].html
                expect(sentHtml).toEqual(trackableHtml)
            })

            it('sends untracked when the consent-mode lookup fails (fail closed)', async () => {
                jest.spyOn(
                    (service as any).teamWorkflowsConfigService,
                    'getEmailTrackingConsentMode'
                ).mockRejectedValue(new Error('db down'))
                const result = await service.executeSendEmail(invocation)
                expect(result.error).toBeUndefined()
                const sentHtml = ses.sent[0].html
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
                const sentHtml = ses.sent[0].html
                expect(sentHtml).toEqual(trackableHtml)
            })
        })

        it('should report a missing message id', async () => {
            // SES always answers a send with a message id, so only a stub can produce this fault.
            jest.spyOn(service.sesV2Client!, 'send').mockResolvedValue({} as never)
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toMatchInlineSnapshot(`"Failed to send email via SES: No messageId returned from SES"`)
            expect(result.emailSendResult).toEqual({ status: 'failed', reason: result.error })
        })

        it.each([
            ['an ordinary template', {}, 'Test Subject', undefined, false],
            ['a sensitive template', { sensitive: true }, undefined, undefined, false],
            ['a workflow step', {}, 'Test Subject', 3, false],
            ['a transactional email', {}, 'Test Subject', undefined, true],
        ])(
            'should capture a $workflows_email_sent PostHog event and version the email_sent metric on success, for %s',
            async (_name, extraMetadata, subject, workflowVersion, transactional) => {
                await captureEngagementEvents()
                invocation.hogFunction.metadata = { ...invocation.hogFunction.metadata, ...extraMetadata }
                invocation.state.renderedWorkflowVersion = workflowVersion
                if (transactional) {
                    invocation.state.globals.event.event = TRANSACTIONAL_EMAIL_EVENT
                }
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
                        $workflow_invocation_id: 'invocation-1',
                        $email_message_id: ses.sent[0].messageId,
                        $email_to: 'test@example.com',
                        $email_tracking_enabled: true,
                    },
                })
                expect(result.capturedPostHogEvents[0].properties.$email_subject).toEqual(subject)
                expect(result.capturedPostHogEvents[0].properties.$workflow_version).toEqual(workflowVersion)
                expect(result.capturedPostHogEvents[0].properties.$email_transactional).toEqual(
                    transactional ? true : undefined
                )
                expect(
                    result.metrics.find((metric) => metric.metric_name === 'email_sent')?.app_source_version
                ).toEqual(
                    workflowVersion === undefined ? undefined : { id: invocation.functionId, version: workflowVersion }
                )
            }
        )

        it('does not capture a PostHog event when engagement capture is disabled for the team', async () => {
            // Default config has capture_workflows_engagement_events=false, so even on success no event is queued.
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeUndefined()
            expect(result.capturedPostHogEvents).toHaveLength(0)
        })

        it('should capture a $workflows_email_failed PostHog event on failure', async () => {
            jest.spyOn((service as any).teamWorkflowsConfigService, 'shouldCaptureEngagementEvents').mockResolvedValue(
                true
            )
            ses.failWith({ status: 400, type: 'MessageRejected', message: 'SES error' })
            const result = await service.executeSendEmail(invocation)
            expect(result.error).toBeDefined()
            expect(result.capturedPostHogEvents).toHaveLength(1)
            expect(result.capturedPostHogEvents[0]).toMatchObject({
                event: '$workflows_email_failed',
                distinct_id: 'distinct_id',
            })
        })

        it.each([
            {
                outcome: 'delivered',
                rejectWith: undefined,
                delivered: 1,
                error: undefined,
                metrics: ['email_sent', 'email_untracked'],
            },
            {
                outcome: 'rejected',
                rejectWith: 'SES rejected the email',
                delivered: 0,
                error: expect.stringContaining('SES rejected the email'),
                metrics: ['email_failed'],
            },
        ])(
            'keeps a $outcome send as it was when the engagement setting read fails',
            async ({ rejectWith, delivered, error, metrics }) => {
                const teamConfigDb = await postgresThatDropsConnections(hub.DATABASE_URL, () => true)
                service = createService({}, {}, { teamConfigDb: teamConfigDb.postgres })
                if (rejectWith) {
                    ses.failWith({ status: 400, type: 'MessageRejected', message: rejectWith })
                }
                const failuresBefore = await metricValue('cdp_email_engagement_setting_read_failures_total', {})

                const result = await service.executeSendEmail(invocation)
                await teamConfigDb.close()

                expect(ses.sent).toHaveLength(delivered)
                expect(result.error).toEqual(error)
                expect(result.metrics.map((m) => m.metric_name)).toEqual(metrics)
                expect(result.capturedPostHogEvents).toEqual([])
                expect(result.logs).toContainEqual(
                    expect.objectContaining({
                        level: 'warn',
                        message:
                            'Could not read the engagement setting, so no engagement event was recorded for this email.',
                    })
                )
                expect(await metricValue('cdp_email_engagement_setting_read_failures_total', {})).toBe(
                    failuresBefore + 1
                )
            }
        )
    })
})
