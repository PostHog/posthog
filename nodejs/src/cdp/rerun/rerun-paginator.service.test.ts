import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'

import { ClickHouseClient } from '@clickhouse/client'
import { DateTime } from 'luxon'

import { KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'
import { ensureKafkaTopics, resetKafka } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { insertHogFunction as _insertHogFunction, createHogExecutionGlobals } from '../_tests/fixtures'
import { createCdpOutputsRegistry } from '../outputs/registry'
import { HogFlowManagerService } from '../services/hogflows/hogflow-manager.service'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { HogFunctionManagerService } from '../services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../services/monitoring/hog-function-monitoring.service'
import { HogInvocationResultsService } from '../services/monitoring/hog-invocation-results.service'
import { CyclotronJobInvocationHogFunction, HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { RERUN_PAGE_SIZE, RerunJobState } from './rerun-job.types'
import { RerunPaginatorService } from './rerun-paginator.service'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

/**
 * Integration test for RerunPaginatorService.
 *
 * Instead of mocking the ClickHouse client, this test seeds real lifecycle rows
 * through `HogInvocationResultsService.queueLifecycleRow` → Kafka → ClickHouse
 * Kafka MV → `hog_invocation_results`, then runs the paginator against the real
 * data. Only the side effects the paginator emits (the running lifecycle row +
 * the cyclotron re-enqueue) are mocked, so we can assert what got produced.
 *
 * This proves the whole pipeline end-to-end: the queueLifecycleRow shape that
 * the worker uses, the Kafka MV's JSON parsing, and the paginator's argMax
 * collapse query all line up.
 */
describe('RerunPaginatorService integration', () => {
    jest.setTimeout(60_000)

    let hub: Hub
    let kafkaProducer: KafkaProducerWrapper
    let team: Team
    let clickhouse: Clickhouse
    let hogFunction: HogFunctionType
    let seedingService: HogInvocationResultsService
    let chClient: ClickHouseClient
    let paginator: RerunPaginatorService
    // hog functions re-enqueue to the kafka queue, hog flows to postgres-v2.
    let hogQueue: jest.Mocked<JobQueue>
    let hogflowQueue: jest.Mocked<CyclotronJobQueuePostgresV2>
    let paginatorLifecycleService: jest.Mocked<HogInvocationResultsService>
    let paginatorMonitoringService: jest.Mocked<HogFunctionMonitoringService>
    let hogFunctionManager: HogFunctionManagerService
    let hogFlowManager: jest.Mocked<HogFlowManagerService>

    beforeAll(() => {
        clickhouse = Clickhouse.create()
        chClient = Clickhouse.createClient()
    })

    afterAll(async () => {
        clickhouse?.close()
        await chClient?.close()
    })

    let seededCount = 0
    /**
     * Seed `n` lifecycle rows for the given function. Each entry becomes a real
     * Kafka produce + MV ingestion, so by the time this returns ClickHouse has
     * the rows ready for the paginator to read.
     */
    const seedRows = async (
        rows: Array<{
            invocation_id: string
            status: 'running' | 'succeeded' | 'failed'
            error?: Error
            scheduledAt?: Date
        }>
    ): Promise<void> => {
        for (const r of rows) {
            const globals = createHogExecutionGlobals({
                project: { id: team.id } as any,
                event: {
                    uuid: `evt-${r.invocation_id}`,
                    event: '$pageview',
                    properties: {},
                    timestamp: '2026-05-10T09:00:00Z',
                } as any,
            })
            const invocation: CyclotronJobInvocationHogFunction = {
                id: r.invocation_id,
                state: {
                    globals: globals as any,
                    timings: [],
                    attempts: 0,
                },
                teamId: team.id,
                functionId: hogFunction.id,
                hogFunction,
                queue: 'hog',
                queuePriority: 0,
                queueScheduledAt: r.scheduledAt ? ({ toJSDate: () => r.scheduledAt } as any) : undefined,
            }
            seedingService.queueLifecycleRow(invocation, r.status, { error: r.error })
        }
        await seedingService.flush()

        // Track cumulative seeded rows so calling seedRows twice in the same
        // test waits for *all* rows (rather than trivially passing on the
        // previous seed's count).
        seededCount += rows.length
        const expected = seededCount

        await waitForExpect(async () => {
            const got = await clickhouse.query<{ c: number }>(
                `SELECT count() AS c FROM hog_invocation_results
                 WHERE team_id = ${team.id}
                   AND function_id = '${hogFunction.id}'`
            )
            expect(Number(got[0]?.c ?? 0)).toBeGreaterThanOrEqual(expected)
        }, 30_000)
    }

    beforeAll(async () => {
        MockKafkaProducerWrapper.create = jest.fn((...args: any[]) => ActualKafkaProducerWrapper.create(...args))
        await resetKafka()
        await ensureKafkaTopics([KAFKA_HOG_INVOCATION_RESULTS])
        await clickhouse.truncate('hog_invocation_results_data')
    })

    beforeEach(async () => {
        await resetTestDatabase()
        await clickhouse.truncate('hog_invocation_results_data')
        seededCount = 0

        hub = await createHub()
        kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        team = await getFirstTeam(hub.postgres)

        // Real seeding path: outputs → kafka → MV → CH.
        const deps = createCdpConsumerDeps(hub, kafkaProducer)
        const outputs = createCdpOutputsRegistry().build(deps.cdpProducerRegistry, {
            ...hub,
            HOG_INVOCATION_RESULTS_TOPIC: KAFKA_HOG_INVOCATION_RESULTS,
        } as any)
        seedingService = new HogInvocationResultsService(outputs, { HOG_INVOCATION_RESULTS_ENABLED: true })

        hogFunction = await _insertHogFunction(hub.postgres, team.id, {
            type: 'destination',
            hog: 'print("hi")',
            bytecode: [],
            inputs_schema: [],
            inputs: {},
        })

        // Real hog function manager so rehydrate can resolve the function from postgres.
        hogFunctionManager = new HogFunctionManagerService(hub.postgres, hub.pubSub, hub.encryptedFields)
        hogFunctionManager['onHogFunctionsReloaded'](team.id, [hogFunction.id])

        // Hog flow manager stays mocked — this suite focuses on the hog-function
        // path and the CH query/rehydrate logic. Hog flow rehydration is
        // exercised structurally (rest of the same code path) but not end-to-end here.
        hogFlowManager = {
            getHogFlow: jest.fn().mockResolvedValue(null),
        } as unknown as jest.Mocked<HogFlowManagerService>

        hogQueue = {
            queueInvocations: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<JobQueue>
        hogflowQueue = {
            queueInvocations: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<CyclotronJobQueuePostgresV2>

        // The paginator's lifecycle service is mocked so we can assert what it
        // got asked to write (the 'running' row for each rerun). The actual
        // CH state for that running row is a flaky-on-Redpanda concern handled
        // in the e2e test — here we only care that the paginator queues it.
        paginatorLifecycleService = {
            queueLifecycleRow: jest.fn(),
            queueRerunWrapperRow: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
            dropQueuedRowsFor: jest.fn(),
        } as unknown as jest.Mocked<HogInvocationResultsService>

        paginatorMonitoringService = {
            queueLogs: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<HogFunctionMonitoringService>

        paginator = new RerunPaginatorService(
            chClient,
            hogFunctionManager,
            hogFlowManager,
            paginatorLifecycleService,
            { hog_function: hogQueue, hog_flow: hogflowQueue },
            paginatorMonitoringService,
            10000
        )
    })

    afterEach(async () => {
        await kafkaProducer?.disconnect().catch(() => undefined)
        await closeHub(hub)
    })

    const buildState = (overrides: Partial<RerunJobState> = {}): RerunJobState => ({
        function_kind: 'hog_function',
        function_id: hogFunction.id,
        // Window is required by the unified rerun schema. Default to a wide
        // year-long window so the seeded test data falls inside.
        request: { filter: { window_start: '2026-01-01T00:00:00Z', window_end: '2027-01-01T00:00:00Z' } },
        progress: { queued: 0, skipped: 0, done: false },
        ...overrides,
    })

    describe('by-ids mode', () => {
        it('rehydrates and re-enqueues only the requested invocations, ignoring others', async () => {
            await seedRows([
                { invocation_id: 'inv-a', status: 'failed', error: new Error('http_5xx error') },
                { invocation_id: 'inv-b', status: 'succeeded' },
                { invocation_id: 'inv-c', status: 'failed', error: new Error('timeout') },
            ])

            const state = buildState({
                request: {
                    filter: {
                        window_start: '2026-01-01T00:00:00Z',
                        window_end: '2027-01-01T00:00:00Z',
                        invocation_ids: ['inv-a', 'inv-c'],
                    },
                },
            })

            const { state: next } = await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })

            expect(hogQueue.queueInvocations).toHaveBeenCalledTimes(1)
            const enqueued = hogQueue.queueInvocations.mock.calls[0][0] as CyclotronJobInvocationHogFunction[]
            const enqueuedIds = enqueued.map((i) => i.id).sort()
            expect(enqueuedIds).toEqual(['inv-a', 'inv-c'])

            // Each rerun invocation gets a 'running' lifecycle row queued.
            // is_retry / attempts are derived inside queueLifecycleRow from
            // state.rerunAttempts (set by the rehydrator), not passed as an opt.
            const runningCalls = paginatorLifecycleService.queueLifecycleRow.mock.calls.filter(
                (c) => c[1] === 'running'
            )
            expect(runningCalls).toHaveLength(2)
            // Each queued invocation's state should carry rerunAttempts=1.
            for (const [invocation] of runningCalls) {
                expect((invocation as CyclotronJobInvocationHogFunction).state.rerunAttempts).toBe(1)
            }

            expect(next.progress.queued).toBe(2)
            expect(next.progress.skipped).toBe(0)
            expect(next.progress.done).toBe(true)
        })

        it('skips invocation ids that have no matching row in clickhouse', async () => {
            await seedRows([{ invocation_id: 'inv-real', status: 'failed', error: new Error('5xx') }])

            const state = buildState({
                request: {
                    filter: {
                        window_start: '2026-01-01T00:00:00Z',
                        window_end: '2027-01-01T00:00:00Z',
                        invocation_ids: ['inv-real', 'inv-missing'],
                    },
                },
            })

            const { state: next } = await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })

            const enqueued = hogQueue.queueInvocations.mock.calls[0][0] as CyclotronJobInvocationHogFunction[]
            expect(enqueued.map((i) => i.id)).toEqual(['inv-real'])
            // by-ids mode marks done once remaining_ids is drained, regardless of
            // whether every id had a matching CH row.
            expect(next.progress.done).toBe(true)
        })

        it('re-enqueues bare globals — inputs are not stored or pre-resolved by the paginator', async () => {
            await seedRows([{ invocation_id: 'inv-rebuild', status: 'failed', error: new Error('boom') }])

            const state = buildState({
                request: {
                    filter: {
                        window_start: '2026-01-01T00:00:00Z',
                        window_end: '2027-01-01T00:00:00Z',
                        invocation_ids: ['inv-rebuild'],
                    },
                },
            })

            await paginator.processPage(team.id, state, { jobId: 'test-rerun-job', createdAt: DateTime.now() })

            // The re-enqueued invocation carries no resolved `inputs` — the
            // executor rebuilds them from the current hog function config at
            // run time, so the rerun never trusts a stored snapshot.
            const enqueued = hogQueue.queueInvocations.mock.calls[0][0] as CyclotronJobInvocationHogFunction[]
            expect(enqueued).toHaveLength(1)
            expect(enqueued[0].state.globals).not.toHaveProperty('inputs')
        })
    })

    describe('by-filter mode', () => {
        it('defaults to status=failed and only matches failed rows in the window', async () => {
            await seedRows([
                { invocation_id: 'ok-1', status: 'succeeded' },
                { invocation_id: 'fail-1', status: 'failed', error: new Error('500 err') },
                { invocation_id: 'fail-2', status: 'failed', error: new Error('timeout') },
            ])

            const state = buildState({
                request: {
                    filter: { window_start: '2026-01-01T00:00:00Z', window_end: '2027-01-01T00:00:00Z' },
                },
            })

            const { state: next } = await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })

            const enqueued = hogQueue.queueInvocations.mock.calls[0][0] as CyclotronJobInvocationHogFunction[]
            const ids = enqueued.map((i) => i.id).sort()
            expect(ids).toEqual(['fail-1', 'fail-2'])
            expect(next.progress.queued).toBe(2)
        })

        it('honours error_kind filter (only http_5xx rows are rerun)', async () => {
            await seedRows([
                { invocation_id: 'inv-500', status: 'failed', error: new Error('500 server error') },
                { invocation_id: 'inv-timeout', status: 'failed', error: new Error('Request timed out') },
            ])

            const state = buildState({
                request: {
                    filter: {
                        window_start: '2026-01-01T00:00:00Z',
                        window_end: '2027-01-01T00:00:00Z',
                        error_kind: ['http_5xx'],
                    },
                },
            })

            const { state: next } = await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })
            const enqueued = hogQueue.queueInvocations.mock.calls[0]?.[0] as
                | CyclotronJobInvocationHogFunction[]
                | undefined
            expect(enqueued?.map((i) => i.id)).toEqual(['inv-500'])
            expect(next.progress.queued).toBe(1)
        })

        it('honours max_count by capping queued+skipped at the user-provided limit', async () => {
            await seedRows([
                { invocation_id: 'a', status: 'failed', error: new Error('5xx') },
                { invocation_id: 'b', status: 'failed', error: new Error('5xx') },
                { invocation_id: 'c', status: 'failed', error: new Error('5xx') },
            ])

            const state = buildState({
                request: {
                    filter: {
                        window_start: '2026-01-01T00:00:00Z',
                        window_end: '2027-01-01T00:00:00Z',
                        max_count: 2,
                    },
                },
            })

            const { state: next } = await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })
            expect(next.progress.queued).toBe(2)
            expect(next.progress.done).toBe(true)
        })

        it('returns done=true with an empty page when no rows match the filter', async () => {
            await seedRows([{ invocation_id: 'inv-ok', status: 'succeeded' }])

            const state = buildState({
                request: {
                    filter: { window_start: '2026-01-01T00:00:00Z', window_end: '2027-01-01T00:00:00Z' },
                },
            })

            const { state: next } = await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })
            expect(next.progress.queued).toBe(0)
            expect(next.progress.done).toBe(true)
            expect(hogQueue.queueInvocations).not.toHaveBeenCalled()
        })
    })

    describe('rehydration', () => {
        it('skips rows whose hog function has been deleted between original run and rerun', async () => {
            const orphanedFn = await _insertHogFunction(hub.postgres, team.id, {
                type: 'destination',
                hog: 'print("orphan")',
                bytecode: [],
            })
            // Seed under the orphaned function...
            const prevFn = hogFunction
            hogFunction = orphanedFn
            await seedRows([{ invocation_id: 'inv-orphan', status: 'failed', error: new Error('5xx') }])
            hogFunction = prevFn

            // ...then ask the paginator to rerun it. The paginator's hog function
            // manager (real) lazy-loads the orphaned function (still exists in PG)
            // — we explicitly stub `getHogFunction` to return null to simulate the
            // "deleted between original run and rerun" scenario.
            const realGetHogFunction = hogFunctionManager.getHogFunction.bind(hogFunctionManager)
            jest.spyOn(hogFunctionManager, 'getHogFunction').mockImplementation(async (id) => {
                if (id === orphanedFn.id) {
                    return null
                }
                return realGetHogFunction(id)
            })

            const state: RerunJobState = {
                function_kind: 'hog_function',
                function_id: orphanedFn.id,
                request: {
                    filter: {
                        window_start: '2026-01-01T00:00:00Z',
                        window_end: '2027-01-01T00:00:00Z',
                        invocation_ids: ['inv-orphan'],
                    },
                },
                progress: { queued: 0, skipped: 0, done: false },
            }

            const { state: next } = await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })
            expect(next.progress.queued).toBe(0)
            expect(next.progress.skipped).toBe(1)
            expect(hogQueue.queueInvocations).not.toHaveBeenCalled()
        })
    })

    describe('error handling', () => {
        it('captures a ClickHouse query error on progress.last_error without marking done', async () => {
            // Point the paginator at a deliberately broken ClickHouse client to
            // exercise the catch path.
            const brokenChClient = {
                query: jest.fn().mockRejectedValue(new Error('clickhouse boom')),
            } as unknown as ClickHouseClient
            const brokenPaginator = new RerunPaginatorService(
                brokenChClient,
                hogFunctionManager,
                hogFlowManager,
                paginatorLifecycleService,
                { hog_function: hogQueue, hog_flow: hogflowQueue },
                paginatorMonitoringService,
                10000
            )

            const state = buildState({
                request: {
                    filter: {
                        window_start: '2026-01-01T00:00:00Z',
                        window_end: '2027-01-01T00:00:00Z',
                        invocation_ids: ['x'],
                    },
                },
                progress: { queued: 0, skipped: 0, done: false },
            })

            const { state: next } = await brokenPaginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })
            expect(next.progress.done).toBe(false)
            expect(next.progress.last_error).toContain('clickhouse boom')
            expect(hogQueue.queueInvocations).not.toHaveBeenCalled()
        })
    })

    describe('done logic (real CH)', () => {
        it('marks done when fewer rows came back than the page size (no further pages)', async () => {
            await seedRows([{ invocation_id: 'one', status: 'failed', error: new Error('5xx') }])

            const state = buildState({
                request: {
                    filter: { window_start: '2026-01-01T00:00:00Z', window_end: '2027-01-01T00:00:00Z' },
                },
            })

            const { state: next } = await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })
            // 1 row < RERUN_PAGE_SIZE → done.
            expect(next.progress.done).toBe(true)
            // Sanity: RERUN_PAGE_SIZE constant didn't regress to a tiny value.
            expect(RERUN_PAGE_SIZE).toBeGreaterThan(10)
        })

        it('carries first_scheduled_at from the stored row onto the rehydrated invocation state', async () => {
            // The producer writes `first_scheduled_at` verbatim on every retry's
            // lifecycle row so ReplacingMergeTree doesn't collapse it away. The
            // paginator's contract here: read it from the stored row, stamp it
            // onto the rehydrated state so the next retry's producer sees the
            // same original time. Without this, every kafka retry would
            // overwrite first_scheduled_at with the latest scheduled_at.
            const id = 'inv-first-' + new UUIDT().toString()
            const originalScheduledAt = new Date('2026-05-01T09:00:00Z')
            await seedRows([
                {
                    invocation_id: id,
                    status: 'failed',
                    error: new Error('5xx'),
                    scheduledAt: originalScheduledAt,
                },
            ])

            const state = buildState({
                request: {
                    filter: {
                        window_start: '2026-01-01T00:00:00Z',
                        window_end: '2027-01-01T00:00:00Z',
                        invocation_ids: [id],
                    },
                },
            })

            await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })

            const enqueued = hogQueue.queueInvocations.mock.calls[0][0] as CyclotronJobInvocationHogFunction[]
            expect(enqueued).toHaveLength(1)
            // CH returns DateTime64 as 'YYYY-MM-DD HH:MM:SS.ffffff' — just check
            // the date portion matches the original scheduled time. The exact
            // serialization differs between paths but the day/time is preserved.
            expect(enqueued[0].state.firstScheduledAt).toMatch(/^2026-05-01[T ]09:00:00/)
        })

        it('reads the latest row per invocation via argMax(_, version) collapse', async () => {
            // Same invocation_id, multiple lifecycle rows simulating: original
            // failed → user clicked rerun → rerun running → rerun succeeded.
            // The paginator should see the LATEST `succeeded` state, not the
            // earlier `failed`. (Filter mode defaults to status=failed, so an
            // invocation that's now succeeded should NOT be picked up.)
            const id = 'inv-collapse-' + new UUIDT().toString()
            await seedRows([{ invocation_id: id, status: 'failed', error: new Error('5xx') }])
            // Small sleep to ensure version monotonicity is observable.
            await new Promise((r) => setTimeout(r, 5))
            await seedRows([{ invocation_id: id, status: 'succeeded' }])

            const state = buildState({
                request: {
                    filter: { window_start: '2026-01-01T00:00:00Z', window_end: '2027-01-01T00:00:00Z' },
                },
            })

            const { state: next } = await paginator.processPage(team.id, state, {
                jobId: 'test-rerun-job',
                createdAt: DateTime.now(),
            })
            expect(next.progress.queued).toBe(0)
        })
    })

    // Silence unused-import noise for HogFunctionInvocationGlobals which is
    // referenced indirectly via the rehydration assertion.
    void (undefined as unknown as HogFunctionInvocationGlobals)
})
