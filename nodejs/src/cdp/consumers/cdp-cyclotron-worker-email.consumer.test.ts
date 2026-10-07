import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { insertHogFunctionTemplate, insertIntegration } from '~/cdp/_tests/fixtures'
import { createExampleHogFlowInvocation, insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'
import { teamEmailCapBuckets } from '~/cdp/services/messaging/email.service'
import { RateLimiterService } from '~/cdp/services/rate-limiter/rate-limiter.service'
import * as redisV2 from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { assertRouterTargetsTestDatabase } from '~/tests/helpers/database-guard'
import { createEmailSender, createEmailValidationRedis, insertEmailWorkflowsConfig } from '~/tests/helpers/email'
import { EmailQueueInvocation, EmailQueueRoundTrip, EmailRetryClock } from '~/tests/helpers/email-queue'
import { TestRedisV2 } from '~/tests/helpers/redis-v2'
import { LocalSes, LocalSesAwsEnvironment } from '~/tests/helpers/ses'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub } from '../../types'
import { CdpCyclotronWorkerEmail } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(30000)

jest.mock('node:dns/promises', () => ({
    Resolver: jest.fn().mockImplementation(() => ({
        resolveMx: jest.fn().mockResolvedValue([{ exchange: 'mx.example.com', priority: 10 }]),
        resolve4: jest.fn().mockResolvedValue(['192.0.2.1']),
        resolve6: jest.fn().mockResolvedValue([]),
    })),
}))

