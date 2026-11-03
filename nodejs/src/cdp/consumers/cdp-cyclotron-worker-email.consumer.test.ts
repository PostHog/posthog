import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'
import { register } from 'prom-client'

import { insertHogFunctionTemplate, insertIntegration } from '~/cdp/_tests/fixtures'
import { HogFlow } from '~/cdp/schema/hogflow'
import { invocationToV2JobInit, v2JobToInvocation } from '~/cdp/services/job-queue/job-queue-postgres-v2'
import { teamEmailCapBuckets } from '~/cdp/services/messaging/email-pacing'
import { RateLimiterService } from '~/cdp/services/rate-limiter/rate-limiter.service'
import { RedisV2 } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { assertRouterTargetsTestDatabase } from '~/tests/helpers/database-guard'
import { createEmailLimiterRedis, createEmailSender, insertEmailWorkflowsConfig } from '~/tests/helpers/email'
import { LocalSes, useLocalSesAwsEnvironment } from '~/tests/helpers/ses'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import {
    createExampleHogFlowInvocation,
    createHogFlowInvocationContext,
    insertHogFlow,
} from '../_tests/fixtures-hogflows'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { CdpCyclotronWorkerEmail } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(5000)

jest.mock('node:dns/promises', () => ({
    Resolver: jest.fn().mockImplementation(() => ({
        resolveMx: jest.fn().mockResolvedValue([{ exchange: 'mx.example.com', priority: 10 }]),
        resolve4: jest.fn().mockResolvedValue(['192.0.2.1']),
        resolve6: jest.fn().mockResolvedValue([]),
    })),
}))

