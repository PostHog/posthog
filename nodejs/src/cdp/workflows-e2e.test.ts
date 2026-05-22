/**
 * Workflows E2E tests through postgres-v2 (Cyclotron node DB).
 *
 * These tests exercise the full hogflow lifecycle:
 *   event → CdpEventsConsumer → CyclotronJobQueue (produces to v2 DB)
 *   → CdpCyclotronWorkerHogFlow (polls v2 DB) → HogFlowExecutorService
 *   → results written back to v2 DB → logs/metrics to Kafka
 *
 * Only `fetch` is mocked. Everything else is real: v2 database, Kafka
 * producers, Postgres, Redis, person loading, filter evaluation, and
 * state serialization.
 */
import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { DateTime } from 'luxon'
import { Pool } from 'pg'

import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { resetKafka } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '../../src/config/kafka-topics'
import { KafkaProducerWrapper } from '../../src/kafka/producer'
import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { PostgresUse } from '../../src/utils/db/postgres'
import { PostgresPersonRepository } from '../../src/worker/ingestion/persons/repositories/postgres-person-repository'
import { FixtureHogFlowBuilder } from './_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from './_tests/examples'
import { createHogExecutionGlobals, insertHogFunctionTemplate } from './_tests/fixtures'
import { insertHogFlow } from './_tests/fixtures-hogflows'
import { CdpCyclotronWorkerHogFlow } from './consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpEventsConsumer } from './consumers/cdp-events.consumer'
import { HogFunctionInvocationGlobals } from './types'

// Mock the v1 Cyclotron native addon — it crashes on import locally.
// We only use postgres-v2 in these tests so v1 is not needed.
jest.mock('@posthog/cyclotron', () => ({
    CyclotronManager: jest.fn(),
    CyclotronWorker: jest.fn(),
}))

const ActualKafkaProducerWrapper = jest.requireActual('../../src/kafka/producer').KafkaProducerWrapper

// Use the same env var as config.ts (line 210-211) so the cleanup pool and hub always target the same DB
const CYCLOTRON_NODE_DB_URL =
    process.env.CYCLOTRON_NODE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

