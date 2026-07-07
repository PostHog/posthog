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
import { mockFetch, mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { register } from 'prom-client'
import supertest from 'supertest'
import express from 'ultimate-express'

import { HogFlow } from '~/cdp/schema/hogflow'
import { setupExpressApp } from '~/common/api/router'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES, KAFKA_MESSAGE_ASSETS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { InternalPersonWithDistinctId, PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { InternalFetchService } from '~/common/services/internal-fetch'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../src/types'
import { createRedisV2PoolFromConfig } from '../common/redis/redis-v2'
import { FixtureHogFlowBuilder } from './_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from './_tests/examples'
import { createHogExecutionGlobals, insertHogFunctionTemplate, insertIntegration } from './_tests/fixtures'
import { insertHogFlow } from './_tests/fixtures-hogflows'
import { CdpApi } from './cdp-api'
import { CdpCyclotronWorkerBatchResolve } from './consumers/cdp-cyclotron-worker-batch-resolve.consumer'
import { CdpCyclotronWorkerEmail } from './consumers/cdp-cyclotron-worker-email.consumer'
import { CdpCyclotronWorkerHogFlow } from './consumers/cdp-cyclotron-worker-hogflow.consumer'
import { CdpDatawarehouseEventsConsumer } from './consumers/cdp-data-warehouse-events.consumer'
import { CdpEventsConsumer } from './consumers/cdp-events.consumer'
import { CdpHogflowSubscriptionMatcherConsumer } from './consumers/cdp-hogflow-subscription-matcher.consumer'
import { CyclotronV2Manager, CyclotronV2Worker } from './services/cyclotron-v2'
import {
    HOGFLOW_BATCH_RESOLVE_QUEUE,
    MAX_RESOLVER_ATTEMPTS,
    serializeResolverState,
} from './services/hogflows/batch-resolver.types'
import { HogFlowBatchPersonQueryService } from './services/hogflows/hogflow-batch-person-query.service'
import { CyclotronJobQueueKafka } from './services/job-queue/job-queue-kafka'
import { CyclotronJobQueuePostgres } from './services/job-queue/job-queue-postgres'
import { CyclotronJobQueuePostgresV2 } from './services/job-queue/job-queue-postgres-v2'
import { CyclotronJobQueueRateLimitedPostgresV2 } from './services/job-queue/job-queue-rate-limited-postgres-v2'
import { JobQueue } from './services/job-queue/job-queue.interface'
import { RateLimiterService } from './services/rate-limiter/rate-limiter.service'
import { HogFunctionInvocationGlobals } from './types'
import { convertBatchHogFlowRequestToHogFunctionInvocationGlobals } from './utils'
import { convertToHogFunctionFilterGlobal } from './utils/hog-function-filtering'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

// DNS is mocked (like fetch) because EmailValidationService's MX lookups are a real
// network boundary: validation is fail-open, so a CI resolver hiccup would silently
// turn a "skipped hard bounce" assertion into a sent email — a guaranteed flake.
// Implementations are domain-aware and set in the email-queue block's beforeEach.
const mockDnsResolveMx = jest.fn()
const mockDnsResolve4 = jest.fn()
const mockDnsResolve6 = jest.fn()

jest.mock('node:dns/promises', () => ({
    Resolver: jest.fn().mockImplementation(() => ({
        resolveMx: mockDnsResolveMx,
        resolve4: mockDnsResolve4,
        resolve6: mockDnsResolve6,
    })),
}))

// Use the same env vars as config.ts (lines 221-229) so cleanup pools and hub target the same DBs
const CYCLOTRON_NODE_DB_URL =
    process.env.CYCLOTRON_NODE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'
const CYCLOTRON_DB_URL =
    process.env.CYCLOTRON_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron'

describe.each(['postgres-v2' as const, 'postgres' as const])('Workflows E2E (%s)', (mode) => {
    jest.setTimeout(30000)

    let eventsConsumer: CdpEventsConsumer
    let dwhConsumer: CdpDatawarehouseEventsConsumer
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

        await ensureKafkaTopics(TEST_KAFKA_TOPICS)
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
        // Drives the data-warehouse-table trigger path. We call processBatch() directly, so the
        // Kafka consumer is never connected — the shared queues below are the only producers.
        dwhConsumer = new CdpDatawarehouseEventsConsumer(hub, deps, {
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
        // dwhConsumer shares the already-stopped queues with eventsConsumer, so it has nothing to stop.
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

    /**
     * Build the row-scoped globals the DWH consumer produces for a synced warehouse row: a synthetic
     * event named `$warehouse_source_row` with no real person, and the source table on
     * `event.properties.$source_table` so the consumer's eligibilityFn matches warehouse-table triggers.
     */
    function createDwhGlobals(
        tableName: string,
        rowProperties: Record<string, any> = {}
    ): HogFunctionInvocationGlobals {
        return createHogExecutionGlobals({
            project: { id: team.id } as any,
            event: {
                uuid: new UUIDT().toString(),
                event: '$warehouse_source_row',
                distinct_id: '',
                properties: { ...rowProperties, $source_table: tableName },
                timestamp: '2024-09-03T09:00:00Z',
            } as any,
        })
    }

    /** Send a synced warehouse row through the DWH consumer and wait for it to be queued */
    async function triggerDwhWorkflow(rowGlobals: HogFunctionInvocationGlobals): Promise<void> {
        const { backgroundTask } = await dwhConsumer.processBatch([rowGlobals])
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
        opts?: { name?: string; conversion?: HogFlow['conversion']; exitCondition?: HogFlow['exit_condition'] }
    ): Promise<HogFlow> {
        const builder = new FixtureHogFlowBuilder().withTeamId(team.id).withStatus('active').withWorkflow(workflow)
        if (opts?.name) {
            builder.withName(opts.name)
        }
        if (opts?.conversion) {
            builder.withConversion(opts.conversion)
        }
        if (opts?.exitCondition) {
            builder.withExitCondition(opts.exitCondition)
        }
        const flow = builder.build()
        await insertHogFlow(hub.postgres, flow)
        return flow
    }

    /**
     * Construct and enqueue a batch-shaped CyclotronJobInvocation directly, mimicking what
     * the batch resolver's buildHogFlowInvocation would produce. Skips the blast-radius API
     * call so tests don't need to stand up the Django side.
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

        it('does not collapse a delay before a wait when the wait event fires during the delay', async () => {
            // trigger -> delay(5m) -> wait_until_condition(wakeup_event) -> matched / timeout. The
            // wait's event firing DURING the delay must not wake the job: the delay handler no longer
            // pre-advances currentAction to the wait, so while parked the job is at the delay (not the
            // wait) and the matcher leaves it alone. The delay is honored.
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    delay: { type: 'delay', config: { delay_duration: '5m' } },
                    wait_condition: {
                        type: 'wait_until_condition',
                        config: {
                            events: [eventNameFilter('wakeup_event')],
                            condition: { filters: null },
                            max_wait_duration: '5m',
                        },
                    },
                    function_matched: fetchAction('https://example.com/matched'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'delay', type: 'continue' },
                    { from: 'delay', to: 'wait_condition', type: 'continue' },
                    { from: 'wait_condition', to: 'function_matched', type: 'branch', index: 0 },
                    { from: 'wait_condition', to: 'exit', type: 'continue' },
                    { from: 'function_matched', to: 'exit', type: 'continue' },
                ],
            })
            await triggerWorkflow(createGlobals())
            await expectParked()

            // The wait's event fires during the delay — the job must stay parked in the delay.
            await matcher.processBatch([createGlobals({ event: 'wakeup_event' })])

            await new Promise((resolve) => setTimeout(resolve, 1000))
            const jobs = await queryCyclotronJobs()
            expect(jobs.every((j: any) => j.status === 'available' && new Date(j.scheduled) > new Date())).toBe(true)
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('does not run the next step early when a conversion event fires during a delay', async () => {
            // trigger -> delay -> fetch, with an event-based conversion goal used only for
            // measurement (exit_only_at_end). A conversion event arriving while the job is parked
            // in the delay must NOT wake it and run the fetch ~5 minutes early.
            await createWorkflowFlow(
                {
                    actions: {
                        trigger: trigger(),
                        delay: { type: 'delay', config: { delay_duration: '5m' } },
                        after_delay: fetchAction('https://example.com/after-delay'),
                        exit: exitAction(),
                    },
                    edges: [
                        { from: 'trigger', to: 'delay', type: 'continue' },
                        { from: 'delay', to: 'after_delay', type: 'continue' },
                        { from: 'after_delay', to: 'exit', type: 'continue' },
                    ],
                },
                {
                    exitCondition: 'exit_only_at_end',
                    conversion: {
                        window_minutes: 60,
                        filters: [],
                        bytecode: [],
                        events: [eventNameFilter('conversion_event')],
                    } as any,
                }
            )
            await triggerWorkflow(createGlobals())
            await expectParked()

            // The conversion event fires during the delay — it must not pull the job out early.
            await matcher.processBatch([createGlobals({ event: 'conversion_event' })])

            // Give the worker room to (incorrectly) resume the job — it must stay parked, no fetch.
            await new Promise((resolve) => setTimeout(resolve, 1000))
            const jobs = await queryCyclotronJobs()
            expect(jobs.every((j: any) => j.status === 'available' && new Date(j.scheduled) > new Date())).toBe(true)
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('exits the workflow when an exit_on_conversion goal fires during a delay', async () => {
            // Same shape, but the workflow exits on conversion. The conversion event during the delay
            // SHOULD resume the job — to exit it early — but must still not run the next step (fetch).
            await createWorkflowFlow(
                {
                    actions: {
                        trigger: trigger(),
                        delay: { type: 'delay', config: { delay_duration: '5m' } },
                        after_delay: fetchAction('https://example.com/after-delay'),
                        exit: exitAction(),
                    },
                    edges: [
                        { from: 'trigger', to: 'delay', type: 'continue' },
                        { from: 'delay', to: 'after_delay', type: 'continue' },
                        { from: 'after_delay', to: 'exit', type: 'continue' },
                    ],
                },
                {
                    exitCondition: 'exit_on_conversion',
                    conversion: {
                        window_minutes: 60,
                        filters: [],
                        bytecode: [],
                        events: [eventNameFilter('conversion_event')],
                    } as any,
                }
            )
            await triggerWorkflow(createGlobals())
            await expectParked()

            // The conversion event fires during the delay — the workflow must exit early.
            await matcher.processBatch([createGlobals({ event: 'conversion_event' })])

            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                expect(jobs.some((j: any) => ['completed', 'failed', 'canceled'].includes(j.status))).toBe(true)
            }, 10000)
            // Exited on conversion — the after-delay step never ran.
            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('counts an event-based conversion exactly once per run even when the event fires repeatedly', async () => {
            // Regression guard for conversion over-counting on measurement-only flows. The run stays
            // parked in the delay (exit_only_at_end), and the conversion event fires across three
            // separate matcher batches. The matcher must record exactly ONE `conversion` metric for
            // the run (deduped via conversionCounted), and must never wake the job.
            await createWorkflowFlow(
                {
                    actions: {
                        trigger: trigger(),
                        delay: { type: 'delay', config: { delay_duration: '5m' } },
                        after_delay: fetchAction('https://example.com/after-delay'),
                        exit: exitAction(),
                    },
                    edges: [
                        { from: 'trigger', to: 'delay', type: 'continue' },
                        { from: 'delay', to: 'after_delay', type: 'continue' },
                        { from: 'after_delay', to: 'exit', type: 'continue' },
                    ],
                },
                {
                    exitCondition: 'exit_only_at_end',
                    conversion: {
                        window_minutes: 60,
                        filters: [],
                        bytecode: [],
                        events: [eventNameFilter('conversion_event')],
                    } as any,
                }
            )
            await triggerWorkflow(createGlobals())
            await expectParked()

            const conversionCount = (): number =>
                mockProducerObserver
                    .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    .filter((m: any) => m.value.metric_name === 'conversion')
                    .reduce((sum: number, m: any) => sum + m.value.count, 0)

            // First match counts the conversion once.
            await matcher.processBatch([createGlobals({ event: 'conversion_event' })])
            await waitForExpect(() => {
                expect(conversionCount()).toBe(1)
            }, 5000)

            // The same conversion event firing again must NOT increment the count — the run already converted.
            await matcher.processBatch([createGlobals({ event: 'conversion_event' })])
            await matcher.processBatch([createGlobals({ event: 'conversion_event' })])
            await new Promise((resolve) => setTimeout(resolve, 500))
            expect(conversionCount()).toBe(1)

            // Measurement-only: the run stays parked and the after-delay step never runs early.
            const jobs = await queryCyclotronJobs()
            expect(jobs.every((j: any) => j.status === 'available' && new Date(j.scheduled) > new Date())).toBe(true)
            expect(mockFetch).not.toHaveBeenCalled()
        })
    })

    describe('wait_until_time_window: window in the future', () => {
        beforeEach(async () => {
            // A fixed daily window is "open" during its own minutes every day, so any
            // run landing inside it (e.g. CI at 09:5x UTC for a 23:5x UTC+14 window)
            // executes immediately instead of rescheduling. Derive the window a few
            // minutes ahead of now so it is always strictly in the future.
            const now = DateTime.utc()
            const windowStart = now.plus({ minutes: 10 }).toFormat('HH:mm')
            const windowEnd = now.plus({ minutes: 20 }).toFormat('HH:mm')
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    wait_window: {
                        type: 'wait_until_time_window',
                        config: { timezone: 'UTC', day: 'any', time: [windowStart, windowEnd] },
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

        it('parks until the window opens and does not advance early on a premature resume', async () => {
            await triggerWorkflow(globals)

            // Job should be rescheduled to the future time window.
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const rescheduled = jobs.filter(
                    (j: any) => j.status === 'available' && new Date(j.scheduled) > new Date()
                )
                expect(rescheduled.length).toBe(1)
            }, 5000)
            expect(mockFetch).not.toHaveBeenCalled()

            // A premature resume (the window is still in the future) must re-park, not advance to the
            // next step. The handler stays at the wait_until_time_window step and reschedules, so the
            // step that follows the window never runs early.
            await cyclotronPool.query(`UPDATE cyclotron_jobs SET scheduled = NOW() WHERE ${statusColumn} = 'available'`)
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                expect(jobs.some((j: any) => j.status === 'available' && new Date(j.scheduled) > new Date())).toBe(true)
            }, 10000)
            expect(mockFetch).not.toHaveBeenCalled()
        })
    })

    describe('wait_until_time_window: window currently open', () => {
        it('advances through the window and runs the next step', async () => {
            // day: 'any', time: 'any' is always open, so the step must advance and run the next action
            // instead of parking forever.
            await createWorkflow({
                actions: {
                    trigger: trigger(),
                    wait_window: {
                        type: 'wait_until_time_window',
                        config: { timezone: 'UTC', day: 'any', time: 'any' },
                    },
                    function_1: fetchAction('https://example.com/window-open'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'wait_window', type: 'continue' },
                    { from: 'wait_window', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })

            await triggerWorkflow(createGlobals())

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)
            expect(mockFetch).toHaveBeenCalledWith('https://example.com/window-open', expect.anything())
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

    describe('data warehouse table trigger workflow', () => {
        const TABLE_NAME = 'postgres.orders'

        // Row-scoped trigger that always matches (return-true bytecode), so the row payload alone
        // decides whether the flow fires.
        const dwhTrigger = (tableName: string) =>
            ({
                type: 'trigger' as const,
                config: {
                    type: 'data-warehouse-table',
                    table_name: tableName,
                    filters: { properties: [], bytecode: ['_h', 29] },
                },
            }) as any

        beforeEach(async () => {
            await createWorkflow({
                actions: {
                    trigger: dwhTrigger(TABLE_NAME),
                    function_1: fetchAction('https://example.com/warehouse-row'),
                    exit: exitAction(),
                },
                edges: [
                    { from: 'trigger', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'exit', type: 'continue' },
                ],
            })
        })

        it('runs the workflow end-to-end when a row syncs into the matching table', async () => {
            await triggerDwhWorkflow(createDwhGlobals(TABLE_NAME, { order_id: 42 }))

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            expect(mockFetch).toHaveBeenCalledWith(
                'https://example.com/warehouse-row',
                expect.objectContaining({ method: 'POST' })
            )
        })

        it('does not run the workflow when the synced row belongs to a different table', async () => {
            await triggerDwhWorkflow(createDwhGlobals('postgres.other_table', { order_id: 1 }))

            // Give the worker a chance to (not) pick anything up before asserting it stayed idle.
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                expect(jobs).toHaveLength(0)
            }, 3000)

            expect(mockFetch).not.toHaveBeenCalled()
        })

        it('does not look up a person for warehouse rows (no synthetic distinct_id resolution)', async () => {
            // Regression guard: warehouse rows carry a made-up event.distinct_id that evals truthy.
            // The worker must skip the person lookup for data-warehouse-table triggers so we don't
            // pay a person round-trip (or accidentally resolve a bogus person) per synced row.
            const personSpy = jest.spyOn((hogflowWorker as any).personsManager, 'getCyclotronPerson')

            await triggerDwhWorkflow(createDwhGlobals(TABLE_NAME, { order_id: 7 }))

            await waitForExpect(() => {
                expect(mockFetch).toHaveBeenCalledTimes(1)
            }, 10000)

            expect(personSpy).not.toHaveBeenCalled()
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

        await ensureKafkaTopics(TEST_KAFKA_TOPICS)
        await resetTestDatabase()
        await cyclotronPool.query('DELETE FROM cyclotron_jobs')

        hub = await createHub()
        hub.CDP_CYCLOTRON_BATCH_DELAY_MS = 50
        // Default in non-dev envs is `false`, so the message-assets capture path stays
        // dormant in CI. The asset-capture tests below assert the row lands in the
        // dedicated Kafka topic, so we flip the kill-switch on for this describe block.
        // Set before `createCdpConsumerDeps` / worker construction so the value is
        // captured in `MessageAssetsService` at instantiation.
        hub.MESSAGE_ASSETS_CAPTURE_ENABLED = true

        // Enforce mode for the whole block: existing tests prove deliverable recipients
        // pass validation untouched; the skip test proves dead domains never reach the queue.
        hub.CDP_EMAIL_MX_VALIDATION_ENABLED = true
        hub.CDP_EMAIL_MX_VALIDATION_ENFORCE_TEAMS = '*'

        // `.invalid` domains are NXDOMAIN, everything else resolves as deliverable.
        const nxdomain = () => Promise.reject(Object.assign(new Error('queryMx ENOTFOUND'), { code: 'ENOTFOUND' }))
        mockDnsResolveMx.mockImplementation((domain: string) =>
            domain.endsWith('.invalid') ? nxdomain() : Promise.resolve([{ exchange: 'mx.example.com', priority: 10 }])
        )
        mockDnsResolve4.mockImplementation((domain: string) =>
            domain.endsWith('.invalid') ? nxdomain() : Promise.resolve(['1.2.3.4'])
        )
        mockDnsResolve6.mockImplementation(() => Promise.resolve([]))

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

    it('skips a predicted hard bounce before the email queue and completes the workflow', async () => {
        // Locks down the pipeline sequencing the unit tests can't: the MX-validation
        // skip happens on the hogflow worker BEFORE routeEmailToQueue, so a dead-domain
        // recipient must produce no email_queued/email_sent, no billable_invocation,
        // exactly one email_bounce_prevented, and a workflow that still runs to exit
        // instead of wedging on the email queue.
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
                                        to: { email: 'recipient@dead.invalid', name: 'Recipient' },
                                        from: { integrationId: 1, email: 'sender@posthog.com' },
                                        subject: 'Predicted bounce',
                                        text: 'Should never send',
                                        html: '<p>Should never send</p>',
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

        const { backgroundTask } = await eventsConsumer.processBatch([createGlobals()])
        await backgroundTask

        await waitForExpect(() => {
            const sumCounts = (filter: (m: any) => boolean) =>
                mockProducerObserver
                    .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    .filter(filter)
                    .reduce((sum: number, m: any) => sum + m.value.count, 0)

            // Wait for the two positive signals first — once the exit 'succeeded' metric
            // has flushed, the absence of email metrics below is meaningful, since
            // email_queued would have been emitted earlier in the pipeline.
            expect(sumCounts((m) => m.value.metric_name === 'email_bounce_prevented')).toBe(1)
            expect(sumCounts((m) => m.value.metric_name === 'succeeded' && m.value.instance_id === 'exit')).toBe(1)

            expect(sumCounts((m) => m.value.metric_name === 'email_queued')).toBe(0)
            expect(sumCounts((m) => m.value.metric_name === 'email_sent')).toBe(0)
            expect(sumCounts((m) => m.value.metric_name === 'email_failed')).toBe(0)
            expect(sumCounts((m) => m.value.metric_name === 'billable_invocation')).toBe(0)
        }, 15000)

        await waitForExpect(async () => {
            const jobs = await queryCyclotronJobs()
            expect(jobs.filter((j: any) => j.status === 'completed').length).toBeGreaterThanOrEqual(1)
            expect(jobs.filter((j: any) => j.status === 'failed').length).toBe(0)
        }, 10000)
    })

    it('does not emit duplicate Resuming / Executing / pause logs for the email-queue routing reschedule', async () => {
        // Email steps reschedule themselves once to switch onto the dedicated email queue
        // (see HogFunctionHandler.execute in actions/hog_function.ts). That second dequeue
        // continues the *same* action and would otherwise re-emit "Resuming workflow execution
        // at Email", "Executing action Email", and a "Workflow will pause until <basically
        // now>" line — leaking the internal queue routing into customer-visible logs.
        //
        // The fix tags the action state with `routingOnlyReschedule: true` on the rescheduling
        // dequeue and consumes it on the next dequeue to suppress those three lines. This test
        // is the regression guard: trigger → email → exit should produce exactly one trigger
        // log, one "Executing action [Action:email_1]" line, one "Email sent" line, and no
        // routing-flavored pause / resume noise.
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
                                        subject: 'Routing-reschedule log test',
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

        const { backgroundTask } = await eventsConsumer.processBatch([createGlobals()])
        await backgroundTask

        // Wait for the workflow to terminate so all logs from both dequeues have been produced.
        await waitForExpect(async () => {
            const jobs = await queryCyclotronJobs()
            const terminal = jobs.filter(
                (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
            )
            expect(terminal.length).toBeGreaterThanOrEqual(1)
        }, 15000)

        // Collect every log entry produced by this hogflow run from the Kafka topic.
        const logMessages = mockProducerObserver
            .getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
            .map((m: any) => m.value.message as string)

        // Sanity check: the test wired up correctly (email actually sent).
        expect(logMessages.some((msg) => msg.includes('Email sent to recipient@example.com'))).toBe(true)

        // The email action's "Executing action" debug log must fire EXACTLY ONCE despite the
        // two dequeues it takes to switch queues. Anchor on the action id ('email_1') so we
        // don't accidentally also match the trigger or exit action's lines.
        const executingEmailLogs = logMessages.filter((msg) => msg === 'Executing action [Action:email_1]')
        expect(executingEmailLogs).toHaveLength(1)

        // The "Resuming workflow execution at" log fires at most once per dequeue — and the
        // routing-continuation dequeue should be silent. So we should never see a Resuming
        // line anchored on the email action (the first dequeue Starts at the trigger, not the
        // email step).
        const resumingEmailLogs = logMessages.filter(
            (msg) => msg.includes('Resuming workflow execution at') && msg.includes('[Action:email_1]')
        )
        expect(resumingEmailLogs).toHaveLength(0)

        // No "Workflow will pause until" lines either — the only pause in this workflow is the
        // sub-millisecond routing reschedule, which the suppression should hide. Real pauses
        // (delays, wait_until_condition, SES throttle retries) still log normally; they're
        // covered by other tests in this file and aren't exercised here.
        const pauseLogs = logMessages.filter((msg) => msg.startsWith('Workflow will pause until'))
        expect(pauseLogs).toHaveLength(0)
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

    it('suppresses routing logs in both directions across an email → fetch → email ping-pong', async () => {
        // Companion regression guard to the single-email test above, extended to the full
        // ping-pong (`hogflow → email → hogflow → email → exit`). Both routing directions
        // — `routeEmailToQueue` (hogflow → email) and `routeToQueue` (email → hogflow,
        // taken when a fetch action follows an email send) — go through the same
        // `finished: false` + nullish `queueScheduledAt` branch in HogFunctionHandler, so
        // both set `routingOnlyReschedule` and both routing dequeues should be silent in
        // the logs. This test asserts that on a four-action workflow with two emails and
        // a fetch between them, we still see exactly one Executing line per action and
        // zero Resuming-at-email/fetch lines.
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
                    email_1: emailAction('Ping-pong email 1'),
                    fetch_1: {
                        type: 'function',
                        config: {
                            template_id: 'template-workflows-e2e-fetch',
                            inputs: {
                                url: { value: 'https://example.com/ping-pong-fetch' },
                                method: { value: 'POST' },
                            },
                        },
                    },
                    email_2: emailAction('Ping-pong email 2'),
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

        // Wait for both emails sent + the workflow terminated, so all four routing
        // reschedules have happened and all their logs are in Kafka.
        await waitForExpect(() => {
            const sumCounts = (filter: (m: any) => boolean) =>
                mockProducerObserver
                    .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    .filter(filter)
                    .reduce((sum: number, m: any) => sum + m.value.count, 0)

            expect(sumCounts((m) => m.value.metric_name === 'email_sent')).toBe(2)
        }, 15000)

        await waitForExpect(async () => {
            const jobs = await queryCyclotronJobs()
            const terminal = jobs.filter(
                (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
            )
            expect(terminal.length).toBeGreaterThanOrEqual(1)
        }, 10000)

        const logMessages = mockProducerObserver
            .getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
            .map((m: any) => m.value.message as string)

        // Sanity: both emails actually sent (not a vacuous pass where suppression broke the
        // flow). The "Email sent" log lines are prefixed with `[Action:email_X]` via
        // `actionIdForLogging`, so we substring-match instead of equality-match.
        expect(logMessages.filter((msg) => msg.includes('Email sent to recipient@example.com'))).toHaveLength(2)

        // Each routed action runs across two dequeues but only the "real" execution should log.
        // - email_1 routes hogflow → email, sends on the email queue
        // - fetch_1 routes email → hogflow (because the next step is a non-email function),
        //   runs on the hogflow queue
        // - email_2 routes hogflow → email, sends on the email queue
        // - exit runs inline at the tail of email_2's dequeue.
        // Trigger is NOT in this list: `ensureCurrentAction` advances `currentAction` past
        // the trigger to its successor immediately, so the trigger action itself never
        // reaches the "Executing action" log site.
        for (const actionId of ['email_1', 'fetch_1', 'email_2', 'exit']) {
            const executingLogs = logMessages.filter((msg) => msg === `Executing action [Action:${actionId}]`)
            expect(executingLogs).toHaveLength(1)
        }

        // No `Resuming workflow execution at [Action:X]` lines for any of the routed actions.
        // The first dequeue Starts at the trigger; subsequent transitions are all routing
        // reschedules or in-loop next-action advances, none of which re-enter execute()
        // with a non-suppressed flag for these actions.
        for (const actionId of ['email_1', 'fetch_1', 'email_2']) {
            const resumingLogs = logMessages.filter(
                (msg) => msg.includes('Resuming workflow execution at') && msg.includes(`[Action:${actionId}]`)
            )
            expect(resumingLogs).toHaveLength(0)
        }

        // No `Workflow will pause until X` lines anywhere — the three routing reschedules
        // (email_1, fetch_1, email_2) are all sub-millisecond and have to be silenced.
        // The workflow has no delays or wait_until_condition steps so any pause log here
        // would be the routing leak we're guarding against.
        const pauseLogs = logMessages.filter((msg) => msg.startsWith('Workflow will pause until'))
        expect(pauseLogs).toHaveLength(0)
    })

    it('keeps logging real pauses (delay before email) while still suppressing the routing reschedule', async () => {
        // Counter-example test: the suppression must NOT silence real pauses. A workflow
        // with `trigger → delay → email → exit` produces two reschedules:
        //   1. The delay action returns an explicit `queueScheduledAt` 1s in the future
        //      (real pause — must keep logging "Workflow will pause until X" and the
        //      corresponding "Resuming workflow execution at [Action:delay_1]" on wake).
        //   2. The email action returns no `queueScheduledAt` (routing-only — must be
        //      silent in both directions).
        // If the fix over-reaches and suppresses real delay pauses, this test fails.
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
                    delay_1: { type: 'delay', config: { delay_duration: '1s' } },
                    email_1: {
                        type: 'function_email',
                        config: {
                            template_id: 'template-workflows-e2e-email',
                            inputs: {
                                email: {
                                    value: {
                                        to: { email: 'recipient@example.com', name: 'Recipient' },
                                        from: { integrationId: 1, email: 'sender@posthog.com' },
                                        subject: 'After-delay email',
                                        text: 'After-delay email',
                                        html: '<p>After-delay email</p>',
                                    },
                                },
                            },
                        },
                    },
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'delay_1', type: 'continue' },
                    { from: 'delay_1', to: 'email_1', type: 'continue' },
                    { from: 'email_1', to: 'exit', type: 'continue' },
                ],
            })
            .build()
        await insertHogFlow(hub.postgres, hogFlow)

        const { backgroundTask } = await eventsConsumer.processBatch([createGlobals()])
        await backgroundTask

        await waitForExpect(() => {
            const sumCounts = (filter: (m: any) => boolean) =>
                mockProducerObserver
                    .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                    .filter(filter)
                    .reduce((sum: number, m: any) => sum + m.value.count, 0)
            expect(sumCounts((m) => m.value.metric_name === 'email_sent')).toBe(1)
        }, 15000)

        await waitForExpect(async () => {
            const jobs = await queryCyclotronJobs()
            const terminal = jobs.filter(
                (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
            )
            expect(terminal.length).toBeGreaterThanOrEqual(1)
        }, 10000)

        const logMessages = mockProducerObserver
            .getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
            .map((m: any) => m.value.message as string)

        expect(logMessages.filter((msg) => msg.includes('Email sent to recipient@example.com'))).toHaveLength(1)

        // The delay is a genuine pause and must still be logged; the email's routing hop onto
        // the email queue must NOT add a duplicate. Assert exactly one pause and one resume line
        // overall, independent of which action each references — so the guard tests the
        // suppression's intent and stays valid regardless of whether the delay advances
        // currentAction before parking.
        const pauseLogs = logMessages.filter((msg) => msg.startsWith('Workflow will pause until'))
        expect(pauseLogs).toHaveLength(1)
        const resumeLogs = logMessages.filter((msg) => msg.includes('Resuming workflow execution at'))
        expect(resumeLogs).toHaveLength(1)
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

    it('rate-limited variant processes emails end-to-end through the dedicated bucket', async () => {
        // Verifies the inject-pattern wiring: CyclotronJobQueueRateLimitedPostgresV2
        // gates dequeue via a Valkey bucket, then the email worker processes the
        // job normally. Reuses the local test Redis as the bucket store (same
        // approach as rate-limiter.service.test.ts).
        await emailWorker.stop()

        const limiterValkey = createRedisV2PoolFromConfig({
            connection: hub.CDP_REDIS_HOST
                ? {
                      url: hub.CDP_REDIS_HOST,
                      options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
        const bucketKey = '@posthog-test/ses-e2e/bucket'
        await deleteKeysWithPrefix(limiterValkey, '@posthog-test/ses-e2e/')

        const rateLimitedQueue = new CyclotronJobQueueRateLimitedPostgresV2(hub.CONSUMER_BATCH_SIZE, hub, {
            limiter: new RateLimiterService(limiterValkey, { name: 'ses-e2e' }),
            key: bucketKey,
            capacity: 10,
            refillPerSecond: 10,
            throttledPollDelayMs: 50,
        })
        emailWorker = new CdpCyclotronWorkerEmail(hub, deps, rateLimitedQueue)
        await emailWorker.start()

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
                                        subject: 'Rate-limited email',
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

        const { backgroundTask } = await eventsConsumer.processBatch([createGlobals()])
        await backgroundTask

        // The email is sent — the rate-limited queue gated, dequeued, and processed the job.
        await waitForExpect(() => {
            const emailSentCount = mockProducerObserver
                .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                .filter((m: any) => m.value.metric_name === 'email_sent')
                .reduce((sum: number, m: any) => sum + m.value.count, 0)
            expect(emailSentCount).toBe(1)
        }, 15000)

        // The bucket has been touched — proves the rate limiter was actually consulted,
        // not bypassed. `ts` and `pool` are written on every claim (cold start or refill).
        const bucket = await limiterValkey.useClient({ name: 'read-bucket' }, (client) => client.hgetall(bucketKey))
        expect(bucket?.ts).toBeTruthy()
        expect(bucket?.pool).toBeTruthy()
    })

    it('rate-limits dequeue when the bucket drains, then drains the queue as it refills', async () => {
        // Tiny bucket (capacity 1, refill 2/sec = 1 token every 500ms) so the
        // worker has to wait for refills between sends. With 3 emails enqueued
        // we should see the bucket get denied at least once while the worker
        // is waiting — and all 3 should still eventually go through.
        await emailWorker.stop()

        const limiterValkey = createRedisV2PoolFromConfig({
            connection: hub.CDP_REDIS_HOST
                ? {
                      url: hub.CDP_REDIS_HOST,
                      options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
        const bucketKey = '@posthog-test/ses-e2e-throttled/bucket'
        await deleteKeysWithPrefix(limiterValkey, '@posthog-test/ses-e2e-throttled/')

        const limiterName = 'ses-e2e-throttled'
        const rateLimitedQueue = new CyclotronJobQueueRateLimitedPostgresV2(hub.CONSUMER_BATCH_SIZE, hub, {
            limiter: new RateLimiterService(limiterValkey, { name: limiterName }),
            key: bucketKey,
            capacity: 1,
            refillPerSecond: 2,
            throttledPollDelayMs: 50,
        })
        emailWorker = new CdpCyclotronWorkerEmail(hub, deps, rateLimitedQueue)
        await emailWorker.start()

        // Snapshot the denied counter so we measure only this test's claims.
        const readDeniedCount = async (): Promise<number> => {
            const metric = register.getSingleMetric('cdp_rate_limiter_claim_total')
            if (!metric) {
                return 0
            }
            const data = await metric.get()
            return data.values
                .filter(
                    (v: any) =>
                        v.labels.result === 'denied' && v.labels.limiter === limiterName && v.labels.key === bucketKey
                )
                .reduce((sum: number, v: any) => sum + v.value, 0)
        }
        const deniedBefore = await readDeniedCount()

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
                                        subject: 'Throttled email',
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

        // Three distinct events → three email jobs queued near-simultaneously.
        const events = Array.from({ length: 3 }, () => createGlobals({ uuid: new UUIDT().toString() }))
        const { backgroundTask } = await eventsConsumer.processBatch(events)
        await backgroundTask

        // All three eventually send — generous timeout because the bucket only
        // refills 2 tokens/sec.
        await waitForExpect(() => {
            const emailSentCount = mockProducerObserver
                .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                .filter((m: any) => m.value.metric_name === 'email_sent')
                .reduce((sum: number, m: any) => sum + m.value.count, 0)
            expect(emailSentCount).toBe(3)
        }, 20000)

        // The bucket was denied at least once during processing — proves the
        // gating actually fired, not that we just dequeued 3 jobs in a row.
        // (With capacity=1 and three pending jobs, between sends the worker
        // polls many times finding bucket=0.)
        const deniedAfter = await readDeniedCount()
        expect(deniedAfter - deniedBefore).toBeGreaterThan(0)
    })

    it('does not increment the limiter counter on idle polls (no work, no metric)', async () => {
        // Regression guard for the peek-before-claim fix. Without it, idle
        // workers would silently drain the bucket on every poll and the
        // denied counter would climb even with zero traffic.
        await emailWorker.stop()

        const limiterValkey = createRedisV2PoolFromConfig({
            connection: hub.CDP_REDIS_HOST
                ? {
                      url: hub.CDP_REDIS_HOST,
                      options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
        const bucketKey = '@posthog-test/ses-e2e-idle/bucket'
        await deleteKeysWithPrefix(limiterValkey, '@posthog-test/ses-e2e-idle/')

        const limiterName = 'ses-e2e-idle'
        const rateLimitedQueue = new CyclotronJobQueueRateLimitedPostgresV2(hub.CONSUMER_BATCH_SIZE, hub, {
            limiter: new RateLimiterService(limiterValkey, { name: limiterName }),
            key: bucketKey,
            capacity: 2,
            refillPerSecond: 1,
            throttledPollDelayMs: 50,
        })
        emailWorker = new CdpCyclotronWorkerEmail(hub, deps, rateLimitedQueue)
        await emailWorker.start()

        // Sum across all result labels — even granted_* would be wrong here
        // since no work exists. The whole counter family should be flat.
        const readAllResults = async (): Promise<number> => {
            const metric = register.getSingleMetric('cdp_rate_limiter_claim_total')
            if (!metric) {
                return 0
            }
            const data = await metric.get()
            return data.values
                .filter((v: any) => v.labels.limiter === limiterName && v.labels.key === bucketKey)
                .reduce((sum: number, v: any) => sum + v.value, 0)
        }

        const before = await readAllResults()

        // Let the worker poll for a full second with no jobs queued — that's
        // ~20 poll cycles at the default 50ms cadence. None should claim.
        await new Promise((resolve) => setTimeout(resolve, 1000))

        const after = await readAllResults()
        expect(after - before).toBe(0)
    })

    it('claims only the visible row count (sparse traffic does not drain the bucket)', async () => {
        // Regression guard for the pre-size fix. Without it, a single ready
        // email would claim the bucket's full capacity — draining ~capacity-1
        // tokens of SES budget per actual send — even though the worker can
        // only dequeue one row. Pre-sizing asks the limiter for exactly the
        // number of rows the worker is about to dequeue.
        //
        // refillPerSecond=0 freezes the bucket between the claim and our
        // assertion, so the post-claim pool is a deterministic measure of
        // what was deducted (capacity minus tokens granted on the one claim).
        await emailWorker.stop()

        const limiterValkey = createRedisV2PoolFromConfig({
            connection: hub.CDP_REDIS_HOST
                ? {
                      url: hub.CDP_REDIS_HOST,
                      options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
        const bucketKey = '@posthog-test/ses-e2e-presize/bucket'
        await deleteKeysWithPrefix(limiterValkey, '@posthog-test/ses-e2e-presize/')

        const capacity = 10
        const rateLimitedQueue = new CyclotronJobQueueRateLimitedPostgresV2(hub.CONSUMER_BATCH_SIZE, hub, {
            limiter: new RateLimiterService(limiterValkey, { name: 'ses-e2e-presize' }),
            key: bucketKey,
            capacity,
            refillPerSecond: 0,
            throttledPollDelayMs: 50,
        })
        emailWorker = new CdpCyclotronWorkerEmail(hub, deps, rateLimitedQueue)
        await emailWorker.start()

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
                                        subject: 'Sparse-traffic email',
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

        // Exactly ONE event → one email job — the sparse-traffic scenario.
        const { backgroundTask } = await eventsConsumer.processBatch([createGlobals({ uuid: new UUIDT().toString() })])
        await backgroundTask

        await waitForExpect(() => {
            const emailSentCount = mockProducerObserver
                .getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)
                .filter((m: any) => m.value.metric_name === 'email_sent')
                .reduce((sum: number, m: any) => sum + m.value.count, 0)
            expect(emailSentCount).toBe(1)
        }, 15000)

        // Bucket should retain ~capacity-1 tokens — we claimed 1, not capacity.
        // Without the pre-size fix `pool` would be 0 here (the whole bucket
        // drained on the one claim).
        const bucket = await limiterValkey.useClient({ name: 'read-bucket' }, (client) => client.hgetall(bucketKey))
        const pool = parseFloat(bucket?.pool ?? '0')
        expect(pool).toBeGreaterThanOrEqual(capacity - 1)
    })

    // ---- Message-assets bulk flush at the batch boundary ----
    //
    // Email assets used to be produced one-at-a-time via a fire-and-forget Kafka call
    // from `email.service.ts → MessageAssetsService.captureSentEmail`. We've moved that
    // to a buffer-then-flush pattern that drains `result.emailAssets` at the batch
    // boundary and bulk-produces, gated on broker ack before the consumer commits
    // offsets. These tests pin the end-to-end behavior: one workflow → one asset row in
    // the `message_assets` Kafka topic with the right metadata, and a single batch with
    // multiple emails produces all rows. The kill-switch is flipped on in this block's
    // `beforeEach` so the asset Kafka topic actually receives writes.
    describe('message_assets bulk capture', () => {
        const buildEmailWorkflow = (subject: string) =>
            new FixtureHogFlowBuilder()
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
                                            subject,
                                            text: 'plain text body',
                                            html: `<p>${subject}</p>`,
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

        const assetMessages = (): { key: string; value: any }[] =>
            mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_MESSAGE_ASSETS) as any

        it('produces one message_assets row per workflow email with the rendered HTML and metadata', async () => {
            const hogFlow = buildEmailWorkflow('Asset bulk-capture single')
            await insertHogFlow(hub.postgres, hogFlow)

            const { backgroundTask } = await eventsConsumer.processBatch([createGlobals()])
            await backgroundTask

            // The asset row only lands once the email worker's batch flushes — wait for
            // the workflow to reach a terminal state, then assert against the topic.
            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const terminal = jobs.filter(
                    (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
                )
                expect(terminal.length).toBeGreaterThanOrEqual(1)
            }, 15000)

            await waitForExpect(() => {
                const rows = assetMessages()
                expect(rows).toHaveLength(1)

                const row = rows[0].value as Record<string, any>
                expect(row.team_id).toBe(team.id)
                expect(row.function_kind).toBe('hog_flow')
                expect(row.kind).toBe('email')
                expect(row.status).toBe('sent')
                expect(row.action_id).toBe('email_1')
                expect(row.recipient).toBe('recipient@example.com')
                expect(row.subject).toBe('Asset bulk-capture single')
                expect(row.html).toBe('<p>Asset bulk-capture single</p>')
                // Partition key must match invocation_id so retries collapse via the
                // destination ReplacingMergeTree(version).
                expect(rows[0].key).toBe(row.invocation_id)
            }, 15000)
        })

        it('bulk-captures every asset when multiple workflow runs share a batch', async () => {
            // Use distinct subjects so we can assert on row content regardless of the
            // partition-level ordering the Kafka producer chooses.
            const hogFlow = buildEmailWorkflow('Bulk asset capture')
            await insertHogFlow(hub.postgres, hogFlow)

            // Three globals dispatched in one `processBatch` call — they go through the
            // events consumer together. Each fires its own workflow run, each emits one
            // asset; the bulk-flush is what we're exercising.
            const { backgroundTask } = await eventsConsumer.processBatch([
                createGlobals({ uuid: 'aaaaaaaa-0000-0000-0000-000000000001' as any }),
                createGlobals({ uuid: 'aaaaaaaa-0000-0000-0000-000000000002' as any }),
                createGlobals({ uuid: 'aaaaaaaa-0000-0000-0000-000000000003' as any }),
            ])
            await backgroundTask

            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const terminal = jobs.filter(
                    (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
                )
                expect(terminal.length).toBeGreaterThanOrEqual(3)
            }, 20000)

            await waitForExpect(() => {
                const rows = assetMessages()
                expect(rows.length).toBeGreaterThanOrEqual(3)

                // Every produced row must carry distinct invocation_id values (one per
                // workflow run) — otherwise the buffer is dropping or aliasing rows.
                const invocationIds = new Set(rows.map((r) => (r.value as any).invocation_id))
                expect(invocationIds.size).toBeGreaterThanOrEqual(3)

                // Subject and HTML are constant across the three runs (same flow), so we
                // just sanity-check that every row carries the expected shape.
                for (const row of rows) {
                    const value = row.value as Record<string, any>
                    expect(value.subject).toBe('Bulk asset capture')
                    expect(value.html).toBe('<p>Bulk asset capture</p>')
                    expect(value.kind).toBe('email')
                    expect(value.status).toBe('sent')
                    expect(row.key).toBe(value.invocation_id)
                }
            }, 20000)
        })

        it('emits no message_assets rows when the kill-switch is disabled', async () => {
            // Restart the email worker with capture disabled — `MessageAssetsService` reads
            // the config at construction time, so we have to recreate the deps + worker.
            await emailWorker.stop()
            hub.MESSAGE_ASSETS_CAPTURE_ENABLED = false
            deps = createCdpConsumerDeps(hub, kafkaProducer)
            const restartedQueue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)
            emailWorker = new CdpCyclotronWorkerEmail(hub, deps, restartedQueue)
            await emailWorker.start()

            mockProducerObserver.resetKafkaProducer()

            const hogFlow = buildEmailWorkflow('Capture disabled')
            await insertHogFlow(hub.postgres, hogFlow)

            const { backgroundTask } = await eventsConsumer.processBatch([createGlobals()])
            await backgroundTask

            await waitForExpect(async () => {
                const jobs = await queryCyclotronJobs()
                const terminal = jobs.filter(
                    (j: any) => j.status === 'completed' || j.status === 'failed' || j.status === 'canceled'
                )
                expect(terminal.length).toBeGreaterThanOrEqual(1)
            }, 15000)

            // Give the asset producer a chance to run — if anything is going to fire it
            // happens within the same flush window. Re-check after a short delay so we
            // don't accept a false negative from races.
            await new Promise((resolve) => setTimeout(resolve, 500))
            expect(assetMessages()).toHaveLength(0)
        })
    })
})

/**
 * E2E for the batch resolver dispatch path through the cdp-api HTTP boundary.
 *
 * Goes through real express + supertest, real CdpApi, real cyclotron-node
 * Postgres. Verifies that POST `/batch_invocations/<id>` creates a resolver
 * cyclotron job pointing at the right queue with the right state.
 *
 * The deep state-machine paths (page execution, terminal write, truncation,
 * Django down → resolver parks) are covered by the integration tests in
 * `consumers/cdp-cyclotron-worker-batch-resolve.consumer.test.ts`. This
 * test is the boundary backstop — it caught a real bug (wrong DB URL on
 * the resolver manager) during development.
 *
 * Hub lifecycle follows cdp-api.test.ts: one hub for the suite (beforeAll),
 * torn down once (afterAll). Per-test isolation comes from resetting the
 * postgres team data + truncating cyclotron_jobs in beforeEach.
 */

/**
 * E2E for the cyclotron batch resolver. POST through cdp-api, real consumer
 * loop, mocked Django endpoints, assert on the resulting cyclotron + Django
 * state. Mirrors how the system runs in prod — no manual dequeue plumbing.
 */
describe('Workflows E2E: batch resolver dispatch via cdp-api', () => {
    jest.setTimeout(60000)

    const CYCLOTRON_NODE_DB_URL =
        process.env.CYCLOTRON_NODE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

    let hub: Hub
    let team: Team
    let cyclotronPool: Pool
    let app: express.Application
    let server: any
    let api: CdpApi
    let batchResolverProducer: CyclotronV2Manager
    let deps: ReturnType<typeof createCdpConsumerDeps>
    // Fresh consumer per test — built in the it() body, stopped in afterEach.
    let resolverWorker: CdpCyclotronWorkerBatchResolve | undefined

    beforeAll(async () => {
        cyclotronPool = new Pool({ connectionString: CYCLOTRON_NODE_DB_URL })

        MockKafkaProducerWrapper.create = jest.fn((...args) => ActualKafkaProducerWrapper.create(...args))
        await ensureKafkaTopics(TEST_KAFKA_TOPICS)

        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })

        const { createMockJobQueue } = require('../../tests/helpers/mocks/job-queue.mock')
        deps = createCdpConsumerDeps(hub)
        batchResolverProducer = new CyclotronV2Manager({
            pool: { dbUrl: CYCLOTRON_NODE_DB_URL, maxConnections: 5 },
        })
        api = new CdpApi(
            hub,
            deps,
            { hogQueue: createMockJobQueue(), hogflowQueue: createMockJobQueue() },
            batchResolverProducer
        )
        app = setupExpressApp()
        app.use('/', api.router())
        server = app.listen(0, () => {})
    })

    afterAll(async () => {
        server?.close()
        await batchResolverProducer?.disconnect()
        await closeHub(hub)
        await cyclotronPool.end()
    })

    beforeEach(async () => {
        await resetTestDatabase()
        await cyclotronPool.query(`DELETE FROM cyclotron_jobs`)
        team = await getFirstTeam(hub.postgres)
        resolverWorker = undefined
    })

    afterEach(async () => {
        // If the test started the consumer, shut it down before the next test.
        // resolverWorker.stop() waits for any in-flight processBatch to settle,
        // then closes the pool — so afterAll's closeHub has no leftover work.
        await resolverWorker?.stop()
    })

    // Fresh worker per test — stop() disconnects the underlying Postgres pool,
    // so a shared instance can't survive past the first test's afterEach.
    function buildResolverConsumer(): CdpCyclotronWorkerBatchResolve {
        const cyclotronWorker = new CyclotronV2Worker({
            pool: { dbUrl: CYCLOTRON_NODE_DB_URL, maxConnections: 10 },
            queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
            pollDelayMs: 100,
        })
        const internalFetchService = new InternalFetchService(hub.INTERNAL_API_BASE_URL, hub.INTERNAL_API_SECRET)
        const queryService = new HogFlowBatchPersonQueryService(internalFetchService)
        return new CdpCyclotronWorkerBatchResolve(hub, deps, cyclotronWorker, queryService, internalFetchService)
    }

    async function insertActiveBatchFlow(): Promise<HogFlow> {
        const flow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: {
                            type: 'batch',
                            filters: { properties: [{ key: 'plan', value: 'enterprise', type: 'person' }] },
                        },
                    },
                    function_1: {
                        type: 'function',
                        config: {
                            template_id: 'template-workflows-e2e-fetch',
                            inputs: { url: { value: 'https://example.com/batch' } },
                        },
                    },
                },
                edges: [{ from: 'trigger', to: 'function_1', type: 'continue' }],
            })
            .build()
        return await insertHogFlow(hub.postgres, flow)
    }

    it('POST /batch_invocations with flag on creates a resolver cyclotron job with the right shape', async () => {
        const flow = await insertActiveBatchFlow()
        const parentRunId = new UUIDT().toString()

        const response = await supertest(app)
            .post(`/api/projects/${team.id}/hog_flows/${flow.id}/batch_invocations/${parentRunId}`)
            .send({
                filters: { filter_test_accounts: false },
                max_audience_size: 750,
                variables: { greeting: 'hi' },
                group_type_index: 2,
            })
            .expect(200)

        expect(response.body).toEqual({ status: 'queued' })

        const rows = await cyclotronPool.query<{
            id: string
            queue_name: string
            status: string
            parent_run_id: string
            team_id: number
            function_id: string
            state: Buffer | null
        }>(
            `SELECT id, queue_name, status::text AS status, parent_run_id, team_id, function_id, state
             FROM cyclotron_jobs
             WHERE queue_name = 'hogflow_batch_resolve' AND parent_run_id = $1`,
            [parentRunId]
        )
        expect(rows.rows).toHaveLength(1)
        const job = rows.rows[0]
        expect(job.status).toBe('available')
        expect(job.parent_run_id).toBe(parentRunId)
        expect(job.team_id).toBe(team.id)
        expect(job.function_id).toBe(flow.id)

        const state = parseJSON((job.state as Buffer).toString('utf-8')) as Record<string, unknown>
        expect(state).toMatchObject({
            batchJobId: parentRunId,
            teamId: team.id,
            hogFlowId: flow.id,
            maxAudienceSize: 750,
            variables: { greeting: 'hi' },
            groupTypeIndex: 2,
            cursor: null,
            totalEnqueued: 0,
            pagesProcessed: 0,
        })
        expect(state.pendingTerminal).toBeUndefined()
    })

    it('rejects with 400 when the workflow is not a batch trigger', async () => {
        const flow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: { type: 'event', filters: {} },
                    },
                    function_1: {
                        type: 'function',
                        config: {
                            template_id: 'template-workflows-e2e-fetch',
                            inputs: { url: { value: 'https://example.com/' } },
                        },
                    },
                },
                edges: [{ from: 'trigger', to: 'function_1', type: 'continue' }],
            })
            .build()
        const inserted = await insertHogFlow(hub.postgres, flow)
        const parentRunId = new UUIDT().toString()

        await supertest(app)
            .post(`/api/projects/${team.id}/hog_flows/${inserted.id}/batch_invocations/${parentRunId}`)
            .send({ filters: { filter_test_accounts: false } })
            .expect(400)

        const rows = await cyclotronPool.query(`SELECT id FROM cyclotron_jobs WHERE parent_run_id = $1`, [parentRunId])
        expect(rows.rows).toHaveLength(0)
    })

    it('full lifecycle: HTTP POST → resolver chunks 3 pages → children enqueued → Django PUT status=completed', async () => {
        const flow = await insertActiveBatchFlow()
        const parentRunId = new UUIDT().toString()

        const personIds = [
            new UUIDT().toString(),
            new UUIDT().toString(),
            new UUIDT().toString(),
            new UUIDT().toString(),
            new UUIDT().toString(),
        ]
        const statusPuts: Array<{ status: string }> = []
        let personPageCalls = 0

        mockInternalFetch.mockImplementation((url: string, opts: any) => {
            if (url.includes('/user_blast_radius_persons')) {
                personPageCalls += 1
                const pages = [
                    { users_affected: personIds.slice(0, 2), cursor: 'c1', has_more: true },
                    { users_affected: personIds.slice(2, 4), cursor: 'c2', has_more: true },
                    { users_affected: personIds.slice(4), cursor: null, has_more: false },
                ]
                const page = pages[Math.min(personPageCalls - 1, pages.length - 1)]
                return Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve(JSON.stringify(page)),
                    dump: () => Promise.resolve(),
                })
            }
            if (url.includes('/batch_jobs/') && url.endsWith('/status')) {
                statusPuts.push(parseJSON(opts.body) as { status: string })
                return Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                })
            }
            return Promise.reject(new Error(`Unexpected internalFetch call to ${url}`))
        })

        await supertest(app)
            .post(`/api/projects/${team.id}/hog_flows/${flow.id}/batch_invocations/${parentRunId}`)
            .send({ filters: { filter_test_accounts: false }, max_audience_size: 1000 })
            .expect(200)

        // Start the consumer — it'll pick up the resolver job and process pages
        // on its own polling loop. waitForExpect waits for the terminal Django
        // PUT, which only happens after all 3 pages + the terminal-write phase.
        resolverWorker = buildResolverConsumer()
        await resolverWorker.start()

        await waitForExpect(() => {
            expect(statusPuts).toHaveLength(1)
        }, 20000)

        expect(personPageCalls).toBe(3)
        expect(statusPuts[0]).toEqual({ status: 'completed' })

        const children = await cyclotronPool.query(
            `SELECT id FROM cyclotron_jobs WHERE queue_name = 'hogflow' AND parent_run_id = $1`,
            [parentRunId]
        )
        expect(children.rows).toHaveLength(personIds.length)
    })

    it('failed lifecycle: workflow deleted before processing → resolver transitions to failed → Django PUT status=failed', async () => {
        const flow = await insertActiveBatchFlow()
        const parentRunId = new UUIDT().toString()
        const statusPuts: Array<{ status: string }> = []

        mockInternalFetch.mockImplementation((url: string, opts: any) => {
            if (url.includes('/batch_jobs/') && url.endsWith('/status')) {
                statusPuts.push(parseJSON(opts.body) as { status: string })
                return Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                })
            }
            // Audience fetch shouldn't be reached — the resolver bails on missing
            // hogflow before getting that far.
            return Promise.reject(new Error(`Unexpected internalFetch call to ${url}`))
        })

        // Dispatch BEFORE starting the consumer so we can sabotage the workflow
        // before any processing happens (otherwise the consumer would race us
        // and process the job before we delete the workflow).
        await supertest(app)
            .post(`/api/projects/${team.id}/hog_flows/${flow.id}/batch_invocations/${parentRunId}`)
            .send({ filters: { filter_test_accounts: false }, max_audience_size: 1000 })
            .expect(200)

        // Sabotage: customer deletes the workflow between dispatch and processing.
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `DELETE FROM posthog_hogflow WHERE id = $1`,
            [flow.id],
            'delete-hogflow-for-test'
        )
        // The consumer we're about to build will have its own hogFlowManager
        // with an empty cache, so refresh isn't strictly needed — but be
        // explicit so the test isn't sensitive to cache lifecycle changes.

        resolverWorker = buildResolverConsumer()
        await resolverWorker.start()

        await waitForExpect(() => {
            expect(statusPuts).toHaveLength(1)
        }, 20000)

        expect(statusPuts[0]).toEqual({ status: 'failed' })

        const children = await cyclotronPool.query(
            `SELECT id FROM cyclotron_jobs WHERE queue_name = 'hogflow' AND parent_run_id = $1`,
            [parentRunId]
        )
        expect(children.rows).toHaveLength(0)
    })

    it('Django down: resolver retries the terminal PUT instead of acking', async () => {
        const flow = await insertActiveBatchFlow()
        const parentRunId = new UUIDT().toString()
        const personIds = [new UUIDT().toString()]
        let putAttempts = 0

        mockInternalFetch.mockImplementation((url: string) => {
            if (url.includes('/user_blast_radius_persons')) {
                return Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () =>
                        Promise.resolve(
                            JSON.stringify({
                                users_affected: personIds,
                                cursor: null,
                                has_more: false,
                            })
                        ),
                    dump: () => Promise.resolve(),
                })
            }
            if (url.includes('/batch_jobs/') && url.endsWith('/status')) {
                putAttempts += 1
                return Promise.resolve({
                    status: 503,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve('Service Unavailable'),
                    dump: () => Promise.resolve(),
                })
            }
            return Promise.reject(new Error(`Unexpected internalFetch call to ${url}`))
        })

        await supertest(app)
            .post(`/api/projects/${team.id}/hog_flows/${flow.id}/batch_invocations/${parentRunId}`)
            .send({ filters: { filter_test_accounts: false }, max_audience_size: 1000 })
            .expect(200)

        resolverWorker = buildResolverConsumer()
        await resolverWorker.start()

        // Wait until at least one Django PUT attempt has happened — proves the
        // resolver reached the terminal-write phase. Then verify the resolver
        // job is parked (status='available' with pendingTerminal still set),
        // not acked.
        await waitForExpect(() => {
            expect(putAttempts).toBeGreaterThanOrEqual(1)
        }, 20000)

        const rows = await cyclotronPool.query<{ status: string; state: Buffer | null }>(
            `SELECT status::text AS status, state FROM cyclotron_jobs
             WHERE queue_name = 'hogflow_batch_resolve' AND parent_run_id = $1`,
            [parentRunId]
        )
        expect(rows.rows).toHaveLength(1)
        expect(rows.rows[0].status).toBe('available')
        const state = parseJSON((rows.rows[0].state as Buffer).toString('utf-8')) as { pendingTerminal?: string }
        expect(state.pendingTerminal).toBe('completed')
    })

    it('audience fetch failure: resolver reschedules with backoff, cursor unchanged, no children enqueued', async () => {
        const flow = await insertActiveBatchFlow()
        const parentRunId = new UUIDT().toString()
        let fetchAttempts = 0

        mockInternalFetch.mockImplementation((url: string) => {
            if (url.includes('/user_blast_radius_persons')) {
                fetchAttempts += 1
                // Audience fetch always fails — resolver should keep retrying,
                // never advance the cursor, never enqueue children.
                return Promise.reject(new Error('The operation was aborted due to timeout'))
            }
            return Promise.reject(new Error(`Unexpected internalFetch call to ${url}`))
        })

        await supertest(app)
            .post(`/api/projects/${team.id}/hog_flows/${flow.id}/batch_invocations/${parentRunId}`)
            .send({ filters: { filter_test_accounts: false }, max_audience_size: 1000 })
            .expect(200)

        resolverWorker = buildResolverConsumer()
        await resolverWorker.start()

        await waitForExpect(() => {
            expect(fetchAttempts).toBeGreaterThanOrEqual(1)
        }, 20000)

        const rows = await cyclotronPool.query<{ status: string; state: Buffer | null }>(
            `SELECT status::text AS status, state FROM cyclotron_jobs
             WHERE queue_name = 'hogflow_batch_resolve' AND parent_run_id = $1`,
            [parentRunId]
        )
        expect(rows.rows).toHaveLength(1)
        expect(rows.rows[0].status).toBe('available')
        const state = parseJSON((rows.rows[0].state as Buffer).toString('utf-8')) as {
            cursor: string | null
            totalEnqueued: number
            pagesProcessed: number
            pendingTerminal?: string
        }
        expect(state.cursor).toBeNull() // never advanced
        expect(state.totalEnqueued).toBe(0)
        expect(state.pagesProcessed).toBe(0)
        expect(state.pendingTerminal).toBeUndefined()

        const children = await cyclotronPool.query(
            `SELECT id FROM cyclotron_jobs WHERE queue_name = 'hogflow' AND parent_run_id = $1`,
            [parentRunId]
        )
        expect(children.rows).toHaveLength(0)
    })

    it('truncation: pre-existing job at maxAudienceSize skips fetch + emits customer log + writes status=completed', async () => {
        // Pre-populate a resolver job at the cap so the next dequeue takes
        // the truncation branch (audience fetch never runs).
        const flow = await insertActiveBatchFlow()
        const parentRunId = new UUIDT().toString()
        const statusPuts: Array<{ status: string }> = []

        mockInternalFetch.mockImplementation((url: string, opts: any) => {
            if (url.includes('/batch_jobs/') && url.endsWith('/status')) {
                statusPuts.push(parseJSON(opts.body) as { status: string })
                return Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                })
            }
            return Promise.reject(new Error(`Unexpected internalFetch call to ${url}`))
        })

        const cappedState = serializeResolverState({
            batchJobId: parentRunId,
            teamId: team.id,
            hogFlowId: flow.id,
            filters: { properties: [], filter_test_accounts: false },
            variables: {},
            maxAudienceSize: 100,
            cursor: 'some-cursor',
            totalEnqueued: 100,
            pagesProcessed: 1,
            attempts: 0,
            startedAt: new Date().toISOString(),
        })
        await batchResolverProducer.createJob({
            teamId: team.id,
            queueName: 'hogflow_batch_resolve',
            parentRunId,
            functionId: flow.id,
            state: cappedState,
        })

        resolverWorker = buildResolverConsumer()
        await resolverWorker.start()

        await waitForExpect(() => {
            expect(statusPuts).toHaveLength(1)
        }, 20000)

        // Status PUT was completed (truncation is still success, not failure)
        expect(statusPuts[0]).toEqual({ status: 'completed' })

        // No children — the resolver short-circuited before audience fetch
        const children = await cyclotronPool.query(
            `SELECT id FROM cyclotron_jobs WHERE queue_name = 'hogflow' AND parent_run_id = $1`,
            [parentRunId]
        )
        expect(children.rows).toHaveLength(0)
    })

    it('persistent fetch failure exhausts MAX_RESOLVER_ATTEMPTS → flips to pendingTerminal=failed and writes status=failed', async () => {
        // Pre-populate a resolver job already one retry below the cap so we
        // only need to drive a single more fetch failure to cross the
        // threshold — avoids burning 5x backoff windows in CI.
        const flow = await insertActiveBatchFlow()
        const parentRunId = new UUIDT().toString()
        const statusPuts: Array<{ status: string }> = []
        let fetchAttempts = 0

        mockInternalFetch.mockImplementation((url: string, opts: any) => {
            if (url.includes('/user_blast_radius_persons')) {
                fetchAttempts += 1
                return Promise.reject(new Error('ClickHouse permanently rejecting the audience query'))
            }
            if (url.includes('/batch_jobs/') && url.endsWith('/status')) {
                statusPuts.push(parseJSON(opts.body) as { status: string })
                return Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                })
            }
            return Promise.reject(new Error(`Unexpected internalFetch call to ${url}`))
        })

        const seededState = serializeResolverState({
            batchJobId: parentRunId,
            teamId: team.id,
            hogFlowId: flow.id,
            filters: { properties: [], filter_test_accounts: false },
            variables: {},
            maxAudienceSize: 1000,
            cursor: null,
            totalEnqueued: 0,
            pagesProcessed: 0,
            attempts: MAX_RESOLVER_ATTEMPTS - 1,
            startedAt: new Date().toISOString(),
        })
        await batchResolverProducer.createJob({
            teamId: team.id,
            queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
            parentRunId,
            functionId: flow.id,
            state: seededState,
        })

        resolverWorker = buildResolverConsumer()
        await resolverWorker.start()

        await waitForExpect(() => {
            expect(statusPuts).toHaveLength(1)
        }, 20000)

        expect(statusPuts[0]).toEqual({ status: 'failed' })
        expect(fetchAttempts).toBe(1) // one more retry consumed the last attempt budget

        // No children enqueued — the resolver bailed before ever returning a page
        const children = await cyclotronPool.query(
            `SELECT id FROM cyclotron_jobs WHERE queue_name = 'hogflow' AND parent_run_id = $1`,
            [parentRunId]
        )
        expect(children.rows).toHaveLength(0)
    })

    it('persistent Django 4xx on terminal write exhausts MAX_RESOLVER_ATTEMPTS → job.fail()', async () => {
        // Pre-populate a job already in the terminal-write phase with attempts
        // one below the cap. The 404 response is a permanent failure — no
        // amount of retrying will make Django accept it (the row is gone) —
        // so the resolver should give up and fail the cyclotron job instead
        // of looping forever.
        const flow = await insertActiveBatchFlow()
        const parentRunId = new UUIDT().toString()
        let putAttempts = 0

        mockInternalFetch.mockImplementation((url: string) => {
            if (url.includes('/batch_jobs/') && url.endsWith('/status')) {
                putAttempts += 1
                return Promise.resolve({
                    status: 404,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve('Not Found'),
                    dump: () => Promise.resolve(),
                })
            }
            return Promise.reject(new Error(`Unexpected internalFetch call to ${url}`))
        })

        const pendingState = serializeResolverState({
            batchJobId: parentRunId,
            teamId: team.id,
            hogFlowId: flow.id,
            filters: { properties: [], filter_test_accounts: false },
            variables: {},
            maxAudienceSize: 1000,
            cursor: 'last-cursor',
            totalEnqueued: 5,
            pagesProcessed: 1,
            attempts: MAX_RESOLVER_ATTEMPTS - 1,
            startedAt: new Date().toISOString(),
            pendingTerminal: 'completed',
        })
        await batchResolverProducer.createJob({
            teamId: team.id,
            queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
            parentRunId,
            functionId: flow.id,
            state: pendingState,
        })

        resolverWorker = buildResolverConsumer()
        await resolverWorker.start()

        await waitForExpect(async () => {
            const r = await cyclotronPool.query<{ status: string }>(
                `SELECT status::text AS status FROM cyclotron_jobs
                 WHERE queue_name = 'hogflow_batch_resolve' AND parent_run_id = $1`,
                [parentRunId]
            )
            expect(r.rows[0]?.status).toBe('failed')
        }, 20000)

        // One more attempt consumed the budget, then the job failed
        expect(putAttempts).toBe(1)
    })

    it('hard cap: page that would cross maxAudienceSize is truncated before enqueue', async () => {
        // maxAudienceSize=4 with pages of 3. Without the hard cap the resolver
        // would enqueue 6 children (overshoot by 2) then notice and truncate.
        // With the hard cap the second page is truncated to 1 row so the
        // total never exceeds 4.
        const flow = await insertActiveBatchFlow()
        const parentRunId = new UUIDT().toString()
        const personIds = Array.from({ length: 6 }, () => new UUIDT().toString())
        const statusPuts: Array<{ status: string }> = []
        let personPageCalls = 0

        mockInternalFetch.mockImplementation((url: string, opts: any) => {
            if (url.includes('/user_blast_radius_persons')) {
                personPageCalls += 1
                const pages = [
                    { users_affected: personIds.slice(0, 3), cursor: 'c1', has_more: true },
                    { users_affected: personIds.slice(3, 6), cursor: 'c2', has_more: true },
                ]
                const page = pages[Math.min(personPageCalls - 1, pages.length - 1)]
                return Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve(JSON.stringify(page)),
                    dump: () => Promise.resolve(),
                })
            }
            if (url.includes('/batch_jobs/') && url.endsWith('/status')) {
                statusPuts.push(parseJSON(opts.body) as { status: string })
                return Promise.resolve({
                    status: 200,
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve('{}'),
                    dump: () => Promise.resolve(),
                })
            }
            return Promise.reject(new Error(`Unexpected internalFetch call to ${url}`))
        })

        await supertest(app)
            .post(`/api/projects/${team.id}/hog_flows/${flow.id}/batch_invocations/${parentRunId}`)
            .send({ filters: { filter_test_accounts: false }, max_audience_size: 4 })
            .expect(200)

        resolverWorker = buildResolverConsumer()
        await resolverWorker.start()

        await waitForExpect(() => {
            expect(statusPuts).toHaveLength(1)
        }, 20000)

        expect(statusPuts[0]).toEqual({ status: 'completed' })

        const children = await cyclotronPool.query(
            `SELECT id FROM cyclotron_jobs WHERE queue_name = 'hogflow' AND parent_run_id = $1`,
            [parentRunId]
        )
        // Hard cap: exactly 4 children, never 6
        expect(children.rows).toHaveLength(4)
    })

    it('invalid resolver state: garbage bytes → job.fail() (not retry)', async () => {
        // Insert a resolver job with state that doesn't match the Zod schema.
        // Simulates schema drift, corruption, or a row written by an
        // incompatible older deploy. The resolver must FAIL the job (terminal)
        // rather than reschedule — otherwise we'd retry-loop forever on a job
        // that can never succeed.
        const parentRunId = new UUIDT().toString()
        const malformedState = Buffer.from(JSON.stringify({ not: 'a valid resolver state' }))
        await batchResolverProducer.createJob({
            teamId: team.id,
            queueName: 'hogflow_batch_resolve',
            parentRunId,
            functionId: new UUIDT().toString(),
            state: malformedState,
        })

        mockInternalFetch.mockImplementation((url: string) =>
            Promise.reject(new Error(`Unexpected internalFetch call to ${url}`))
        )

        resolverWorker = buildResolverConsumer()
        await resolverWorker.start()

        await waitForExpect(async () => {
            const r = await cyclotronPool.query<{ status: string }>(
                `SELECT status::text AS status FROM cyclotron_jobs
                 WHERE queue_name = 'hogflow_batch_resolve' AND parent_run_id = $1`,
                [parentRunId]
            )
            expect(r.rows[0]?.status).toBe('failed')
        }, 20000)

        // No children, no Django PUT — the resolver failed before any work.
        const children = await cyclotronPool.query(
            `SELECT id FROM cyclotron_jobs WHERE queue_name = 'hogflow' AND parent_run_id = $1`,
            [parentRunId]
        )
        expect(children.rows).toHaveLength(0)
    })
})
