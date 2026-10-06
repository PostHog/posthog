import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { insertHogFunctionTemplate, insertIntegration } from '~/cdp/_tests/fixtures'
import { createExampleHogFlowInvocation, insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'
import { invocationToV2JobInit, v2JobToInvocation } from '~/cdp/services/job-queue/job-queue-postgres-v2'
import { teamEmailCapBuckets } from '~/cdp/services/messaging/email.service'
import { RateLimiterService } from '~/cdp/services/rate-limiter/rate-limiter.service'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '~/cdp/types'
import * as redisV2 from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { assertRouterTargetsTestDatabase } from '~/tests/helpers/database-guard'
import { TestRedisV2 } from '~/tests/helpers/redis-v2'
import { LocalSes } from '~/tests/helpers/ses'
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
        let invocation: CyclotronJobInvocation
        const originalEnv = { ...process.env }

        const roundTrip = (item: CyclotronJobInvocation): CyclotronJobInvocation => {
            const job = invocationToV2JobInit(item)
            return v2JobToInvocation({
                ...job,
                id: item.id,
                queueName: job.queueName ?? 'hogflow',
                priority: job.priority ?? 0,
                functionId: job.functionId ?? null,
                state: job.state ?? null,
                scheduled: DateTime.fromJSDate(job.scheduled!),
                created: DateTime.now(),
                parentRunId: job.parentRunId ?? null,
                distinctId: job.distinctId ?? null,
                personId: job.personId ?? null,
                actionId: job.actionId ?? null,
                transitionCount: 0,
                cancelRequestedAt: null,
                ack: jest.fn(),
                fail: jest.fn(),
                reschedule: jest.fn(),
                cancel: jest.fn(),
                heartbeat: jest.fn(),
                bulkCreateAndCheckIn: jest.fn(),
            })
        }

        const processInvocation = async (item: CyclotronJobInvocation): Promise<CyclotronJobInvocationResult> => {
            const results = await worker.processInvocations([item])
            expect(results).toHaveLength(1)
            expect(results[0].error).toBeUndefined()
            results[0].invocation = roundTrip(results[0].invocation)
            return results[0]
        }

        const workflowBucket = (): { key: string; capacity: number; refillPerSecond: number } => ({
            key: `@posthog/workflow-email-rate/${flow.team_id}/${flow.id}`,
            capacity: 1,
            refillPerSecond: 1 / 3600,
        })

        const wakeAtScheduledTime = async (item: CyclotronJobInvocation): Promise<void> => {
            const wake = item.queueScheduledAt!.toMillis() + 1
            const elapsed = wake - Date.now()
            const keys = [
                workflowBucket().key,
                ...teamEmailCapBuckets(flow.team_id, 10, 20).map((bucket) => bucket.key),
            ]
            // Valkey's TIME ignores Date.now, so age its bucket timestamps by the same wait.
            await redis.useClient({ name: 'advance-email-buckets' }, async (client) => {
                for (const key of keys) {
                    for (const field of ['ts', 'resv']) {
                        const timestamp = await client.hget(key, field)
                        if (timestamp !== null) {
                            await client.hset(key, field, Number(timestamp) - elapsed)
                        }
                    }
                }
            })
            jest.spyOn(Date, 'now').mockReturnValue(wake)
        }

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
            process.env.AWS_ACCESS_KEY_ID = 'local-ses-test'
            process.env.AWS_SECRET_ACCESS_KEY = 'local-ses-test'
            delete process.env.AWS_SESSION_TOKEN
            delete process.env.AWS_PROFILE
            process.env.AWS_MAX_ATTEMPTS = '1'
            ses = new LocalSes()
            await ses.start()
            redis = new TestRedisV2({
                connection: {
                    url: hub.CDP_VALKEY_HOST,
                    options: { port: hub.CDP_VALKEY_PORT, password: hub.CDP_VALKEY_PASSWORD },
                },
                poolMinSize: 0,
                poolMaxSize: 1,
            })
            limiter = new RateLimiterService(redis, { name: 'email-round-trip-test' })
            const { team } = await createTestTeamFixture(hub.postgres)
            const emailTemplateId = `template-email-round-trip-${team.id}`
            const fetchTemplateId = `template-email-round-trip-fetch-${team.id}`
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
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO workflows_teamworkflowsconfig
                 (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                  email_sending_suspension_reason, ses_tenant_sending_status, email_sending_tier)
                 VALUES ($1, true, 'off', '', '', 0)`,
                [team.id],
                'test-create-workflows-config'
            )
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
            invocation = roundTrip({ ...createExampleHogFlowInvocation(flow), queuePriority: 2 })
        })

        afterEach(async () => {
            worker?.emailService.sesV2Client?.destroy()
            await worker?.stop()
            await redis?.close()
            await ses?.stop()
            process.env = { ...originalEnv }
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
                invocation = roundTrip({ ...createExampleHogFlowInvocation(flow), queuePriority: 2 })
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
            const routed = await processInvocation(invocation)
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
                const delayed = await processInvocation(retry)
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
                expect(
                    (delayed.invocation as CyclotronJobInvocationHogFlow).state.currentAction?.hogFunctionState?.vmState
                        ?.stack
                ).toEqual(
                    (routed.invocation as CyclotronJobInvocationHogFlow).state.currentAction?.hogFunctionState?.vmState
                        ?.stack
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
                await wakeAtScheduledTime(retry)
            }
            const resumed = await processInvocation(retry)
            results.push(resumed)
            expect(resumed.invocation).toMatchObject({
                queue: 'hogflow',
                queuePriority: 2,
                queueParameters: { type: 'fetch' },
            })
            expect(resumed.invocation.queueMetadata).toBeUndefined()
            const completed = await processInvocation(resumed.invocation)
            results.push(completed)
            expect(completed.finished).toBe(true)
            expect((completed.invocation as CyclotronJobInvocationHogFlow).state.currentAction?.id).toBe('exit')
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