describe('Workflows E2E (postgres-v2)', () => {
    jest.setTimeout(30000)

    let eventsConsumer: CdpEventsConsumer
    let hogflowWorker: CdpCyclotronWorkerHogFlow

    let hub: Hub
    let kafkaProducer: KafkaProducerWrapper
    let mockProducerObserver: KafkaProducerObserver
    let team: Team
    let globals: HogFunctionInvocationGlobals
    let cyclotronPool: Pool

    beforeAll(() => {
        cyclotronPool = new Pool({ connectionString: CYCLOTRON_NODE_DB_URL })
    })

    afterAll(async () => {
        await cyclotronPool.end()
    })

    beforeEach(async () => {
        // Real Kafka producers for all CDP producer slots
        MockKafkaProducerWrapper.create = jest.fn((...args) => {
            return ActualKafkaProducerWrapper.create(...args)
        })

        await resetKafka()
        await resetTestDatabase()
        await cyclotronPool.query('DELETE FROM cyclotron_jobs')

        hub = await createHub()

        kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        mockProducerObserver = new KafkaProducerObserver(kafkaProducer)

        team = await getFirstTeam(hub.postgres)
        mockProducerObserver.resetKafkaProducer()

        // Route hogflow to postgres-v2, everything else to kafka
        hub.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING = 'hogflow:postgres-v2,*:kafka'
        hub.CDP_CYCLOTRON_BATCH_DELAY_MS = 50
        hub.CDP_FETCH_RETRIES = 2
        hub.CDP_FETCH_BACKOFF_BASE_MS = 50

        // Insert a simple fetch template for function actions
        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-workflows-e2e-fetch',
            name: 'Workflows E2E Fetch',
            code: `
            let res := fetch(inputs.url, {'method': inputs.method});
            print('Fetch result:', res.status);
            `,
            inputs_schema: [
                { key: 'url', type: 'string', required: true },
                { key: 'method', type: 'string', required: false },
            ],
        })

        const deps = createCdpConsumerDeps(hub, kafkaProducer)

        // Events consumer — only start as producer (skip Kafka consumer connection).
        // We call processBatch() directly so the Kafka consumer is not needed.
        eventsConsumer = new CdpEventsConsumer({ ...hub, CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: 'postgres-v2' }, deps)
        await (eventsConsumer as any).cyclotronJobQueue.startAsProducer()

        // Start hogflow worker (consumer side — polls v2 DB)
        hogflowWorker = new CdpCyclotronWorkerHogFlow(
            { ...hub, CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: 'postgres-v2' },
            deps
        )
        await hogflowWorker.start()

        mockFetch.mockResolvedValue({
            status: 200,
            headers: { 'Content-Type': 'application/json' },
            json: () => Promise.resolve({ success: true }),
            text: () => Promise.resolve(JSON.stringify({ success: true })),
            dump: () => Promise.resolve(),
        })
    })

    afterEach(async () => {
        await Promise.all([eventsConsumer?.stop() ?? Promise.resolve(), hogflowWorker?.stop() ?? Promise.resolve()])
        await kafkaProducer.disconnect()
        await closeHub(hub)
        mockProducerObserver.resetKafkaProducer()
    })

    // ── Helpers ──────────────────────────────────────────────────────

    function createGlobals(
        overrides: Partial<HogFunctionInvocationGlobals['event']> = {}
    ): HogFunctionInvocationGlobals {
        return createHogExecutionGlobals({
            project: { id: team.id } as any,
            event: {
                uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                event: '$pageview',
                properties: {
                    $current_url: 'https://posthog.com',
                    $lib_version: '1.0.0',
                },
                timestamp: '2024-09-03T09:00:00Z',
                ...overrides,
            } as any,
        })
    }

    async function queryCyclotronJobs(): Promise<any[]> {
        const result = await cyclotronPool.query('SELECT * FROM cyclotron_jobs ORDER BY created ASC')
        return result.rows
    }

    /** Send an event through the events consumer and wait for it to be queued to v2 */
    async function triggerWorkflow(eventGlobals: HogFunctionInvocationGlobals): Promise<void> {
        const { backgroundTask } = await eventsConsumer.processBatch([eventGlobals])
        await backgroundTask
    }

    /** Insert an active hogflow for the current team */
    async function createWorkflow(
        workflow: Parameters<FixtureHogFlowBuilder['withWorkflow']>[0],
        opts?: { name?: string }
    ): Promise<string> {
        const builder = new FixtureHogFlowBuilder().withTeamId(team.id).withStatus('active').withWorkflow(workflow)
        if (opts?.name) {
            builder.withName(opts.name)
        }
        const flow = builder.build()
        await insertHogFlow(hub.postgres, flow)
        return flow.id
    }

    // Reusable action configs
    const trigger = () =>
        ({
            type: 'trigger' as const,
            config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
        }) as const

    const fetchAction = (url: string, method = 'POST') => ({
        type: 'function' as const,
        config: {
            template_id: 'template-workflows-e2e-fetch',
            inputs: { url: { value: url }, method: { value: method } },
        },
    })

    const delayAction = (duration: string) => ({
        type: 'delay' as const,
        config: { delay_duration: duration },
    })

    const exitAction = () => ({ type: 'exit' as const, config: {} })

    describe('simple workflow: trigger → function → exit', () => {
        beforeEach(async () => {
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    function_1: fetchAction('https://example.com/webhook'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })
            globals = createGlobals()
        })

        it('should execute the workflow end-to-end through v2', async () => {
            await triggerWorkflow(globals)

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            expect(mockFetch).toHaveBeenCalledWith(
                'https://example.com/webhook',
                expect.objectContaining({ method: 'POST' })
            )

            // Verify metrics were produced to Kafka
            await waitForExpect(() => {
                const metrics = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                expect(metrics.length).toBeGreaterThanOrEqual(1)
            }, 5000)

            // Verify logs were produced to Kafka
            await waitForExpect(() => {
                const logs = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
                expect(logs.length).toBeGreaterThanOrEqual(1)
            }, 5000)
        })
    })

    describe('delay workflow: trigger → delay → function → exit', () => {
        beforeEach(async () => {
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    delay_1: delayAction('1s'),
                    function_1: fetchAction('https://example.com/delayed-webhook'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'delay_1', type: 'continue' },
                    { from: 'delay_1', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })
            globals = createGlobals()
        })

        it('should reschedule on delay and execute function after delay passes', async () => {
            await triggerWorkflow(globals)

            // First: worker picks up job and hits the delay — job gets rescheduled
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const rescheduled = jobs.filter(
                    (j: any) => j.status === 'available' && new Date(j.scheduled) > new Date()
                )
                expect(rescheduled.length).toBe(1)
            }, 5000)

            // Fetch should NOT have been called yet (delay hasn't passed)
            expect(mockFetch).not.toHaveBeenCalled()

            // Wait for the delay to pass and the worker to pick up the job again
            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            expect(mockFetch).toHaveBeenCalledWith(
                'https://example.com/delayed-webhook',
                expect.objectContaining({ method: 'POST' })
            )

            // Verify the job completed (transition_count > 1 due to reschedule)
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const terminal = jobs.filter(
                    (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
                )
                expect(terminal.length).toBeGreaterThanOrEqual(1)
            }, 5000)
        })
    })

    describe('conditional branch workflow', () => {
        beforeEach(async () => {
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    branch: {
                        type: 'conditional_branch',
                        config: {
                            conditions: [
                                { filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters },
                                { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters },
                            ],
                        },
                    },
                    function_a: fetchAction('https://example.com/branch-a'),
                    function_b: fetchAction('https://example.com/branch-b'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'branch', type: 'continue' },
                    { from: 'branch', to: 'function_a', type: 'branch', index: 0 },
                    { from: 'branch', to: 'function_b', type: 'branch', index: 1 },
                    { from: 'function_a', to: 'exit', type: 'continue' },
                    { from: 'function_b', to: 'exit', type: 'continue' },
                ],
            })
        })

        it('should take branch A when event matches the first condition', async () => {
            globals = createGlobals({
                event: '$pageview',
                properties: { $current_url: 'https://posthog.com/pricing' },
            })
            await triggerWorkflow(globals)

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            expect(mockFetch).toHaveBeenCalledWith('https://example.com/branch-a', expect.anything())
        })
    })

    describe('workflow disabled mid-execution', () => {
        let hogFlowId: string

        beforeEach(async () => {
            hogFlowId = await createWorkflow({
                actions: {
                    trigger: trigger(),
                    delay_1: delayAction('1s'),
                    function_1: fetchAction('https://example.com/should-not-fire'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'delay_1', type: 'continue' },
                    { from: 'delay_1', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })
            globals = createGlobals()
        })

        it('should cancel the job when workflow is archived during delay', async () => {
            await triggerWorkflow(globals)

            // Wait for the delay step to be hit (job rescheduled)
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                expect(jobs.some((j: any) => j.status === 'available' && new Date(j.scheduled) > new Date())).toBe(true)
            }, 5000)

            // Archive the hogflow while job is waiting
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogflow SET status = 'archived' WHERE id = $1`,
                [hogFlowId],
                'archiveHogFlow'
            )

            // Force the hogflow manager to reload
            ;(hogflowWorker as any).hogFlowManager.lazyLoader.markForRefresh(hogFlowId)

            // Wait for the delayed job to be picked up and canceled
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const canceled = jobs.filter((j: any) => j.status === 'canceled')
                expect(canceled.length).toBe(1)
            }, 10000)

            // Function should NOT have been called
            expect(mockFetch).not.toHaveBeenCalled()
        })
    })

    describe('multiple workflows matching same event', () => {
        const simpleFetchWorkflow = (url: string) => ({
            actions: {
                trigger: trigger(),
                function_1: fetchAction(url),
                exit: exitAction(),
            },
            edges: [
                { from: 'trigger', to: 'function_1', type: 'continue' as const },
                { from: 'function_1', to: 'exit', type: 'continue' as const },
            ],
        })

        beforeEach(async () => {
            await createWorkflow(simpleFetchWorkflow('https://example.com/workflow-a'), { name: 'Workflow A' })
            await createWorkflow(simpleFetchWorkflow('https://example.com/workflow-b'), { name: 'Workflow B' })
            globals = createGlobals()
        })

        it('should execute both workflows independently', async () => {
            await triggerWorkflow(globals)

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(2)
            }, 10000)

            const urls = mockFetch.mock.calls.map((call) => call[0])
            expect(urls).toContain('https://example.com/workflow-a')
            expect(urls).toContain('https://example.com/workflow-b')
        })
    })

    describe('wait_until_condition: condition matches immediately', () => {
        beforeEach(async () => {
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    wait_condition: {
                        type: 'wait_until_condition',
                        config: {
                            condition: {
                                // Matches $pageview with "posthog" in $current_url
                                filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
                            },
                            max_wait_duration: '10s',
                        },
                    },
                    function_matched: fetchAction('https://example.com/condition-matched'),
                    function_timeout: fetchAction('https://example.com/condition-timed-out'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'wait_condition', type: 'continue' },
                    { from: 'wait_condition', to: 'function_matched', type: 'branch', index: 0 },
                    { from: 'wait_condition', to: 'function_timeout', type: 'continue' },
                    { from: 'function_matched', to: 'exit', type: 'continue' },
                    { from: 'function_timeout', to: 'exit', type: 'continue' },
                ],
            })
            // Event matches the condition: $pageview with posthog in URL
            globals = createGlobals({
                event: '$pageview',
                properties: { $current_url: 'https://posthog.com' },
            })
        })

        it('should take the matched branch without rescheduling', async () => {
            await triggerWorkflow(globals)

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            // Should hit the matched branch, not the timeout branch
            expect(mockFetch).toHaveBeenCalledWith('https://example.com/condition-matched', expect.anything())
        })
    })

    describe('wait_until_condition: condition never matches, times out', () => {
        beforeEach(async () => {
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    wait_condition: {
                        type: 'wait_until_condition',
                        config: {
                            condition: {
                                // Requires $autocapture with "reload" in elements_chain_texts — won't match
                                filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters,
                            },
                            max_wait_duration: '2s',
                        },
                    },
                    function_1: fetchAction('https://example.com/after-wait-timeout'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'wait_condition', type: 'continue' },
                    { from: 'wait_condition', to: 'exit', type: 'branch', index: 0 },
                    { from: 'wait_condition', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })
            globals = createGlobals()
        })

        it('should reschedule while polling, then continue after max_wait expires', async () => {
            await triggerWorkflow(globals)

            // Job should be rescheduled (condition doesn't match, waiting for next poll)
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const rescheduled = jobs.filter(
                    (j: any) => j.status === 'available' && new Date(j.scheduled) > new Date()
                )
                expect(rescheduled.length).toBe(1)
            }, 5000)

            // Fetch should NOT be called yet — still waiting for condition
            expect(mockFetch).not.toHaveBeenCalled()

            // After max_wait (2s) expires, the condition times out and the workflow
            // continues to the function action via the continue edge
            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            expect(mockFetch).toHaveBeenCalledWith('https://example.com/after-wait-timeout', expect.anything())
        })
    })

    describe('wait_until_time_window: window in the future', () => {
        beforeEach(async () => {
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    wait_window: {
                        type: 'wait_until_time_window',
                        // UTC+14 with late-night window ensures it's always in the future
                        config: { timezone: 'Pacific/Kiritimati', day: 'any', time: ['23:50', '23:59'] },
                    },
                    function_1: fetchAction('https://example.com/after-time-window'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'wait_window', type: 'continue' },
                    { from: 'wait_window', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })
            globals = createGlobals()
        })

        it('should reschedule to the time window start and execute after it opens', async () => {
            await triggerWorkflow(globals)

            // Job should be rescheduled to the future time window
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const rescheduled = jobs.filter(
                    (j: any) => j.status === 'available' && new Date(j.scheduled) > new Date()
                )
                expect(rescheduled.length).toBe(1)
            }, 5000)

            // Fetch should NOT be called yet
            expect(mockFetch).not.toHaveBeenCalled()

            // Fast-forward: set the scheduled time to now so the worker picks it up
            await cyclotronPool.query(`UPDATE cyclotron_jobs SET scheduled = NOW() WHERE status = 'available'`)

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            expect(mockFetch).toHaveBeenCalledWith('https://example.com/after-time-window', expect.anything())
        })
    })

    describe('fetch failure with retries', () => {
        beforeEach(async () => {
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    function_1: fetchAction('https://example.com/failing-endpoint'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })

            mockFetch.mockResolvedValue({
                status: 500,
                headers: {},
                json: () => Promise.resolve({ error: 'Server error' }),
                text: () => Promise.resolve(JSON.stringify({ error: 'Server error' })),
                dump: () => Promise.resolve(),
            })

            globals = createGlobals()
        })

        it('should retry the fetch and eventually complete with error', async () => {
            await triggerWorkflow(globals)

            // Hogflow function actions retry fetch within a single execution cycle.
            // We expect at least 2 calls (initial + retry) before the workflow completes.
            await waitForExpect(() => {
                expect(mockFetch.mock.calls.length).toBeGreaterThanOrEqual(2)
            }, 15000)

            // Verify the workflow eventually reaches a terminal state
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const terminal = jobs.filter(
                    (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
                )
                expect(terminal.length).toBeGreaterThanOrEqual(1)
            }, 5000)
        })
    })

    describe('person data survives v2 round-trip', () => {
        beforeEach(async () => {
            const personRepository = new PostgresPersonRepository(hub.postgres)
            await personRepository.createPerson(
                DateTime.utc(),
                { email: 'test@example.com', name: 'Test User', plan: 'enterprise' },
                {},
                {},
                team.id,
                null,
                true,
                'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1',
                { distinctId: 'test-distinct-id' }
            )

            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-workflows-e2e-person',
                name: 'Workflows E2E Person',
                code: `fetch(inputs.url, { 'method': 'POST', 'body': inputs.body });`,
                inputs_schema: [
                    { key: 'url', type: 'string', required: true },
                    { key: 'body', type: 'string', required: true },
                ],
            })

            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    function_1: {
                        type: 'function',
                        config: {
                            template_id: 'template-workflows-e2e-person',
                            inputs: {
                                url: { value: 'https://example.com/person-test' },
                                body: {
                                    value: '{person.properties.email}',
                                    bytecode: ['_H', 1, 32, 'email', 32, 'properties', 32, 'person', 1, 3, 38],
                                },
                            },
                        },
                    },
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })

            globals = createGlobals({ distinct_id: 'test-distinct-id' })
        })

        it('should load person and pass properties to function action', async () => {
            await triggerWorkflow(globals)

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            // The fetch body should contain the person's email, proving person data
            // was loaded by the worker after deserializing the v2 job
            expect(mockFetch).toHaveBeenCalledWith(
                'https://example.com/person-test',
                expect.objectContaining({
                    body: 'test@example.com',
                    method: 'POST',
                })
            )
        })
    })
})
