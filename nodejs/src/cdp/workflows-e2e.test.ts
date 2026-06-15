/**
 * Workflows E2E tests through postgres-v2 (Cyclotron node DB).
 *
 * These tests exercise the full hogflow lifecycle:
 *   event → CdpEventsConsumer → CyclotronJobQueuePostgresV2 (produces to v2 DB)
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
import { HogFlow } from '../../src/schema/hogflow'
import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { PostgresUse } from '../../src/utils/db/postgres'
import { UUIDT } from '../../src/utils/utils'
import {
    InternalPersonWithDistinctId,
    PersonReadRepository,
} from '../../src/worker/ingestion/persons/repositories/person-repository'
import { FixtureHogFlowBuilder } from './_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from './_tests/examples'
import { createHogExecutionGlobals, insertHogFunctionTemplate, insertIntegration } from './_tests/fixtures'
import { insertHogFlow } from './_tests/fixtures-hogflows'
import { CdpCyclotronWorkerEmail } from './consumers/cdp-cyclotron-worker-email.consumer'
import { CdpCyclotronWorkerHogFlow } from './consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpEventsConsumer } from './consumers/cdp-events.consumer'
import { CdpHogflowSubscriptionMatcherConsumer } from './consumers/cdp-hogflow-subscription-matcher.consumer'
import { CyclotronJobQueueKafka } from './services/job-queue/job-queue-kafka'
import { CyclotronJobQueuePostgres } from './services/job-queue/job-queue-postgres'
import { CyclotronJobQueuePostgresV2 } from './services/job-queue/job-queue-postgres-v2'
import { JobQueue } from './services/job-queue/job-queue.interface'
import { HogFunctionInvocationGlobals } from './types'
import { convertBatchHogFlowRequestToHogFunctionInvocationGlobals } from './utils'
import { convertToHogFunctionFilterGlobal } from './utils/hog-function-filtering'

const ActualKafkaProducerWrapper = jest.requireActual('../../src/kafka/producer').KafkaProducerWrapper

// Use the same env vars as config.ts (lines 221-229) so cleanup pools and hub target the same DBs
const CYCLOTRON_NODE_DB_URL =
    process.env.CYCLOTRON_NODE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'
const CYCLOTRON_DB_URL =
    process.env.CYCLOTRON_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron'

describe.each(['postgres-v2' as const, 'postgres' as const])('Workflows E2E (%s)', (mode) => {
    jest.setTimeout(30000)

    let eventsConsumer: CdpEventsConsumer
    let hogflowWorker: CdpCyclotronWorkerHogFlow
    let hogflowQueue: JobQueue

    let hub: Hub
    let kafkaProducer: KafkaProducerWrapper
    let mockProducerObserver: KafkaProducerObserver
    let team: Team
    let globals: HogFunctionInvocationGlobals
    let mockPersonRepo: jest.Mocked<PersonReadRepository>
    let cyclotronPool: Pool
    let deps: ReturnType<typeof createCdpConsumerDeps>

    beforeAll(() => {
        cyclotronPool = new Pool({
            connectionString: mode === 'postgres-v2' ? CYCLOTRON_NODE_DB_URL : CYCLOTRON_DB_URL,
        })
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

        mockPersonRepo = {
            fetchPerson: jest.fn().mockResolvedValue(undefined),
            fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonsByPersonIds: jest.fn().mockResolvedValue([]),
            fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
        }

        deps = { ...createCdpConsumerDeps(hub, kafkaProducer), personRepository: mockPersonRepo }

        const kafkaQueue = new CyclotronJobQueueKafka(hub.KAFKA_CLIENT_RACK, hub, hub.CONSUMER_BATCH_SIZE)

        // Build the hogflow queue for the current mode
        if (mode === 'postgres-v2') {
            hogflowQueue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)
        } else {
            hogflowQueue = new CyclotronJobQueuePostgres(hub.CONSUMER_BATCH_SIZE, hub)
        }

        // Events consumer — only start as producer (skip Kafka consumer connection).
        // We call processBatch() directly so the Kafka consumer is not needed.
        eventsConsumer = new CdpEventsConsumer(hub, deps, {
            hogQueue: kafkaQueue,
            hogflowQueue,
        })
        await Promise.all([kafkaQueue.startAsProducer(), hogflowQueue.startAsProducer()])

        // Start hogflow worker (consumer side — polls from the mode's backend)
        hogflowWorker = new CdpCyclotronWorkerHogFlow(hub, deps, hogflowQueue)
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

    // v1 stores lifecycle in `state` (and vm payload in `vm_state`);
    // v2 stores lifecycle in `status` (and state payload in `state`).
    // Normalize so tests can use `.status` regardless of mode.
    const statusColumn = mode === 'postgres-v2' ? 'status' : 'state'

    async function queryCyclotronJobs(): Promise<any[]> {
        const result = await cyclotronPool.query(
            `SELECT *, ${statusColumn} AS status FROM cyclotron_jobs ORDER BY created ASC`
        )
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
        const flow = await createWorkflowFlow(workflow, opts)
        return flow.id
    }

    /** Same as createWorkflow but returns the full HogFlow object (useful for hand-built invocations) */
    async function createWorkflowFlow(
        workflow: Parameters<FixtureHogFlowBuilder['withWorkflow']>[0],
        opts?: { name?: string }
    ): Promise<HogFlow> {
        const builder = new FixtureHogFlowBuilder().withTeamId(team.id).withStatus('active').withWorkflow(workflow)
        if (opts?.name) {
            builder.withName(opts.name)
        }
        const flow = builder.build()
        await insertHogFlow(hub.postgres, flow)
        return flow
    }

    /**
     * Construct and enqueue a batch-shaped CyclotronJobInvocation directly, mimicking what
     * CdpBatchHogFlowRequestsConsumer.createHogFlowInvocation would produce. Skips the
     * blast-radius API call so tests don't need to stand up the Django side.
     */
    async function triggerBatchWorkflow(hogFlow: HogFlow, personUuid: string): Promise<void> {
        const invocationGlobals = convertBatchHogFlowRequestToHogFunctionInvocationGlobals({
            team,
            personId: personUuid,
            siteUrl: hub.SITE_URL,
        })
        const filterGlobals = convertToHogFunctionFilterGlobal(invocationGlobals)
        const invocation = {
            id: new UUIDT().toString(),
            state: {
                event: invocationGlobals.event,
                personId: personUuid,
                actionStepCount: 0,
                variables: {},
            },
            teamId: team.id,
            functionId: hogFlow.id,
            parentRunId: new UUIDT().toString(),
            hogFlow,
            person: invocationGlobals.person,
            filterGlobals,
            queue: 'hogflow' as const,
            queuePriority: 1,
        }
        await hogflowQueue.queueInvocations([invocation])
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

    // Mirrors what HogFlowSerializer compiles for {events: [{id: <name>}]}: a single
    // equality check on the `event` global. The matcher is fail-closed when bytecode
    // is absent, so fixtures must supply it the same way Django would on save.
    const eventNameBytecode = (eventName: string): any[] => ['_H', 1, 32, eventName, 32, 'event', 1, 1, 11]
    const eventNameFilter = (eventName: string) => ({
        filters: { events: [{ id: eventName }], bytecode: eventNameBytecode(eventName) },
    })
    // An action-based wait entry: the editor's Actions picker yields a filter with `actions` set and
    // `events` empty. Django compiles the action's match conditions into bytecode the same way.
    const actionFilter = (eventName: string, actionId: number) => ({
        filters: { actions: [{ id: actionId, type: 'actions' }], events: [], bytecode: eventNameBytecode(eventName) },
    })
    // The state left when the last event is removed from a wait entry in the UI: no events, no
    // actions. Empty filters compile to always-true bytecode (op 29), which must NOT wake on every
    // event. ['_H', 1, 29] is exactly what the Django compiler emits for empty filters.
    const emptyEventFilter = () => ({ filters: { events: [], bytecode: ['_H', 1, 29] } })
    // A wait CONDITION with no property filters: the state left when a condition's last filter is
    // removed, or one is added but never filled in. Django compiles it to the same always-true
    // bytecode (op 29). Unlike an events entry, the executor evaluates the condition on entry, so
    // without the guard this fires the wait immediately. Mirrors the serializer's compiled shape.
    const emptyConditionFilters = () => ({ bytecode: ['_H', 1, 29], properties: [] })

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

    // The matcher reads parked jobs via `CYCLOTRON_NODE_DATABASE_URL` (the postgres-v2 backend).
    // In legacy `postgres` mode the worker parks the job in a different DB the matcher cannot see,
    // so wakes are postgres-v2-only.
    const describeMatcher = mode === 'postgres-v2' ? describe : describe.skip
    describeMatcher('wait_until_condition: subscription matcher wakes parked jobs', () => {
        let matcher: CdpHogflowSubscriptionMatcherConsumer

        // trigger → wait_condition → (matched branch | timeout continue) → exit
        const createWaitUntilWorkflow = (waitConfig: Record<string, any>): Promise<string> =>
            createWorkflow({
                actions: {
                    trigger: trigger(),
                    wait_condition: { type: 'wait_until_condition', config: waitConfig },
                    function_matched: fetchAction('https://example.com/condition-matched'),
                    function_timeout: fetchAction('https://example.com/timed-out'),
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

        // The job is parked when it is available with a scheduled time in the future.
        const expectParked = async (): Promise<void> => {
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                expect(jobs.some((j: any) => j.status === 'available' && new Date(j.scheduled) > new Date())).toBe(true)
            }, 5000)
            expect(mockFetch).not.toHaveBeenCalled()
        }

        beforeEach(() => {
            matcher = new CdpHogflowSubscriptionMatcherConsumer({ ...hub }, deps)
        })

        afterEach(async () => {
            await matcher?.stop().catch(() => {})
        })

        it('wakes a parked job and takes the matched branch when a subscribed event fires', async () => {
            await createWaitUntilWorkflow({
                // Property condition never matches the trigger event, so the job parks.
                condition: { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters },
                events: [eventNameFilter('wakeup_event')],
                max_wait_duration: '5m',
            })
            await triggerWorkflow(createGlobals())
            await expectParked()

            // A subscribed event fires for this person — the matcher wakes the job.
            await matcher.processBatch([createGlobals({ event: 'wakeup_event' })])

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)
            expect(mockFetch).toHaveBeenCalledWith('https://example.com/condition-matched', expect.anything())
        })

        it('wakes a parked job whose wait entry is action-based (events empty, actions + bytecode set)', async () => {
            await createWaitUntilWorkflow({
                // Property condition never matches the trigger event, so the job parks.
                condition: { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters },
                // "Events to wait for" entry targets a PostHog Action: filters.events is empty,
                // filters.actions is set, and the compiled bytecode matches the action's event.
                events: [actionFilter('action_wakeup_event', 3)],
                max_wait_duration: '5m',
            })
            await triggerWorkflow(createGlobals())
            await expectParked()

            // The action's underlying event fires — the matcher must wake the job via the action
            // entry even though filters.events is empty.
            await matcher.processBatch([createGlobals({ event: 'action_wakeup_event' })])

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)
            expect(mockFetch).toHaveBeenCalledWith('https://example.com/condition-matched', expect.anything())
        })

        it('wakes a parked job when a later event satisfies the property condition', async () => {
            await createWaitUntilWorkflow({
                // No events list — only a property-based condition. The matcher evaluates the
                // condition against every incoming event, making property waits event-driven.
                condition: { filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters },
                max_wait_duration: '5m',
            })
            // Trigger with an event that does not satisfy the condition, so the job parks.
            await triggerWorkflow(createGlobals({ event: 'custom_trigger', properties: {} }))
            await expectParked()

            // A later $pageview with a posthog URL satisfies the property condition.
            await matcher.processBatch([
                createGlobals({ event: '$pageview', properties: { $current_url: 'https://posthog.com' } }),
            ])

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)
            expect(mockFetch).toHaveBeenCalledWith('https://example.com/condition-matched', expect.anything())
        })

        it('takes the timeout branch when neither events nor the condition match before max_wait', async () => {
            await createWaitUntilWorkflow({
                condition: { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters },
                events: [eventNameFilter('never_fires')],
                max_wait_duration: '2s',
            })
            await triggerWorkflow(createGlobals())

            // An unrelated event passes through the matcher but must not wake the job.
            await matcher.processBatch([createGlobals({ event: 'some_other_event' })])

            // After max_wait expires the job advances down the continue (timeout) branch.
            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 15000)
            expect(mockFetch).toHaveBeenCalledWith('https://example.com/timed-out', expect.anything())
        })

        it('leaves the job parked when an event matches neither the events nor the condition', async () => {
            await createWaitUntilWorkflow({
                condition: { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters },
                events: [eventNameFilter('wakeup_event')],
                max_wait_duration: '5m',
            })
            await triggerWorkflow(createGlobals())
            await expectParked()

            // An unrelated event must not wake the job.
            await matcher.processBatch([createGlobals({ event: 'some_other_event' })])

            // Give the worker room to (incorrectly) pick the job up — it must not.
            await new Promise((resolve) => setTimeout(resolve, 1000))
            const jobs = await queryCyclotronJobs()
            expect(jobs.every((j: any) => j.status === 'available' && new Date(j.scheduled) > new Date())).toBe(true)
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('does not wake on a completely empty "events to wait for" entry (always-true bytecode)', async () => {
            // The state left when the last event is removed from a wait entry: empty filters compile
            // to always-true bytecode. Inserted directly so it bypasses the serializer strip — this
            // guards the matcher itself, which must NOT fire the workflow on every incoming event.
            await createWaitUntilWorkflow({
                condition: { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters },
                events: [emptyEventFilter()],
                max_wait_duration: '5m',
            })
            await triggerWorkflow(createGlobals())
            await expectParked()

            // An unrelated event must not wake the job — the always-true bytecode would otherwise match.
            await matcher.processBatch([createGlobals({ event: 'some_unrelated_event' })])

            // Give the worker room to (incorrectly) pick the job up — it must not.
            await new Promise((resolve) => setTimeout(resolve, 1000))
            const jobs = await queryCyclotronJobs()
            expect(jobs.every((j: any) => j.status === 'available' && new Date(j.scheduled) > new Date())).toBe(true)
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('does not fire on entry for an empty property condition; takes the timeout branch', async () => {
            // An empty condition compiles to always-true bytecode. The executor evaluates the
            // condition on entry, so without the guard the wait advances down the matched branch
            // immediately. With no events and no real condition it must park and time out instead.
            await createWaitUntilWorkflow({
                condition: { filters: emptyConditionFilters() },
                max_wait_duration: '2s',
            })
            await triggerWorkflow(createGlobals())

            // If it fired on entry this would be the matched branch; it must be the timeout branch.
            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 15000)
            expect(mockFetch).toHaveBeenCalledWith('https://example.com/timed-out', expect.anything())
        })

        it('does not fire on entry when an empty condition coexists with a real events entry; still wakes on the event', async () => {
            // The reported bug: an empty (always-true) condition alongside a real "events to wait
            // for" entry. Without the guard the empty condition matches on entry and the wait fires
            // immediately, ignoring the configured event. It must park and only wake when the event
            // actually fires.
            await createWaitUntilWorkflow({
                condition: { filters: emptyConditionFilters() },
                events: [eventNameFilter('wakeup_event')],
                max_wait_duration: '5m',
            })
            await triggerWorkflow(createGlobals())
            await expectParked()

            // The configured event fires — the matcher wakes the job via the events entry.
            await matcher.processBatch([createGlobals({ event: 'wakeup_event' })])

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)
            expect(mockFetch).toHaveBeenCalledWith('https://example.com/condition-matched', expect.anything())
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
            await cyclotronPool.query(`UPDATE cyclotron_jobs SET scheduled = NOW() WHERE ${statusColumn} = 'available'`)

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
            const person: InternalPersonWithDistinctId = {
                id: '1',
                uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1',
                team_id: team.id,
                properties: { email: 'test@example.com', name: 'Test User', plan: 'enterprise' },
                properties_last_updated_at: {},
                properties_last_operation: null,
                created_at: DateTime.utc(),
                version: 1,
                is_identified: true,
                is_user_id: null,
                last_seen_at: null,
                distinct_id: 'test-distinct-id',
            }
            mockPersonRepo.fetchPersonsByDistinctIds.mockResolvedValue([person])

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

    describe('batch workflow: event.distinct_id resolved at the worker', () => {
        // A batch-triggered workflow enqueues invocations with personId but an empty
        // event.distinct_id (blast radius returns UUIDs only). The cyclotron worker is
        // responsible for resolving one distinct_id per person during its existing
        // postgres lookup and backfilling state.event.distinct_id — otherwise capture-based
        // templates defaulting to {event.distinct_id} would silently mint new person profiles.
        const personUuid = 'aaaaaaaa-1111-1111-1111-111111111111'
        const personDistinctId = 'batch-person-distinct-id'
        let hogFlow: HogFlow

        beforeEach(async () => {
            const person = {
                id: '2',
                uuid: personUuid,
                team_id: team.id,
                properties: { email: 'batch@example.com', plan: 'enterprise' },
                properties_last_updated_at: {},
                properties_last_operation: null,
                created_at: DateTime.utc(),
                version: 1,
                is_identified: true,
                is_user_id: null,
                last_seen_at: null,
            }
            mockPersonRepo.fetchPersonsByDistinctIds.mockResolvedValue([{ ...person, distinct_id: personDistinctId }])
            mockPersonRepo.fetchPersonsByPersonIds.mockResolvedValue([person])
            mockPersonRepo.fetchDistinctIdsForPersons.mockResolvedValue({
                [person.id]: [personDistinctId],
            })

            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-workflows-e2e-batch-distinct-id',
                name: 'Workflows E2E Batch Distinct Id',
                code: `fetch(inputs.url, { 'method': 'POST', 'body': inputs.distinct_id });`,
                inputs_schema: [
                    { key: 'url', type: 'string', required: true },
                    { key: 'distinct_id', type: 'string', required: true },
                ],
            })

            hogFlow = await createWorkflowFlow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: {
                            // 'batch' trigger so the events consumer skips this workflow —
                            // it only fires when an invocation is queued directly.
                            type: 'batch',
                            filters: { properties: [{ key: 'plan', value: 'enterprise', type: 'person' }] },
                        },
                    },
                    function_1: {
                        type: 'function',
                        config: {
                            template_id: 'template-workflows-e2e-batch-distinct-id',
                            inputs: {
                                url: { value: 'https://example.com/batch-distinct-id' },
                                distinct_id: {
                                    value: '{event.distinct_id}',
                                    bytecode: ['_H', 1, 32, 'distinct_id', 32, 'event', 1, 2, 38],
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
        })

        it("backfills {event.distinct_id} from the person's distinct_id at dequeue", async () => {
            await triggerBatchWorkflow(hogFlow, personUuid)

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 5000)

            // The hog template's `{event.distinct_id}` resolved at runtime to the value
            // the worker backfilled — proving the full chain: postgres lookup → CyclotronPerson.distinct_id
            // → state.event.distinct_id mutation → hog input resolution.
            expect(mockFetch).toHaveBeenCalledWith(
                'https://example.com/batch-distinct-id',
                expect.objectContaining({
                    body: personDistinctId,
                    method: 'POST',
                })
            )
        })

        it('does NOT call fetchDistinctIdsForPersons for event-triggered invocations', async () => {
            // Regression guard for the optimization: when event.distinct_id is set going in,
            // the persons-manager uses the by-distinct_id lookup which returns the distinct_id
            // as part of the lookup key — no separate fetchDistinctIdsForPersons RPC needed.
            // Without this guard, the by-person_id path could accidentally be used for event
            // triggers and pay an unnecessary postgres round-trip per worker tick.
            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-workflows-e2e-event-no-extra-rpc',
                name: 'Workflows E2E Event No Extra RPC',
                code: `fetch(inputs.url, { 'method': 'POST' });`,
                inputs_schema: [{ key: 'url', type: 'string', required: true }],
            })
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    function_1: fetchAction('https://example.com/event-trigger-no-extra-rpc'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })

            mockPersonRepo.fetchDistinctIdsForPersons.mockClear()

            await triggerWorkflow(createGlobals({ distinct_id: personDistinctId }))

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalled()
            }, 5000)

            expect(mockPersonRepo.fetchDistinctIdsForPersons).not.toHaveBeenCalled()
        })
    })

    describe('posthog_ticket_tags input resolves templated values per element', () => {
        // Regression guard for the templating opt-in in posthog/cdp/validation.py.
        // Reproduces the real user-reported case: a ticket tag set to
        // `zendesk/{variables.zendesk_ticketid}` used to ship to the runtime as
        // a literal placeholder string (because the type wasn't on the bytecode
        // opt-in list), so the ticket ended up tagged with the raw template text
        // instead of "zendesk/12345". The fix puts the per-element bytecode that
        // `generate_template_bytecode` already emits for lists into a shape that
        // `formatHogInput` can walk element-by-element.
        beforeEach(async () => {
            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-workflows-e2e-tags',
                name: 'Workflows E2E Tags',
                code: `fetch(inputs.url, { 'method': 'POST', 'body': jsonStringify(inputs.tags) });`,
                inputs_schema: [
                    { key: 'url', type: 'string', required: true },
                    { key: 'tags', type: 'posthog_ticket_tags', required: true },
                ],
            })

            const hogFlow = new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withStatus('active')
                .withWorkflow({
                    actions: {
                        trigger: trigger(),
                        function_1: {
                            type: 'function',
                            config: {
                                template_id: 'template-workflows-e2e-tags',
                                inputs: {
                                    url: { value: 'https://example.com/tags' },
                                    tags: {
                                        // What the Python serializer now produces for a
                                        // `posthog_ticket_tags` value like
                                        // `["zendesk/{variables.zendesk_ticketid}"]`:
                                        // one outer array, one inner bytecode per element.
                                        // Inner bytecode is a concat of the literal prefix
                                        // and a variables.* field access — same shape Django
                                        // emits today for other templated string inputs
                                        // (cf. the production `text` input bytecode).
                                        value: ['zendesk/{variables.zendesk_ticketid}'],
                                        templating: 'hog',
                                        bytecode: [
                                            [
                                                '_H',
                                                1,
                                                32,
                                                'zendesk/',
                                                32,
                                                'zendesk_ticketid',
                                                32,
                                                'variables',
                                                1,
                                                2,
                                                2,
                                                'concat',
                                                2,
                                            ],
                                        ],
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
                .build()
            // Workflow-defined variable with a default — populated into state.variables
            // by createHogFlowInvocation, so the function action sees it via globals.variables.
            // In a real workflow the value would be set by an earlier `Get ticket` action's
            // output_variable; for this test we pre-seed via the default to keep it focused.
            hogFlow.variables = [
                { key: 'zendesk_ticketid', type: 'string', label: 'Zendesk ticket id', default: '12345' },
            ]
            await insertHogFlow(hub.postgres, hogFlow)

            globals = createGlobals()
        })

        it('resolves zendesk/{variables.zendesk_ticketid} per element', async () => {
            await triggerWorkflow(globals)

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            // The body proves the full chain end-to-end: per-element bytecode →
            // formatHogInput recurses into the list → executes against globals
            // populated with workflow variables → concat produces "zendesk/12345".
            // Pre-fix behaviour would emit `["zendesk/{variables.zendesk_ticketid}"]`.
            expect(mockFetch).toHaveBeenCalledWith(
                'https://example.com/tags',
                expect.objectContaining({
                    body: JSON.stringify(['zendesk/12345']),
                    method: 'POST',
                })
            )
        })
    })
})

// Email queue routing is postgres-v2 only — the email worker reschedules jobs
// between queue names on the same v2 backend. We keep this block outside the
// `describe.each` so the legacy postgres mode doesn't also try to exercise it.
describe('Workflows E2E (email queue)', () => {
    jest.setTimeout(30000)

    let eventsConsumer: CdpEventsConsumer
    let hogflowWorker: CdpCyclotronWorkerHogFlow
    let emailWorker: CdpCyclotronWorkerEmail
    let matcher: CdpHogflowSubscriptionMatcherConsumer | undefined

    let hub: Hub
    let kafkaProducer: KafkaProducerWrapper
    let mockProducerObserver: KafkaProducerObserver
    let team: Team
    let cyclotronPool: Pool
    let deps: ReturnType<typeof createCdpConsumerDeps>

    beforeAll(() => {
        cyclotronPool = new Pool({ connectionString: CYCLOTRON_NODE_DB_URL })
    })

    afterAll(async () => {
        await cyclotronPool.end()
    })

    beforeEach(async () => {
        MockKafkaProducerWrapper.create = jest.fn((...args) => {
            return ActualKafkaProducerWrapper.create(...args)
        })

        await resetKafka()
        await resetTestDatabase()
        await cyclotronPool.query('DELETE FROM cyclotron_jobs')

        hub = await createHub()
        // Route all teams' emails through the dedicated queue
        hub.CDP_EMAIL_QUEUE_ROUTING = '*'
        hub.CDP_CYCLOTRON_BATCH_DELAY_MS = 50

        kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        mockProducerObserver = new KafkaProducerObserver(kafkaProducer)

        team = await getFirstTeam(hub.postgres)
        mockProducerObserver.resetKafkaProducer()

        // Email integration — provider 'maildev' routes to local SMTP (port 1025)
        await insertIntegration(hub.postgres, team.id, {
            id: 1,
            kind: 'email',
            config: {
                email: 'sender@posthog.com',
                name: 'Test Sender',
                domain: 'posthog.com',
                verified: true,
                provider: 'maildev',
            },
        })

        // Native-email template that the workflow's email action invokes
        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-workflows-e2e-email',
            name: 'Workflows E2E Email',
            code: `sendEmail(inputs.email)`,
            inputs_schema: [
                {
                    type: 'native_email',
                    key: 'email',
                    label: 'Email message',
                    integration: 'email',
                    required: true,
                    default: {
                        to: { email: '', name: '' },
                        from: { email: '', name: '' },
                        subject: '',
                        text: 'Hello!',
                        html: '<div>Hello!</div>',
                    },
                    secret: false,
                    description: '',
                    templating: 'liquid',
                },
            ],
        })

        matcher = undefined
        deps = createCdpConsumerDeps(hub, kafkaProducer)
        const kafkaQueue = new CyclotronJobQueueKafka(hub.KAFKA_CLIENT_RACK, hub, hub.CONSUMER_BATCH_SIZE)
        // Each consumer gets a dedicated CyclotronJobQueuePostgresV2 — sharing one
        // across two consumers collides on `this.worker` and the shared pg pool.
        // Mirrors the prod deployment model where each capability runs in its own pod.
        const eventsProducerQueue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)
        const hogflowConsumerQueue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)
        const emailConsumerQueue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)

        eventsConsumer = new CdpEventsConsumer(hub, deps, {
            hogQueue: kafkaQueue,
            hogflowQueue: eventsProducerQueue,
        })
        await Promise.all([kafkaQueue.startAsProducer(), eventsProducerQueue.startAsProducer()])

        // Hogflow worker polls jobs with queue_name='hogflow' and re-stamps email
        // jobs to queue_name='email' so the email worker picks them up
        hogflowWorker = new CdpCyclotronWorkerHogFlow(hub, deps, hogflowConsumerQueue)
        await hogflowWorker.start()

        // Email worker polls jobs with queue_name='email', sends via EmailService,
        // and continues the workflow inline (until it hits a fetch or terminates)
        emailWorker = new CdpCyclotronWorkerEmail(hub, deps, emailConsumerQueue)
        await emailWorker.start()
    })

    afterEach(async () => {
        await Promise.all([
            eventsConsumer?.stop() ?? Promise.resolve(),
            hogflowWorker?.stop() ?? Promise.resolve(),
            emailWorker?.stop() ?? Promise.resolve(),
            matcher?.stop().catch(() => {}) ?? Promise.resolve(),
        ])
        await kafkaProducer.disconnect()
        await closeHub(hub)
        mockProducerObserver.resetKafkaProducer()
    })

    async function queryCyclotronJobs(): Promise<any[]> {
        const result = await cyclotronPool.query(`SELECT *, status AS status FROM cyclotron_jobs ORDER BY created ASC`)
        return result.rows
    }

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

    // Mirrors what HogFlowSerializer compiles for {events: [{id: <name>}]}: a single
    // equality check on the `event` global. The matcher fails closed without bytecode.
    const eventNameFilter = (eventName: string) => ({
        filters: { events: [{ id: eventName }], bytecode: ['_H', 1, 32, eventName, 32, 'event', 1, 1, 11] as any[] },
    })

    it('routes the email through the dedicated queue and continues the workflow', async () => {
        const hogFlow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withExitCondition('exit_only_at_end')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
                    },
                    email_1: {
                        type: 'function_email',
                        config: {
                            template_id: 'template-workflows-e2e-email',
                            inputs: {
                                email: {
                                    value: {
                                        to: { email: 'recipient@example.com', name: 'Recipient' },
                                        from: { integrationId: 1, email: 'sender@posthog.com' },
                                        subject: 'Test Email',
                                        text: 'Test text',
                                        html: '<p>Test html</p>',
                                    },
                                },
                            },
                        },
                    },
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'email_1', type: 'continue' },
                    { from: 'email_1', to: 'exit', type: 'continue' },
                ],
            })
            .build()
        await insertHogFlow(hub.postgres, hogFlow)

        // Trigger the workflow via the events consumer (real Kafka producer + v2 queue)
        const { backgroundTask } = await eventsConsumer.processBatch([createGlobals()])
        await backgroundTask

        // Verify both metric stages fire EXACTLY ONCE — regression guard against
        // a double-counting bug where each metric (incl. unrelated ones like the
        // exit_node 'succeeded') was being pushed twice per invocation. The
        // AppMetricsAggregator dedupes by key in-memory, so we sum `count` across
        // all messages rather than counting messages: one push at count=1 looks
        // identical to two pushes at count=1 unless we sum.
        await waitForExpect(() => {
            const sumCounts = (filter: (m: any) => boolean) =>
                mockProducerObserver
                    .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    .filter(filter)
                    .reduce((sum: number, m: any) => sum + m.value.count, 0)

            expect(sumCounts((m) => m.value.metric_name === 'email_queued')).toBe(1)
            expect(sumCounts((m) => m.value.metric_name === 'email_sent')).toBe(1)
            // The exit action's 'succeeded' metric has nothing to do with the email
            // pipeline — including it locks down that the doubling isn't email-specific.
            // (The instance_id matches the action key from FixtureHogFlowBuilder.)
            expect(sumCounts((m) => m.value.metric_name === 'succeeded' && m.value.instance_id === 'exit')).toBe(1)
        }, 15000)

        // Workflow should reach a terminal state once the email worker has continued through exit
        await waitForExpect(async () => {
            const jobs = await queryCyclotronJobs()
            const terminal = jobs.filter(
                (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
            )
            expect(terminal.length).toBeGreaterThanOrEqual(1)
        }, 10000)
    })

    it('re-routes between hogflow and email queues across email → fetch → email', async () => {
        // Exercises the full ping-pong:
        //   hogflow worker → email queue (email_1) → email worker sends → routes back to hogflow
        //   → hogflow worker does fetch → email queue (email_2) → email worker sends → exits
        // Proves queueMetadata.originQueue is honored on the return trip from the email worker.
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

        mockFetch.mockResolvedValue({
            status: 200,
            headers: { 'Content-Type': 'application/json' },
            json: () => Promise.resolve({ success: true }),
            text: () => Promise.resolve(JSON.stringify({ success: true })),
            dump: () => Promise.resolve(),
        })

        const emailAction = (label: string) => ({
            type: 'function_email' as const,
            config: {
                template_id: 'template-workflows-e2e-email',
                inputs: {
                    email: {
                        value: {
                            to: { email: 'recipient@example.com', name: 'Recipient' },
                            from: { integrationId: 1, email: 'sender@posthog.com' },
                            subject: label,
                            text: label,
                            html: `<p>${label}</p>`,
                        },
                    },
                },
            },
        })

        const hogFlow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withExitCondition('exit_only_at_end')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
                    },
                    email_1: emailAction('First email'),
                    fetch_1: {
                        type: 'function',
                        config: {
                            template_id: 'template-workflows-e2e-fetch',
                            inputs: {
                                url: { value: 'https://example.com/between-emails' },
                                method: { value: 'POST' },
                            },
                        },
                    },
                    email_2: emailAction('Second email'),
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'email_1', type: 'continue' },
                    { from: 'email_1', to: 'fetch_1', type: 'continue' },
                    { from: 'fetch_1', to: 'email_2', type: 'continue' },
                    { from: 'email_2', to: 'exit', type: 'continue' },
                ],
            })
            .build()
        await insertHogFlow(hub.postgres, hogFlow)

        const { backgroundTask } = await eventsConsumer.processBatch([createGlobals()])
        await backgroundTask

        // The fetch must fire exactly once — happens on the hogflow worker between
        // the two email queue hops. If it never fires, the email worker is failing
        // to route back to hogflow after the first send.
        await waitForExpect(() => {
            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(mockFetch).toHaveBeenCalledWith(
                'https://example.com/between-emails',
                expect.objectContaining({ method: 'POST' })
            )
        }, 15000)

        // Two emails were queued and two were sent — one for each side of the fetch.
        // Sum `count` across all messages: with aggregator in-memory dedup we'd
        // miss a 2× per-send bug by only counting messages, not their counts.
        await waitForExpect(() => {
            const sumCounts = (filter: (m: any) => boolean) =>
                mockProducerObserver
                    .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    .filter(filter)
                    .reduce((sum: number, m: any) => sum + m.value.count, 0)

            expect(sumCounts((m) => m.value.metric_name === 'email_queued')).toBe(2)
            expect(sumCounts((m) => m.value.metric_name === 'email_sent')).toBe(2)
        }, 15000)

        await waitForExpect(async () => {
            const jobs = await queryCyclotronJobs()
            const terminal = jobs.filter(
                (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
            )
            expect(terminal.length).toBeGreaterThanOrEqual(1)
        }, 10000)
    })

    it('wakes a wait_until_condition parked on the email queue after an email step', async () => {
        // Reproduces the prod bug: an email step routes the invocation to the email queue, so the
        // following wait_until_condition parks on the email queue (not hogflow). The matcher must
        // still find and wake it there — otherwise a matching event never wakes the job and the
        // post-wait email is never sent.
        const emailAction = (label: string) => ({
            type: 'function_email' as const,
            config: {
                template_id: 'template-workflows-e2e-email',
                inputs: {
                    email: {
                        value: {
                            to: { email: 'recipient@example.com', name: 'Recipient' },
                            from: { integrationId: 1, email: 'sender@posthog.com' },
                            subject: label,
                            text: label,
                            html: `<p>${label}</p>`,
                        },
                    },
                },
            },
        })

        const hogFlow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withExitCondition('exit_only_at_end')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
                    },
                    email_1: emailAction('First email'),
                    wait_condition: {
                        type: 'wait_until_condition',
                        config: {
                            // Property condition never matches, so only the event can wake the job.
                            condition: { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters },
                            events: [eventNameFilter('wakeup_event')],
                            // Long enough that the job stays parked for the whole test — the only way
                            // the second email sends is the matcher waking it, never a timeout.
                            max_wait_duration: '5m',
                        },
                    },
                    email_2: emailAction('Second email'),
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'email_1', type: 'continue' },
                    { from: 'email_1', to: 'wait_condition', type: 'continue' },
                    { from: 'wait_condition', to: 'email_2', type: 'branch', index: 0 },
                    { from: 'wait_condition', to: 'exit', type: 'continue' },
                    { from: 'email_2', to: 'exit', type: 'continue' },
                ],
            })
            .build()
        await insertHogFlow(hub.postgres, hogFlow)

        const emailsSent = () =>
            mockProducerObserver
                .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                .filter((m: any) => m.value.metric_name === 'email_sent')
                .reduce((sum: number, m: any) => sum + m.value.count, 0)

        // Trigger: email_1 routes to the email queue, the email worker sends it and continues the
        // flow to the wait step, which parks.
        const { backgroundTask } = await eventsConsumer.processBatch([createGlobals()])
        await backgroundTask

        // The first email is sent and the job parks waiting for the event.
        await waitForExpect(async () => {
            expect(emailsSent()).toBe(1)
            const jobs = await queryCyclotronJobs()
            expect(jobs.some((j: any) => j.status === 'available' && new Date(j.scheduled) > new Date())).toBe(true)
        }, 15000)

        // The wait parks on the email queue (carried over from email_1). The matcher has to find
        // it there regardless of queue — that's exactly the scenario that was broken.
        const parked = (await queryCyclotronJobs()).find(
            (j: any) => j.status === 'available' && new Date(j.scheduled) > new Date()
        )
        expect(parked).toBeDefined()
        expect(parked?.queue_name).toBe('email')
        expect(emailsSent()).toBe(1)

        // The subscribed event fires for this person — the matcher wakes the parked job even though
        // it sits on the email queue, the email worker resumes it down the matched branch, and the
        // second email is sent. This is the end-to-end "the job wakes and the next step runs" check.
        matcher = new CdpHogflowSubscriptionMatcherConsumer({ ...hub }, deps)
        await matcher.processBatch([createGlobals({ event: 'wakeup_event' })])

        await waitForExpect(() => {
            expect(emailsSent()).toBe(2)
        }, 15000)
    })
})
