import { AddressInfo, createServer } from 'node:net'
import SMTPTransport from 'nodemailer/lib/smtp-transport'

import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { RedisV2 } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import {
    EmailServiceFixture,
    createEmailLimiterRedis,
    createEmailSender,
    createEmailVmState,
    createMessageAssetsService,
    insertEmailWorkflowsConfig,
} from '~/tests/helpers/email'
import { LocalSes, LocalSesAwsEnvironment } from '~/tests/helpers/ses'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub } from '../../../types'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { EmailSuppressionService } from './email-suppression.service'
import { EmailService, EmailServiceConfig, teamEmailCapBuckets } from './email.service'
import { mailDevTransport } from './helpers/maildev'
import { MessageAssetsService } from './message-assets.service'

describe('EmailService with local SES', () => {
    let hub: Hub
    let service: EmailService
    let invocation: CyclotronJobInvocationHogFunction
    let params: CyclotronInvocationQueueParametersEmailType
    let ses: LocalSes
    let limiter: RateLimiterService
    // One pool of one client for the whole suite, because RedisV2 has no close. afterAll quits that client so Jest can exit.
    let redis: RedisV2 | undefined
    let configService: TeamWorkflowsConfigService
    let suppression: EmailSuppressionService
    let assets: MessageAssetsService
    const hourlyCap = 4
    const dailyCap = 8
    const capReachedLog = `reached its email sending limit of ${hourlyCap} emails per hour`
    let environment: LocalSesAwsEnvironment | undefined
    let services: EmailServiceFixture

    const workflowBucket = (): { key: string; capacity: number; refillPerSecond: number } => ({
        key: `@posthog/workflow-email-rate/${invocation.teamId}/${invocation.functionId}`,
        capacity: 1,
        refillPerSecond: 1 / 3600,
    })

    const drainWorkflowBucket = async (): Promise<void> => {
        expect(await limiter.claimUpTo({ ...workflowBucket(), requested: 1 })).toBe(1)
    }

    const drainHourlyTeamBucket = async (): Promise<void> => {
        const bucket = teamEmailCapBuckets(invocation.teamId, hourlyCap, dailyCap)[0]
        expect(await limiter.claimUpTo({ ...bucket, requested: bucket.capacity })).toBe(bucket.capacity)
    }

    const logMessages = (result: { logs: { message: string }[] }): string[] => result.logs.map((log) => log.message)

    const setProvider = async (provider: string): Promise<void> => {
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_integration SET config = jsonb_set(config, '{provider}', to_jsonb($1::text)) WHERE id = $2`,
            [provider, params.from.integrationId],
            'test-set-email-provider'
        )
    }

    const failDatabaseQuery = (tag: string): void => {
        const query = hub.postgres.query.bind(hub.postgres)
        jest.spyOn(hub.postgres, 'query').mockImplementation((...args) => {
            if (args[3] === tag) {
                return Promise.reject(new Error(`Database fault: ${tag}`))
            }
            return query(...args)
        })
    }

    const useService = (config: Partial<EmailServiceConfig> = {}): void => {
        service?.sesV2Client?.destroy()
        service = services.create({
            sesConfig: {
                sesAccessKeyId: 'local-ses-test',
                sesSecretAccessKey: 'local-ses-test',
                sesRegion: 'us-east-1',
                sesEndpoint: ses.endpoint,
                sesTrackedConfigurationSet: 'local-tracked',
                sesUntrackedConfigurationSet: 'local-untracked',
                teamEmailCapMode: 'off',
                teamEmailTierHourlyCaps: [hourlyCap],
                teamEmailTierDailyCaps: [dailyCap],
                ...config,
            },
            messageAssetsService: assets,
            workflowEmailRateLimiter: limiter,
            teamEmailRateLimiter: limiter,
        })
    }

    beforeEach(async () => {
        environment = new LocalSesAwsEnvironment()
        environment.configure()
        ses = new LocalSes()
        await ses.start()
        hub = await createHub({ SITE_URL: 'http://localhost:8000' })
        redis ??= createEmailLimiterRedis(hub)
        limiter = new RateLimiterService(redis, { name: 'email-outcomes-test' })
        services = new EmailServiceFixture(hub)
        configService = services.workflowsConfig
        suppression = services.suppression
        assets = createMessageAssetsService()
        const { team } = await createTestTeamFixture(hub.postgres)
        const integration = await insertIntegration(hub.postgres, team.id, createEmailSender())
        useService()
        invocation = createExampleInvocation({ team_id: team.id, metadata: { tracking_enabled: false } })
        params = {
            type: 'email',
            from: { integrationId: integration.id },
            to: { email: `${invocation.id}@example.com`, name: 'Example Recipient' },
            cc: 'copy@example.com',
            bcc: 'hidden@example.com',
            replyTo: 'reply@example.com',
            subject: 'Local SES delivery',
            text: 'A plain text message.',
            html: '<p>An HTML message.</p>',
        }
        invocation.queueParameters = params
        invocation.state.vmState = createEmailVmState()
        invocation.state.actionId = 'send-email'
        await insertEmailWorkflowsConfig(hub, team.id)
    })

    afterEach(async () => {
        services?.close()
        await ses?.stop()
        if (hub) {
            await closeHub(hub)
        }
        environment?.restore()
        jest.restoreAllMocks()
    })

    afterAll(async () => {
        await redis?.useClient({ name: 'email-outcomes-test-close' }, (client) => client.quit())
    })

    it('delivers the email through the real SDK with bodies, addresses and custom headers', async () => {
        const result = await service.executeSendEmail(invocation)

        expect(result).toMatchObject({ finished: true })
        expect(result.error).toBeUndefined()
        expect(result.metrics).toEqual(
            expect.arrayContaining([expect.objectContaining({ metric_name: 'email_sent', count: 1 })])
        )
        expect(ses.requests).toHaveLength(1)
        expect(ses.requests[0]).toMatchObject({
            TenantName: `team-${invocation.teamId}`,
            ConfigurationSetName: 'local-untracked',
            FeedbackForwardingEmailAddress: 'sender@example.com',
            EmailTags: [{ Name: 'ph_id', Value: expect.any(String) }],
        })
        const emails = await ses.getEmails()
        expect(emails).toHaveLength(1)
        expect(emails[0]).toMatchObject({
            messageId: expect.any(String),
            from: '"Example Sender" <sender@example.com>',
            destination: {
                to: [`"Example Recipient" <${params.to.email}>`],
                cc: ['copy@example.com'],
                bcc: ['hidden@example.com'],
            },
            replyTo: ['reply@example.com'],
            subject: 'Local SES delivery',
            body: { text: 'A plain text message.', html: '<p>An HTML message.</p>' },
            headers: expect.arrayContaining([
                { name: 'Auto-Submitted', value: 'auto-generated' },
                { name: 'List-Unsubscribe-Post', value: 'List-Unsubscribe=One-Click' },
                { name: 'List-Unsubscribe', value: expect.stringContaining('http') },
                { name: 'X-PostHog-Tracking-Code', value: expect.any(String) },
            ]),
        })
    })

    describe('rescheduled outcomes', () => {
        it.each([
            {
                cause: 'workflow pacing',
                arrange: async (): Promise<void> => {
                    invocation.hogFunction.metadata!.email_sending_rate_limit = { count: 1, period: 'hour' }
                    await drainWorkflowBucket()
                },
                log: 'Sending rate limit reached (1 emails per hour)',
            },
            {
                cause: 'team cap',
                arrange: async (): Promise<void> => {
                    useService({ teamEmailCapMode: 'enforce' })
                    await drainHourlyTeamBucket()
                },
                log: capReachedLog,
            },
        ])('keeps the payload and priority without a send footprint after $cause', async ({ arrange, log }) => {
            invocation.queuePriority = 1
            await arrange()
            const before = Date.now()

            const result = await service.executeSendEmail(invocation)

            expect(result).toMatchObject({
                finished: false,
                metrics: [],
                messageAssets: [],
                capturedPostHogEvents: [],
            })
            expect(result.error).toBeUndefined()
            expect(result.skipped).toBeUndefined()
            expect(logMessages(result)).toEqual(expect.arrayContaining([expect.stringContaining(log)]))
            expect(result.invocation.queueParameters).toEqual(params)
            expect(result.invocation.queuePriority).toBe(1)
            expect(result.invocation.queueScheduledAt!.toMillis()).toBeGreaterThan(before)
            expect(result.invocation.state.vmState?.stack).toEqual([])
            expect(ses.requests).toEqual([])
            expect(await ses.getEmails()).toEqual([])
        })
    })

    describe('provider outcomes', () => {
        it('reports an unknown provider as sent without delivering', async () => {
            await setProvider('unknown')

            const result = await service.executeSendEmail(invocation)

            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()
            expect(result.invocation.queueParameters).toBeUndefined()
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(result.invocation.state.vmState?.stack).toEqual([{ success: true }])
            expect(result.metrics.map((metric) => metric.metric_name)).toEqual(['email_sent', 'email_untracked'])
            expect(result.messageAssets).toHaveLength(1)
            expect(result.capturedPostHogEvents).toEqual([expect.objectContaining({ event: '$workflows_email_sent' })])
            expect(ses.requests).toEqual([])
            expect(await ses.getEmails()).toEqual([])
        })

        it('fails an unsupported provider', async () => {
            await setProvider('unsupported')

            const result = await service.executeSendEmail(invocation)

            expect(result.finished).toBe(true)
            expect(result.error).toBe('Email delivery mode not supported')
            expect(result.invocation.queueParameters).toBeUndefined()
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
            expect(result.metrics.map((metric) => metric.metric_name)).toEqual(['email_failed'])
            expect(result.messageAssets).toEqual([])
            expect(result.capturedPostHogEvents).toEqual([
                expect.objectContaining({ event: '$workflows_email_failed' }),
            ])
            expect(ses.requests).toEqual([])
            expect(await ses.getEmails()).toEqual([])
        })

        it('records a maildev SMTP rejection as failed', async () => {
            await setProvider('maildev')
            const smtp = createServer((socket) => socket.end('554 Local SMTP rejected email\r\n'))
            await new Promise<void>((resolve) => smtp.listen(0, '127.0.0.1', resolve))
            const transport = mailDevTransport!.transporter as SMTPTransport
            const originalOptions = transport.options
            transport.options = { ...originalOptions, host: '127.0.0.1', port: (smtp.address() as AddressInfo).port }
            try {
                const result = await service.executeSendEmail(invocation)

                expect(result).toMatchObject({
                    finished: true,
                    error: expect.stringContaining('Local SMTP rejected email'),
                    metrics: [expect.objectContaining({ metric_name: 'email_failed' })],
                    messageAssets: [],
                    capturedPostHogEvents: [expect.objectContaining({ event: '$workflows_email_failed' })],
                })
                expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
                expect(result.invocation.queueParameters).toBeUndefined()
                expect(result.invocation.queueScheduledAt).toBeUndefined()
                expect(ses.requests).toEqual([])
                expect(await ses.getEmails()).toEqual([])
            } finally {
                transport.options = originalOptions
                await new Promise<void>((resolve, reject) => smtp.close((error) => (error ? reject(error) : resolve())))
            }
        })
    })

    describe('skip flags and unspent budgets', () => {
        it.each([
            {
                gate: 'suspended',
                metric: 'email_suspended',
                skipped: undefined,
                arrange: async (): Promise<void> => {
                    await hub.postgres.query(
                        PostgresUse.COMMON_WRITE,
                        'UPDATE workflows_teamworkflowsconfig SET email_sending_suspended_at = NOW() WHERE team_id = $1',
                        [invocation.teamId],
                        'test-suspend-email-sending'
                    )
                },
            },
            {
                gate: 'paused',
                metric: 'email_paused',
                skipped: true,
                arrange: (): Promise<void> => {
                    invocation.hogFunction.metadata!.email_sending_paused_at = new Date().toISOString()
                    return Promise.resolve()
                },
            },
            {
                gate: 'suppressed to and cc',
                metric: 'email_suppressed',
                skipped: undefined,
                arrange: async (): Promise<void> => {
                    await suppression.recordHardBounces(invocation.teamId, [params.to.email, 'copy@example.com'])
                },
            },
        ])('$gate keeps both budgets intact', async ({ metric, skipped, arrange }) => {
            useService({ teamEmailCapMode: 'enforce' })
            invocation.hogFunction.metadata!.email_sending_rate_limit = { count: 1, period: 'hour' }
            await arrange()

            const result = await service.executeSendEmail(invocation)

            expect(result).toMatchObject({
                finished: true,
                metrics: [expect.objectContaining({ metric_name: metric, count: 1 })],
                messageAssets: [],
                capturedPostHogEvents: [],
            })
            expect(result.error).toBeUndefined()
            expect(result.skipped).toBe(skipped)
            expect(result.invocation.queueParameters).toBeUndefined()
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
            expect(ses.requests).toEqual([])
            expect(await ses.getEmails()).toEqual([])
            expect(await limiter.claimUpTo({ ...workflowBucket(), requested: 1 })).toBe(1)
            for (const bucket of teamEmailCapBuckets(invocation.teamId, hourlyCap, dailyCap)) {
                expect(await limiter.claimUpTo({ ...bucket, requested: bucket.capacity })).toBe(bucket.capacity)
            }
        })
    })

    describe('failures before the tracking decision', () => {
        it('rejects an integration lookup fault instead of recording an outcome', async () => {
            failDatabaseQuery('fetchIntegrations')

            await expect(service.executeSendEmail(invocation)).rejects.toThrow('Database fault: fetchIntegrations')

            expect(invocation.state.vmState?.stack).toEqual([])
            expect(ses.requests).toEqual([])
            expect(await ses.getEmails()).toEqual([])
        })

        it('reports tracking enabled on a failure before the tracking-off decision', async () => {
            params.from.integrationId = -1

            const result = await service.executeSendEmail(invocation)

            expect(result).toMatchObject({
                finished: true,
                error: expect.stringContaining('Email integration not found'),
                metrics: [expect.objectContaining({ metric_name: 'email_failed' })],
                messageAssets: [],
                capturedPostHogEvents: [
                    expect.objectContaining({
                        event: '$workflows_email_failed',
                        properties: expect.objectContaining({ $email_tracking_enabled: true }),
                    }),
                ],
            })
            expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
            expect(ses.requests).toEqual([])
            expect(await ses.getEmails()).toEqual([])
        })
    })

    describe('team sending budgets', () => {
        it.each([0, 1])('shadow mode sends despite bucket %i denying and charges both buckets', async (denied) => {
            useService({ teamEmailCapMode: 'shadow' })
            const buckets = teamEmailCapBuckets(invocation.teamId, hourlyCap, dailyCap)
            const drained = buckets[denied]
            expect(await limiter.claimUpTo({ ...drained, requested: drained.capacity })).toBe(drained.capacity)

            const result = await service.executeSendEmail(invocation)

            expect(result).toMatchObject({ finished: true })
            expect(result.error).toBeUndefined()
            expect(result.invocation.queueParameters).toBeUndefined()
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(await ses.getEmails()).toHaveLength(1)
            for (const [index, bucket] of buckets.entries()) {
                expect(await limiter.claimUpTo({ ...bucket, requested: bucket.capacity, refillPerSecond: 0 })).toBe(
                    index === denied ? 0 : bucket.capacity - 3
                )
            }
        })

        it.each([
            {
                lookup: 'fails',
                arrange: (): void => failDatabaseQuery('fetch-team-workflows-configs'),
            },
            {
                lookup: 'returns no tier',
                arrange: (): void => {
                    jest.spyOn(configService, 'getEmailSendingTier').mockResolvedValue(null)
                },
            },
        ])('sends without charging the team cap when the tier lookup $lookup', async ({ arrange }) => {
            useService({ teamEmailCapMode: 'enforce' })
            invocation.state.globals.event.distinct_id = ''
            arrange()

            const result = await service.executeSendEmail(invocation)

            expect(result).toMatchObject({ finished: true })
            expect(result.error).toBeUndefined()
            expect(await ses.getEmails()).toHaveLength(1)
            for (const bucket of teamEmailCapBuckets(invocation.teamId, hourlyCap, dailyCap)) {
                expect(await limiter.claimUpTo({ ...bucket, requested: bucket.capacity })).toBe(bucket.capacity)
            }
        })

        it.each([
            { name: 'to only', copies: 1, hourly: 4, daily: 8, charged: 1 },
            { name: 'to, cc and bcc', copies: 3, hourly: 4, daily: 8, charged: 3 },
            { name: 'clamped to hourly capacity', copies: 3, hourly: 2, daily: 8, charged: 2 },
            { name: 'clamped to daily capacity', copies: 3, hourly: 4, daily: 2, charged: 2 },
        ])('charges each recipient, $name', async ({ copies, hourly, daily, charged }) => {
            useService({
                teamEmailCapMode: 'enforce',
                teamEmailTierHourlyCaps: [hourly],
                teamEmailTierDailyCaps: [daily],
            })
            if (copies === 1) {
                delete params.cc
                delete params.bcc
            }

            const result = await service.executeSendEmail(invocation)

            expect(result).toMatchObject({ finished: true })
            expect(result.error).toBeUndefined()
            const emails = await ses.getEmails()
            expect(emails).toHaveLength(1)
            expect(Object.values(emails[0].destination).flat()).toHaveLength(copies)
            for (const bucket of teamEmailCapBuckets(invocation.teamId, hourly, daily)) {
                expect(await limiter.claimUpTo({ ...bucket, requested: bucket.capacity, refillPerSecond: 0 })).toBe(
                    bucket.capacity - charged
                )
            }
        })
    })

    describe('tokens after rescheduling', () => {
        const throttleSes = (): Promise<void> => {
            ses.setError('TooManyRequestsException')
            return Promise.resolve()
        }

        it.each([
            {
                name: 'a team cap denial keeps the workflow token spent',
                arrange: drainHourlyTeamBucket,
                isTest: false,
                log: capReachedLog,
                sesRequests: 0,
                workflow: 0,
                hour: 0,
                day: 8,
            },
            {
                name: 'an SES throttle keeps both budgets spent',
                arrange: throttleSes,
                isTest: false,
                log: 'SES rate-limited (TooManyRequestsException)',
                sesRequests: 1,
                workflow: 0,
                hour: 1,
                day: 5,
            },
            {
                name: 'a throttled editor test reschedules without charging budgets',
                arrange: throttleSes,
                isTest: true,
                log: 'SES rate-limited (TooManyRequestsException)',
                sesRequests: 1,
                workflow: 1,
                hour: 4,
                day: 8,
            },
        ])('$name', async ({ arrange, isTest, log, sesRequests, workflow, hour, day }) => {
            useService({ teamEmailCapMode: 'enforce' })
            invocation.hogFunction.metadata!.email_sending_rate_limit = { count: 1, period: 'hour' }
            await arrange()

            const result = await service.executeSendEmail(invocation, isTest)

            expect(result).toMatchObject({ finished: false, metrics: [], messageAssets: [], capturedPostHogEvents: [] })
            expect(result.error).toBeUndefined()
            expect(result.skipped).toBeUndefined()
            expect(logMessages(result)).toEqual(expect.arrayContaining([expect.stringContaining(log)]))
            expect(result.invocation.queueParameters).toEqual(params)
            expect(result.invocation.queueScheduledAt?.isValid).toBe(true)
            expect(result.invocation.state.vmState?.stack).toEqual([])
            expect(ses.requests).toHaveLength(sesRequests)
            expect(await ses.getEmails()).toEqual([])
            expect(await limiter.claimUpTo({ ...workflowBucket(), requested: 1, refillPerSecond: 0 })).toBe(workflow)
            const [hourly, daily] = teamEmailCapBuckets(invocation.teamId, hourlyCap, dailyCap)
            expect(await limiter.claimUpTo({ ...hourly, requested: hourly.capacity, refillPerSecond: 0 })).toBe(hour)
            expect(await limiter.claimUpTo({ ...daily, requested: daily.capacity, refillPerSecond: 0 })).toBe(day)
        })
    })

    describe('post-send faults', () => {
        it('throws after SES accepts when the engagement config read fails', async () => {
            jest.spyOn(configService, 'shouldCaptureEngagementEvents').mockRejectedValue(
                new Error('Engagement config fault')
            )

            await expect(service.executeSendEmail(invocation)).rejects.toThrow('Engagement config fault')

            expect(ses.requests).toHaveLength(1)
            expect(await ses.getEmails()).toEqual([expect.objectContaining({ subject: params.subject })])
        })

        it('reports email_failed after SES accepts when the asset row fails', async () => {
            jest.spyOn(assets, 'buildRowForEmail').mockImplementation(() => {
                throw new Error('Asset row fault')
            })

            const result = await service.executeSendEmail(invocation)

            expect(result).toMatchObject({
                finished: true,
                error: 'Asset row fault',
                metrics: [expect.objectContaining({ metric_name: 'email_failed' })],
                messageAssets: [],
                capturedPostHogEvents: [expect.objectContaining({ event: '$workflows_email_failed' })],
            })
            expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
            expect(result.invocation.queueParameters).toBeUndefined()
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(ses.requests).toHaveLength(1)
            expect(await ses.getEmails()).toEqual([expect.objectContaining({ subject: params.subject })])
        })
    })

    it.each([1, 3])('reschedules after %i SDK attempt(s) and sends its email payload on retry', async (attempts) => {
        environment?.setMaxAttempts(attempts)
        useService()
        ses.setError('TooManyRequestsException')
        invocation.queuePriority = 1

        const throttled = await service.executeSendEmail(invocation)

        expect(throttled).toMatchObject({
            finished: false,
            metrics: [],
            messageAssets: [],
            capturedPostHogEvents: [],
        })
        expect(throttled.error).toBeUndefined()
        expect(throttled.skipped).toBeUndefined()
        expect(throttled.invocation.queueParameters).toEqual(params)
        expect(throttled.invocation.queuePriority).toBe(1)
        expect(throttled.invocation.queueScheduledAt?.isValid).toBe(true)
        expect(throttled.invocation.state.vmState?.stack).toEqual([])
        expect(ses.requests).toHaveLength(attempts)
        expect(await ses.getEmails()).toEqual([])

        ses.setError(undefined)
        const retry = await service.executeSendEmail(throttled.invocation)

        expect(retry).toMatchObject({ finished: true })
        expect(retry.error).toBeUndefined()
        expect(retry.metrics).toEqual(
            expect.arrayContaining([expect.objectContaining({ metric_name: 'email_sent', count: 1 })])
        )
        expect(ses.requests).toHaveLength(attempts + 1)
        expect(ses.requests[attempts]).toMatchObject({
            FromEmailAddress: '"Example Sender" <sender@example.com>',
            Destination: {
                ToAddresses: [`"Example Recipient" <${params.to.email}>`],
                CcAddresses: ['copy@example.com'],
                BccAddresses: ['hidden@example.com'],
            },
            Content: {
                Simple: {
                    Subject: { Data: 'Local SES delivery', Charset: 'UTF-8' },
                    Body: {
                        Text: { Data: 'A plain text message.', Charset: 'UTF-8' },
                        Html: { Data: '<p>An HTML message.</p>', Charset: 'UTF-8' },
                    },
                },
            },
        })
        expect(await ses.getEmails()).toEqual([
            expect.objectContaining({ subject: 'Local SES delivery', body: { text: params.text, html: params.html } }),
        ])
    })

    it.each(['LimitExceededException', 'SendingPausedException'] as const)(
        'fails an HTTP %s without rescheduling or delivering mail',
        async (error) => {
            ses.setError(error)

            const result = await service.executeSendEmail(invocation)

            expect(result).toMatchObject({
                finished: true,
                error: `Failed to send email via SES: Local SES injected ${error}`,
                metrics: [expect.objectContaining({ metric_name: 'email_failed', count: 1 })],
            })
            expect(result.invocation.queueParameters).toBeUndefined()
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(ses.requests).toHaveLength(1)
            expect(await ses.getEmails()).toEqual([])
        }
    )
})
