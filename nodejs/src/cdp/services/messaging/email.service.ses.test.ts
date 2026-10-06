import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import { AddressInfo, createServer } from 'node:net'
import SMTPTransport from 'nodemailer/lib/smtp-transport'

import { createExampleInvocation, insertIntegration } from '~/cdp/_tests/fixtures'
import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { TestRedisV2 } from '~/tests/helpers/redis-v2'
import { LocalSes } from '~/tests/helpers/ses'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub } from '../../../types'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
import { EmailSuppressionService, emailSuppressionConfigFromEnv } from './email-suppression.service'
import { EmailService, EmailServiceConfig, teamEmailCapBuckets } from './email.service'
import { mailDevTransport } from './helpers/maildev'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'
import { MessageAssetsService } from './message-assets.service'

describe('EmailService with local SES', () => {
    let hub: Hub
    let service: EmailService
    let invocation: CyclotronJobInvocationHogFunction
    let params: CyclotronInvocationQueueParametersEmailType
    let ses: LocalSes
    let redis: TestRedisV2
    let limiter: RateLimiterService
    let configService: TeamWorkflowsConfigService
    let suppression: EmailSuppressionService
    let assets: MessageAssetsService
    const hourlyCap = 4
    const dailyCap = 8
    const originalEnv = { ...process.env }

    const workflowBucket = (): { key: string; capacity: number; refillPerSecond: number } => ({
        key: `@posthog/workflow-email-rate/${invocation.teamId}/${invocation.functionId}`,
        capacity: 1,
        refillPerSecond: 1 / 3600,
    })

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

    const createService = (endpoint: string, config: Partial<EmailServiceConfig> = {}): EmailService =>
        new EmailService(
            {
                sesAccessKeyId: 'local-ses-test',
                sesSecretAccessKey: 'local-ses-test',
                sesRegion: 'us-east-1',
                sesEndpoint: endpoint,
                sesTrackedConfigurationSet: 'local-tracked',
                sesUntrackedConfigurationSet: 'local-untracked',
                teamEmailCapMode: 'off',
                teamEmailTierHourlyCaps: [hourlyCap],
                teamEmailTierDailyCaps: [dailyCap],
                ...config,
            },
            hub.integrationManager,
            configService,
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL),
            suppression,
            new RecipientsManagerService(hub.postgres),
            assets,
            limiter,
            limiter
        )

    beforeEach(async () => {
        process.env.AWS_ACCESS_KEY_ID = 'local-ses-test'
        process.env.AWS_SECRET_ACCESS_KEY = 'local-ses-test'
        delete process.env.AWS_SESSION_TOKEN
        delete process.env.AWS_PROFILE
        process.env.AWS_MAX_ATTEMPTS = '1'
        ses = new LocalSes()
        await ses.start()
        hub = await createHub({ SITE_URL: 'http://localhost:8000' })
        redis = new TestRedisV2({
            connection: {
                url: hub.CDP_VALKEY_HOST,
                options: { port: hub.CDP_VALKEY_PORT, password: hub.CDP_VALKEY_PASSWORD },
            },
            poolMinSize: 0,
            poolMaxSize: 1,
        })
        limiter = new RateLimiterService(redis, { name: 'email-outcomes-test' })
        configService = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
        suppression = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
        assets = new MessageAssetsService({
            produce: jest.fn().mockResolvedValue(undefined),
        } as unknown as IngestionOutputs<'message_assets'>)
        const { team } = await createTestTeamFixture(hub.postgres)
        const integration = await insertIntegration(hub.postgres, team.id, {
            kind: 'email',
            config: {
                email: 'sender@example.com',
                name: 'Example Sender',
                domain: 'example.com',
                verified: true,
                provider: 'ses',
            },
        })
        service = createService(ses.endpoint)
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
        invocation.state.vmState = {
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
        invocation.state.actionId = 'send-email'
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO workflows_teamworkflowsconfig
             (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
              email_sending_suspension_reason, ses_tenant_sending_status, email_sending_tier)
             VALUES ($1, true, 'off', '', '', 0)`,
            [team.id],
            'test-create-workflows-config'
        )
    })

    afterEach(async () => {
        service?.sesV2Client?.destroy()
        await redis?.close()
        await ses?.stop()
        if (hub) {
            await closeHub(hub)
        }
        process.env = { ...originalEnv }
        jest.restoreAllMocks()
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

    describe('rescheduled outcomes (M5)', () => {
        it.each(['workflow pacing', 'team cap', 'SES throttle'] as const)(
            'keeps the payload and priority without a send footprint after %s',
            async (cause) => {
                invocation.queuePriority = 1
                if (cause === 'workflow pacing') {
                    invocation.hogFunction.metadata!.email_sending_rate_limit = { count: 1, period: 'hour' }
                    await limiter.claimUpTo({ ...workflowBucket(), requested: 1 })
                } else if (cause === 'team cap') {
                    service.sesV2Client?.destroy()
                    service = createService(ses.endpoint, { teamEmailCapMode: 'enforce' })
                    const bucket = teamEmailCapBuckets(invocation.teamId, hourlyCap, dailyCap)[0]
                    await limiter.claimUpTo({ ...bucket, requested: bucket.capacity })
                } else {
                    ses.setError('TooManyRequestsException')
                }
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
                expect(result.invocation.queueParameters).toEqual(params)
                expect(result.invocation.queuePriority).toBe(1)
                expect(result.invocation.queueScheduledAt!.toMillis()).toBeGreaterThan(before)
                expect(result.invocation.state.vmState?.stack).toEqual([])
                expect(ses.requests).toHaveLength(cause === 'SES throttle' ? 1 : 0)
                expect(await ses.getEmails()).toEqual([])
            }
        )
    })

    describe('provider outcomes', () => {
        it.each([
            [
                'M6: unknown provider fails without delivery',
                'unknown',
                'Email provider not recognized. Select a different email integration.',
            ],
            ['M7: unsupported provider fails', 'unsupported', 'Email delivery mode not supported'],
        ])('%s', async (_name, provider, error) => {
            await setProvider(provider)

            const result = await service.executeSendEmail(invocation)

            expect(result.finished).toBe(true)
            expect(result.error).toBe(error)
            expect(result.logs).toEqual(
                expect.arrayContaining([expect.objectContaining({ level: 'error', message: error })])
            )
            expect(result.invocation.queueParameters).toBeUndefined()
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(result.invocation.state.vmState?.stack).toEqual([{ success: false }])
            expect(result.metrics.map((metric) => metric.metric_name)).toEqual(['email_failed'])
            expect(result.messageAssets).toHaveLength(0)
            expect(result.capturedPostHogEvents).toEqual([
                expect.objectContaining({ event: '$workflows_email_failed' }),
            ])
            expect(ses.requests).toEqual([])
            expect(await ses.getEmails()).toEqual([])
        })

        it('M8: records a maildev SMTP rejection as failed', async () => {
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

    describe('skip flags and unspent budgets (M9, M18, M21; billing policy in Silthus/posthog#313)', () => {
        it.each([
            ['suspended', 'email_suspended', undefined],
            ['paused', 'email_paused', true],
            ['suppressed to', 'email_suppressed', undefined],
            ['suppressed cc', 'email_suppressed', undefined],
            ['suppressed bcc', 'email_suppressed', undefined],
        ] as const)('%s keeps both budgets intact', async (gate, metric, skipped) => {
            service.sesV2Client?.destroy()
            service = createService(ses.endpoint, { teamEmailCapMode: 'enforce' })
            invocation.hogFunction.metadata!.email_sending_rate_limit = { count: 1, period: 'hour' }
            if (gate === 'suspended') {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE workflows_teamworkflowsconfig SET email_sending_suspended_at = NOW() WHERE team_id = $1',
                    [invocation.teamId],
                    'test-suspend-email-sending'
                )
            } else if (gate === 'paused') {
                invocation.hogFunction.metadata!.email_sending_paused_at = new Date().toISOString()
            } else {
                const address = gate === 'suppressed to' ? params.to.email : 'blocked@example.com'
                if (gate === 'suppressed cc') {
                    params.cc = 'allowed@example.com, "Blocked Copy" <BLOCKED@example.com>'
                } else if (gate === 'suppressed bcc') {
                    params.bcc = 'allowed@example.com, "Blocked Hidden" <BLOCKED@example.com>'
                }
                await suppression.recordHardBounces(invocation.teamId, [address])
            }

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
        it('M10: rejects an integration lookup fault instead of recording an outcome', async () => {
            failDatabaseQuery('fetchIntegrations')

            await expect(service.executeSendEmail(invocation)).rejects.toThrow('Database fault: fetchIntegrations')

            expect(invocation.state.vmState?.stack).toEqual([])
            expect(ses.requests).toEqual([])
            expect(await ses.getEmails()).toEqual([])
        })

        it('M11: reports tracking enabled on a failure before the tracking-off decision', async () => {
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
        it.each([0, 1])('M12: shadow mode sends despite bucket %i denying and charges both buckets', async (denied) => {
            service.sesV2Client?.destroy()
            service = createService(ses.endpoint, { teamEmailCapMode: 'shadow' })
            const buckets = teamEmailCapBuckets(invocation.teamId, hourlyCap, dailyCap)
            await limiter.claimUpTo({ ...buckets[denied], requested: buckets[denied].capacity })

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

        it.each(['failed', 'null'] as const)(
            'M13: sends without charging the team cap when the tier lookup is %s',
            async (fault) => {
                service.sesV2Client?.destroy()
                service = createService(ses.endpoint, { teamEmailCapMode: 'enforce' })
                invocation.state.globals.event.distinct_id = ''
                if (fault === 'failed') {
                    failDatabaseQuery('fetch-team-workflows-configs')
                } else {
                    jest.spyOn(configService, 'getEmailSendingTier').mockResolvedValue(null)
                }

                const result = await service.executeSendEmail(invocation)

                expect(result).toMatchObject({ finished: true })
                expect(result.error).toBeUndefined()
                expect(await ses.getEmails()).toHaveLength(1)
                for (const bucket of teamEmailCapBuckets(invocation.teamId, hourlyCap, dailyCap)) {
                    expect(await limiter.claimUpTo({ ...bucket, requested: bucket.capacity })).toBe(bucket.capacity)
                }
            }
        )

        it.each([
            { name: 'to only', copies: 1, hourly: 4, daily: 8, charged: 1 },
            { name: 'to, cc and bcc', copies: 3, hourly: 4, daily: 8, charged: 3 },
            { name: 'clamped to hourly capacity', copies: 3, hourly: 2, daily: 8, charged: 2 },
            { name: 'clamped to daily capacity', copies: 3, hourly: 4, daily: 2, charged: 2 },
        ])('M14: charges each recipient, $name', async ({ copies, hourly, daily, charged }) => {
            service.sesV2Client?.destroy()
            service = createService(ses.endpoint, {
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

    describe('tokens after rescheduling (M15, M16; refund policy in Silthus/posthog#295)', () => {
        it.each([
            {
                name: 'M15: team cap denial keeps the workflow token spent',
                cause: 'team cap',
                isTest: false,
                workflow: 0,
                hour: 0,
                day: 8,
            },
            {
                name: 'M15: SES throttle keeps both budgets spent',
                cause: 'SES throttle',
                isTest: false,
                workflow: 0,
                hour: 1,
                day: 5,
            },
            {
                name: 'M16: a throttled editor test reschedules without charging budgets',
                cause: 'SES throttle',
                isTest: true,
                workflow: 1,
                hour: 4,
                day: 8,
            },
        ])('$name', async ({ cause, isTest, workflow, hour, day }) => {
            service.sesV2Client?.destroy()
            service = createService(ses.endpoint, { teamEmailCapMode: 'enforce' })
            invocation.hogFunction.metadata!.email_sending_rate_limit = { count: 1, period: 'hour' }
            const buckets = teamEmailCapBuckets(invocation.teamId, hourlyCap, dailyCap)
            if (cause === 'team cap') {
                await limiter.claimUpTo({ ...buckets[0], requested: hourlyCap })
            } else {
                ses.setError('TooManyRequestsException')
            }

            const result = await service.executeSendEmail(invocation, isTest)

            expect(result).toMatchObject({ finished: false, metrics: [], messageAssets: [], capturedPostHogEvents: [] })
            expect(result.error).toBeUndefined()
            expect(result.skipped).toBeUndefined()
            expect(result.invocation.queueParameters).toEqual(params)
            expect(result.invocation.queueScheduledAt?.isValid).toBe(true)
            expect(result.invocation.state.vmState?.stack).toEqual([])
            expect(ses.requests).toHaveLength(cause === 'SES throttle' ? 1 : 0)
            expect(await ses.getEmails()).toEqual([])
            expect(await limiter.claimUpTo({ ...workflowBucket(), requested: 1, refillPerSecond: 0 })).toBe(workflow)
            for (const [index, bucket] of buckets.entries()) {
                expect(await limiter.claimUpTo({ ...bucket, requested: bucket.capacity, refillPerSecond: 0 })).toBe(
                    index === 0 ? hour : day
                )
            }
        })
    })

    describe('post-send faults (M19, M20; flip in Silthus/posthog#312)', () => {
        it.each(['engagement config', 'asset row'] as const)(
            'reports a failure after SES accepts when %s fails',
            async (stage) => {
                if (stage === 'engagement config') {
                    jest.spyOn(configService, 'shouldCaptureEngagementEvents').mockRejectedValue(
                        new Error('Engagement config fault')
                    )

                    await expect(service.executeSendEmail(invocation)).rejects.toThrow('Engagement config fault')
                } else {
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
                }
                expect(ses.requests).toHaveLength(1)
                expect(await ses.getEmails()).toEqual([expect.objectContaining({ subject: params.subject })])
            }
        )
    })

    it.each([1, 3])('reschedules after %i SDK attempt(s) and sends its email payload on retry', async (attempts) => {
        process.env.AWS_MAX_ATTEMPTS = String(attempts)
        service.sesV2Client?.destroy()
        service = createService(ses.endpoint)
        ses.setError('TooManyRequestsException')
        invocation.queuePriority = 1

        const throttled = await service.executeSendEmail(invocation)

        expect(throttled).toMatchObject({ finished: false, metrics: [] })
        expect(throttled.error).toBeUndefined()
        expect(throttled.invocation.queueParameters).toEqual(params)
        expect(throttled.invocation.queuePriority).toBe(1)
        expect(throttled.invocation.queueScheduledAt?.isValid).toBe(true)
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

    it('isolates concurrent proxy faults and inbox reads for identical recipients', async () => {
        const unrelatedClient = new SESv2Client({ region: 'us-east-1', endpoint: 'http://127.0.0.1:4566' })
        try {
            await unrelatedClient.send(
                new SendEmailCommand({
                    FromEmailAddress: 'sender@example.com',
                    Destination: { ToAddresses: [params.to.email] },
                    Content: {
                        Simple: {
                            Subject: { Data: 'Unrelated email without headers' },
                            Body: { Text: { Data: 'Another inbox writer.' } },
                        },
                    },
                })
            )
        } finally {
            unrelatedClient.destroy()
        }
        const otherSes = new LocalSes()
        await otherSes.start()
        const otherService = createService(otherSes.endpoint)
        ses.setError('TooManyRequestsException')

        try {
            const [throttled, delivered] = await Promise.all([
                service.executeSendEmail(invocation),
                otherService.executeSendEmail(invocation),
            ])
            expect(throttled).toMatchObject({ finished: false, metrics: [] })
            expect(delivered).toMatchObject({ finished: true })
            expect(delivered.error).toBeUndefined()
            expect(await ses.getEmails()).toEqual([])
            const otherEmails = await otherSes.getEmails()
            expect(otherEmails).toHaveLength(1)

            ses.setError(undefined)
            const retry = await service.executeSendEmail(throttled.invocation)
            expect(retry.error).toBeUndefined()
            const emails = await ses.getEmails()
            expect(emails).toHaveLength(1)
            expect(emails[0].destination).toEqual(otherEmails[0].destination)
            expect(emails[0].messageId).not.toBe(otherEmails[0].messageId)
            expect(await otherSes.getEmails()).toEqual(otherEmails)
            expect(ses.requests).toHaveLength(2)
            expect(otherSes.requests).toHaveLength(1)
        } finally {
            otherService.sesV2Client?.destroy()
            await otherSes.stop()
        }
    })
})