describe('CdpCyclotronWorkerEmail', () => {
    let hub: Hub
    let pools: TestRedisV2[]

    beforeAll(async () => {
        hub = await createHub()
    })

    afterAll(async () => {
        await closeHub(hub)
    })

    beforeEach(() => {
        pools = []
        jest.spyOn(redisV2, 'createRedisV2PoolFromConfig').mockImplementation((config) => {
            const pool = new TestRedisV2(config)
            pools.push(pool)
            return pool
        })
    })

    afterEach(async () => {
        await Promise.all(pools.map((pool) => pool.close()))
        jest.restoreAllMocks()
    })

    describe('construction', () => {
        let worker: CdpCyclotronWorkerEmail

        beforeEach(() => {
            worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        })

        afterEach(async () => {
            worker.emailService.sesV2Client?.destroy()
            await worker.stop()
        })

        it('should set queue to email', () => {
            expect(worker['queue']).toBe('email')
        })

        it('should extend CdpCyclotronWorkerHogFlow', () => {
            expect(worker['name']).toBe('CdpCyclotronWorkerEmail')
        })
    })

    describe('rescheduled emails through the v2 job codec preserve origin queue and priority (M17)', () => {
        let worker: CdpCyclotronWorkerEmail
        let ses: LocalSes
        let redis: TestRedisV2
        let limiter: RateLimiterService
        let flow: HogFlow
        let invocation: EmailQueueInvocation
        let environment: LocalSesAwsEnvironment
        let queue: EmailQueueRoundTrip
        let retryClock: EmailRetryClock

        const workflowBucket = (): { key: string; capacity: number; refillPerSecond: number } => ({
            key: `@posthog/workflow-email-rate/${flow.team_id}/${flow.id}`,
            capacity: 1,
            refillPerSecond: 1 / 3600,
        })

        const pauseWorkflow = async (): Promise<void> => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogflow SET email_sending_paused_at = now(),
                 email_sending_paused_reason = 'Sending paused during retry' WHERE id = $1`,
                [flow.id],
                'test-pause-workflow-email'
            )
            const reloaded = new Promise<void>((resolve) => {
                hub.pubSub['eventEmitter'].once('reload-hog-flows', () => resolve())
            })
            await hub.pubSub.publish(
                'reload-hog-flows',
                JSON.stringify({ teamId: flow.team_id, hogFlowIds: [flow.id] })
            )
            await reloaded
        }

        beforeEach(async () => {
            await assertRouterTargetsTestDatabase(hub.postgres, PostgresUse.COMMON_WRITE)
            jest.spyOn(Math, 'random').mockReturnValue(0)
            environment = new LocalSesAwsEnvironment()
            environment.configure()
            ses = new LocalSes()
            await ses.start()
            redis = createEmailValidationRedis(hub)
            limiter = new RateLimiterService(redis, { name: 'email-round-trip-test' })
            const { team } = await createTestTeamFixture(hub.postgres)
            const emailTemplateId = `template-email-round-trip-${team.id}`
            const fetchTemplateId = `template-email-round-trip-fetch-${team.id}`
            const integration = await insertIntegration(hub.postgres, team.id, createEmailSender())
            await insertHogFunctionTemplate(hub.postgres, {
                id: emailTemplateId,
                name: 'Email round trip',
                code: 'sendEmail(inputs.email)',
                inputs_schema: [{ key: 'email', type: 'native_email', label: 'Email', required: true }],
            })
            await insertHogFunctionTemplate(hub.postgres, {
                id: fetchTemplateId,
                name: 'Fetch after email',
                code: "return fetch(inputs.url, {'method': inputs.method});",
                inputs_schema: [
                    { key: 'url', type: 'string', label: 'URL', required: true },
                    { key: 'method', type: 'string', label: 'Method', required: true },
                ],
            })
            flow = new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withExitCondition('exit_only_at_end')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'event', filters: {} } },
                        email: {
                            type: 'function_email',
                            config: {
                                template_id: emailTemplateId,
                                inputs: {
                                    email: {
                                        value: {
                                            from: { integrationId: integration.id },
                                            to: {
                                                email: 'recipient@round-trip.example.com',
                                                name: 'Example Recipient',
                                            },
                                            subject: 'S2 round trip',
                                            text: 'Retry delivery',
                                            html: '<p>Retry delivery</p>',
                                        },
                                    },
                                },
                            },
                        },
                        fetch: {
                            type: 'function',
                            config: {
                                template_id: fetchTemplateId,
                                inputs: {
                                    url: { value: 'https://example.com/after-email' },
                                    method: { value: 'POST' },
                                },
                            },
                        },
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [
                        { from: 'trigger', to: 'email', type: 'continue' },
                        { from: 'email', to: 'fetch', type: 'continue' },
                        { from: 'fetch', to: 'exit', type: 'continue' },
                    ],
                })
                .build()
            await insertHogFlow(hub.postgres, flow)
            await insertEmailWorkflowsConfig(hub, team.id)
            const deps = { ...createCdpConsumerDeps(hub), emailValidationValkey: redis }
            worker = new CdpCyclotronWorkerEmail(
                {
                    ...hub,
                    SES_REGION: 'us-east-1',
                    SES_ENDPOINT: ses.endpoint,
                    EMAIL_TEAM_SENDING_CAP_MODE: 'enforce',
                    EMAIL_TEAM_SENDING_CAP_HOURLY_BY_TIER: '10',
                    EMAIL_TEAM_SENDING_CAP_DAILY_BY_TIER: '20',
                },
                deps,
                createMockJobQueue()
            )
            queue = new EmailQueueRoundTrip(worker)
            retryClock = new EmailRetryClock(redis, [
                workflowBucket().key,
                ...teamEmailCapBuckets(flow.team_id, 10, 20).map((bucket) => bucket.key),
            ])
            invocation = EmailQueueRoundTrip.encodeAndDecode({
                ...createExampleHogFlowInvocation(flow),
                queuePriority: 2,
            })
        })

        afterEach(async () => {
            worker?.emailService.sesV2Client?.destroy()
            await worker?.stop()
            await redis?.close()
            await ses?.stop()
            environment.restore()
            jest.restoreAllMocks()
            mockFetch.mockClear()
        })

        it.each([
            { case: 'M1', cause: 'SES throttle', attempts: 2, outcome: 'sends once' },
            { case: 'M2', cause: 'workflow pacing', attempts: 1, outcome: 'sends once' },
            { case: 'M3', cause: 'team hourly cap', attempts: 1, outcome: 'sends once' },
            { case: 'M3', cause: 'team daily cap', attempts: 2, outcome: 'sends once' },
            { case: 'M4', cause: 'SES throttle', attempts: 1, outcome: 'skips a paused workflow' },
            { case: 'M4', cause: 'workflow pacing', attempts: 1, outcome: 'skips a paused workflow' },
            { case: 'M4', cause: 'team hourly cap', attempts: 1, outcome: 'skips a paused workflow' },
            {
                case: 'M17 consecutive emails',
                cause: 'workflow pacing',
                attempts: 1,
                outcome: 'sends second email once',
            },
        ])('$case: $cause retries through the codec and $outcome', async ({ cause, attempts, outcome }) => {
            const paused = outcome === 'skips a paused workflow'
            const consecutive = outcome === 'sends second email once'
            if (consecutive) {
                const emailAction = flow.actions.find((action) => action.id === 'email')!
                flow.actions.push({ ...emailAction, id: 'first-email' })
                flow.edges = [
                    { from: 'trigger', to: 'first-email', type: 'continue' },
                    { from: 'first-email', to: 'email', type: 'continue' },
                    ...flow.edges.filter((edge) => edge.from !== 'trigger'),
                ]
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE posthog_hogflow SET actions = $1, edges = $2 WHERE id = $3',
                    [JSON.stringify(flow.actions), JSON.stringify(flow.edges), flow.id],
                    'test-consecutive-workflow-emails'
                )
                invocation = EmailQueueRoundTrip.encodeAndDecode({
                    ...createExampleHogFlowInvocation(flow),
                    queuePriority: 2,
                })
            }
            if (cause === 'workflow pacing') {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    'UPDATE posthog_hogflow SET email_sending_rate_limit = $1 WHERE id = $2',
                    [{ count: 1, period: 'hour' }, flow.id],
                    'test-workflow-email-rate'
                )
                if (!consecutive) {
                    expect(await limiter.claimUpTo({ ...workflowBucket(), requested: 1 })).toBe(1)
                }
            }
            if (cause.startsWith('team')) {
                const bucket = teamEmailCapBuckets(flow.team_id, 10, 20)[cause === 'team hourly cap' ? 0 : 1]
                expect(await limiter.claimUpTo({ ...bucket, requested: bucket.capacity })).toBe(bucket.capacity)
            }
            const routed = await queue.process(invocation)
            expect(routed.finished).toBe(false)
            expect(routed.invocation).toMatchObject({
                queue: 'email',
                queuePriority: 1,
                queueParameters: { type: 'email' },
                queueMetadata: { originQueue: 'hogflow', originPriority: 2 },
            })
            if (cause === 'SES throttle') {
                ses.throttleNextRequests(attempts)
            }
            const params = routed.invocation.queueParameters
            const results = [routed]
            let retry = routed.invocation
            for (let attempt = 0; attempt < attempts; attempt++) {
                const before = DateTime.now().toMillis()
                const delayed = await queue.process(retry)
                expect(delayed.finished).toBe(false)
                expect(delayed.invocation).toMatchObject({
                    queue: 'email',
                    queuePriority: 1,
                    queueParameters: params,
                })
                expect(delayed.invocation.queueMetadata).toEqual({ originQueue: 'hogflow', originPriority: 2 })
                expect(delayed.invocation.queueScheduledAt!.toMillis()).toBeGreaterThan(before)
                if (consecutive) {
                    expect(delayed.metrics.filter((metric) => metric.metric_name === 'email_sent')).toEqual([
                        expect.objectContaining({ count: 1 }),
                    ])
                    expect(delayed.messageAssets).toHaveLength(1)
                    expect(delayed.capturedPostHogEvents.map((event) => event.event)).toEqual(['$workflows_email_sent'])
                } else {
                    expect(delayed.metrics).toEqual([])
                    expect(delayed.messageAssets).toEqual([])
                    expect(delayed.capturedPostHogEvents).toEqual([])
                }
                expect(delayed.invocation.state?.currentAction?.hogFunctionState?.vmState?.stack).toEqual(
                    routed.invocation.state?.currentAction?.hogFunctionState?.vmState?.stack
                )
                if (consecutive) {
                    expect(await ses.getEmails()).toEqual([
                        expect.objectContaining({
                            subject: 'S2 round trip',
                            body: { text: 'Retry delivery', html: '<p>Retry delivery</p>' },
                        }),
                    ])
                } else {
                    expect(await ses.getEmails()).toEqual([])
                }
                results.push(delayed)
                retry = delayed.invocation
                if (paused) {
                    await pauseWorkflow()
                }
                await retryClock.wake(retry)
            }
            const resumed = await queue.process(retry)
            results.push(resumed)
            expect(resumed.invocation).toMatchObject({
                queue: 'hogflow',
                queuePriority: 2,
                queueParameters: { type: 'fetch' },
            })
            expect(resumed.invocation.queueMetadata).toBeUndefined()
            const completed = await queue.process(resumed.invocation)
            results.push(completed)
            expect(completed.finished).toBe(true)
            expect(completed.invocation.state?.currentAction?.id).toBe('exit')
            const metrics = results.flatMap((result) => result.metrics)
            const sentCount = paused ? 0 : consecutive ? 2 : 1
            expect(metrics.filter((metric) => metric.metric_name === 'email_sent')).toEqual(
                Array.from({ length: sentCount }, () => expect.objectContaining({ count: 1 }))
            )
            expect(metrics.filter((metric) => metric.metric_name === 'email_paused')).toEqual(
                paused ? [expect.objectContaining({ count: 1 })] : []
            )
            expect(metrics.filter((metric) => metric.metric_name === 'email_failed')).toEqual([])
            expect(results.flatMap((result) => result.capturedPostHogEvents).map((event) => event.event)).toEqual(
                Array.from({ length: sentCount }, () => '$workflows_email_sent')
            )
            expect(await ses.getEmails()).toEqual(
                Array.from({ length: sentCount }, () =>
                    expect.objectContaining({
                        subject: 'S2 round trip',
                        body: { text: 'Retry delivery', html: '<p>Retry delivery</p>' },
                    })
                )
            )
            expect(ses.requests).toHaveLength((cause === 'SES throttle' ? attempts : 0) + sentCount)
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })
    })
})