describe('CdpCyclotronWorkerEmail', () => {
    let hub: Hub

    beforeAll(async () => {
        hub = await createHub()
    })

    afterAll(async () => {
        await closeHub(hub)
    })

    it('should set queue to email', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['queue']).toBe('email')
    })

    it('should extend CdpCyclotronWorkerHogFlow', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['name']).toBe('CdpCyclotronWorkerEmail')
    })

    describe('rescheduled emails through the v2 job codec', () => {
        let worker: CdpCyclotronWorkerEmail
        let ses: LocalSes
        let redis: RedisV2
        let limiter: RateLimiterService
        let flow: HogFlow
        let invocation: CyclotronJobInvocation

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
            // Valkey's TIME ignores Date.now. A deleted bucket is the state an idle bucket expires to: full.
            const keys = [workflowBucket().key, ...teamEmailCapBuckets(flow.team_id, 10, 20).map((b) => b.key)]
            await redis.useClient({ name: 'reset-email-buckets' }, async (client) => {
                for (const key of keys) {
                    await client.del(key)
                }
            })
            jest.spyOn(Date, 'now').mockReturnValue(item.queueScheduledAt!.toMillis() + 1)
        }

        const addFirstEmail = async (): Promise<void> => {
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

        const limitWorkflowRate = async (): Promise<void> => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                'UPDATE posthog_hogflow SET email_sending_rate_limit = $1 WHERE id = $2',
                [{ count: 1, period: 'hour' }, flow.id],
                'test-workflow-email-rate'
            )
        }

        const drainWorkflowBucket = async (): Promise<void> => {
            expect(await limiter.claimUpTo({ ...workflowBucket(), requested: 1 })).toBe(1)
        }

        const drainTeamHourlyCap = async (): Promise<void> => {
            const [hourly] = teamEmailCapBuckets(flow.team_id, 10, 20)
            expect(await limiter.claimUpTo({ ...hourly, requested: hourly.capacity })).toBe(hourly.capacity)
        }

        const queueWaitsByTeamCapped = async (): Promise<Record<string, number>> => {
            const counts: Record<string, number> = { true: 0, false: 0 }
            const metric = await register.getSingleMetric('cdp_email_queue_to_send_ms')!.get()
            for (const value of metric.values) {
                const name = 'metricName' in value ? value.metricName : undefined
                if (name === 'cdp_email_queue_to_send_ms_count' && value.labels.source === 'workflow') {
                    counts[String(value.labels.team_capped)] += value.value
                }
            }
            return counts
        }

        beforeEach(async () => {
            await assertRouterTargetsTestDatabase(hub.postgres, PostgresUse.COMMON_WRITE)
            jest.spyOn(Math, 'random').mockReturnValue(0)
            useLocalSesAwsEnvironment()
            ses = new LocalSes()
            await ses.start()
            redis = createEmailLimiterRedis(hub)
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
            invocation = roundTrip({ ...createExampleHogFlowInvocation(flow), queuePriority: 2 })
        })

        afterEach(async () => {
            worker?.emailService.sesV2Client?.destroy()
            await worker?.stop()
            // The worker does not own the injected pool, and RedisV2 has no close, so quit its one client here.
            await redis?.useClient({ name: 'email-round-trip-test-close' }, (client) => client.quit())
            await ses?.stop()
            jest.restoreAllMocks()
            mockFetch.mockClear()
        })

        it.each([
            {
                cause: 'an SES throttle',
                arrange: (): Promise<void> => Promise.resolve(ses.throttleNextRequests(2)),
                emails: 1,
                retries: 2,
                throttles: 2,
                sentBeforeRetry: 0,
                cappedSends: 0,
            },
            {
                cause: 'workflow pacing',
                arrange: async (): Promise<void> => {
                    await limitWorkflowRate()
                    await drainWorkflowBucket()
                },
                emails: 1,
                retries: 1,
                throttles: 0,
                sentBeforeRetry: 0,
                cappedSends: 0,
            },
            {
                cause: 'the team hourly cap',
                arrange: drainTeamHourlyCap,
                emails: 1,
                retries: 1,
                throttles: 0,
                sentBeforeRetry: 0,
                cappedSends: 1,
            },
            {
                cause: 'workflow pacing of the second email',
                arrange: async (): Promise<void> => {
                    await addFirstEmail()
                    await limitWorkflowRate()
                },
                emails: 2,
                retries: 1,
                throttles: 0,
                sentBeforeRetry: 1,
                cappedSends: 0,
            },
            {
                cause: 'the team hourly cap on the first of two emails',
                arrange: async (): Promise<void> => {
                    await addFirstEmail()
                    await drainTeamHourlyCap()
                },
                emails: 2,
                retries: 1,
                throttles: 0,
                sentBeforeRetry: 0,
                cappedSends: 1,
            },
        ])(
            'returns to the origin queue and priority after $cause',
            async ({ arrange, emails, retries, throttles, sentBeforeRetry, cappedSends }) => {
                await arrange()
                const waitsBefore = await queueWaitsByTeamCapped()
                const routed = await processInvocation(invocation)
                expect(routed.finished).toBe(false)
                expect(routed.invocation).toMatchObject({
                    queue: 'email',
                    queuePriority: 1,
                    queueParameters: { type: 'email' },
                    queueMetadata: { originQueue: 'hogflow', originPriority: 2 },
                })
                const params = routed.invocation.queueParameters
                const results = [routed]
                let retry = routed.invocation
                for (let attempt = 0; attempt < retries; attempt++) {
                    const before = DateTime.now().toMillis()
                    const delayed = await processInvocation(retry)
                    expect(delayed.finished).toBe(false)
                    expect(delayed.invocation).toMatchObject({
                        queue: 'email',
                        queuePriority: 1,
                        queueParameters: params,
                        queueMetadata: { originQueue: 'hogflow', originPriority: 2 },
                    })
                    expect(delayed.invocation.queueScheduledAt!.toMillis()).toBeGreaterThan(before)
                    expect(delayed.metrics.filter((metric) => metric.metric_name === 'email_sent')).toHaveLength(
                        sentBeforeRetry
                    )
                    expect(await ses.getEmails()).toHaveLength(sentBeforeRetry)
                    expect(
                        (delayed.invocation as CyclotronJobInvocationHogFlow).state.currentAction?.hogFunctionState
                            ?.vmState?.stack
                    ).toEqual(
                        (routed.invocation as CyclotronJobInvocationHogFlow).state.currentAction?.hogFunctionState
                            ?.vmState?.stack
                    )
                    results.push(delayed)
                    retry = delayed.invocation
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
                expect(metrics.filter((metric) => metric.metric_name === 'email_sent')).toHaveLength(emails)
                expect(metrics.filter((metric) => metric.metric_name === 'email_failed')).toEqual([])
                expect(results.flatMap((result) => result.capturedPostHogEvents).map((event) => event.event)).toEqual(
                    Array.from({ length: emails }, () => '$workflows_email_sent')
                )
                expect(await ses.getEmails()).toEqual(
                    Array.from({ length: emails }, () =>
                        expect.objectContaining({
                            subject: 'S2 round trip',
                            body: { text: 'Retry delivery', html: '<p>Retry delivery</p>' },
                        })
                    )
                )
                expect(ses.requests).toHaveLength(throttles + emails)
                // Only the send the team cap delayed reads as capped, never the email that follows it.
                const waitsAfter = await queueWaitsByTeamCapped()
                expect({
                    true: waitsAfter.true - waitsBefore.true,
                    false: waitsAfter.false - waitsBefore.false,
                }).toEqual({ true: cappedSends, false: throttles + emails - cappedSends })
                expect(mockFetch).toHaveBeenCalledTimes(1)
            },
            30000
        )
    })

    it.each([
        ['counts a job the transactional email API marked once, not again on its reschedule', true, [1, 0]],
        ['does not count a job without the mark', false, [0, 0]],
    ])('%s', async (_desc, marked, expectedTriggeredPerRun) => {
        const { team } = await createTestTeamFixture(hub.postgres)
        // The delay parks the run, so the second dequeue is a reschedule of the same job.
        const hogFlow: HogFlow = await insertHogFlow(
            hub.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withStatus('active')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'api' } },
                        delay: { type: 'delay', config: { delay_duration: '1h' } },
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [
                        { from: 'trigger', to: 'delay', type: 'continue' },
                        { from: 'delay', to: 'exit', type: 'continue' },
                    ],
                } as any)
                .build()
        )
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        const triggered = (result: CyclotronJobInvocationResult) =>
            result.metrics.filter((metric) => metric.metric_name === 'triggered')

        let job: CyclotronJobInvocation = {
            id: new UUIDT().toString(),
            teamId: team.id,
            functionId: hogFlow.id,
            queue: 'email',
            queuePriority: 0,
            state: createHogFlowInvocationContext({
                event: { distinct_id: 'distinct_A_1', properties: { to: 'user@example.com' } } as any,
                ...(marked ? { triggerMetricPending: true } : {}),
            }),
        }
        const triggeredPerRun: CyclotronJobInvocationResult['metrics'][] = []
        for (let run = 0; run < 2; run++) {
            const [result] = await worker.processInvocations([job])
            expect(result.finished).toBe(false)
            triggeredPerRun.push(triggered(result))
            // The job queue persists the result's state as JSON, and the next dequeue reads it back.
            job = { ...job, state: parseJSON(JSON.stringify(result.invocation.state)) }
        }

        expect(triggeredPerRun.map((metrics) => metrics.length)).toEqual(expectedTriggeredPerRun)
        expect(triggeredPerRun.flat()).toEqual(
            marked
                ? [
                      {
                          team_id: team.id,
                          app_source_id: hogFlow.id,
                          metric_kind: 'other',
                          metric_name: 'triggered',
                          count: 1,
                      },
                  ]
                : []
        )
    })
})
