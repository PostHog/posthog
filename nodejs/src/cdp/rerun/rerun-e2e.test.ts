import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { DateTime } from 'luxon'
import { Pool } from 'pg'

import { KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { insertHogFunction as _insertHogFunction, createHogExecutionGlobals } from '../_tests/fixtures'
import { CdpConsumerBaseDeps } from '../consumers/cdp-base.consumer'
import { CdpCyclotronWorker } from '../consumers/cdp-cyclotron-worker.consumer'
import { CdpEventsConsumer } from '../consumers/cdp-events.consumer'
import { CdpRerunWorkerConsumer } from '../consumers/cdp-rerun-worker.consumer'
import { CyclotronJobQueueKafka } from '../services/job-queue/job-queue-kafka'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { compileHog } from '../templates/compiler'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { RerunJobManager } from './rerun-job.manager'
import { RERUN_QUEUE_NAME } from './rerun-job.types'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

const NODE_DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

interface PersistedRow {
    invocation_id: string
    status: string
    is_retry: number
    attempts: number
    error_kind: string
    function_kind: string
    invocation_globals: string
}

/**
 * Probe the ClickHouse Kafka MV for our topic in particular. With
 * auto.offset.reset=latest, anything produced before the MV's internal consumer
 * has attached is silently dropped. Send probe rows until one lands in CH so we
 * know the MV is live before the test produces real rows.
 */
const waitForHogInvocationResultsMvReady = async (clickhouse: Clickhouse): Promise<void> => {
    const producer = await ActualKafkaProducerWrapper.create(undefined)
    const probeTeamId = -999_999
    try {
        await waitForExpect(async () => {
            await producer.queueMessages({
                topic: KAFKA_HOG_INVOCATION_RESULTS,
                messages: [
                    {
                        key: 'probe',
                        value: JSON.stringify({
                            team_id: probeTeamId,
                            function_kind: 'hog_function',
                            function_id: 'probe',
                            invocation_id: 'probe',
                            parent_run_id: '',
                            status: 'running',
                            attempts: 0,
                            is_retry: 0,
                            scheduled_at: DateTime.utc().toFormat("yyyy-MM-dd HH:mm:ss.SSS'000'"),
                            started_at: null,
                            finished_at: null,
                            duration_ms: null,
                            error_kind: '',
                            error_message: '',
                            event_uuid: '',
                            distinct_id: '',
                            person_id: '',
                            invocation_globals: '{}',
                            version: String(BigInt(Date.now()) * 1000n),
                            is_deleted: 0,
                        }),
                    },
                ],
            })
            await producer.flush()

            const result = await clickhouse.query<{ c: number }>(
                `SELECT count() AS c FROM hog_invocation_results WHERE team_id = ${probeTeamId}`
            )
            expect(Number(result[0]?.c ?? 0)).toBeGreaterThan(0)
        }, 30_000)
    } finally {
        await producer.disconnect()
    }
}

/**
 * End-to-end exercise of the runs/rerun pipeline.
 *
 * Everything is real: real Kafka, real ClickHouse Kafka MV, real cyclotron-v2
 * postgres, real cyclotron worker, real rerun wrapper-job loop. The ONLY thing
 * mocked is the inbound Django request — we call `RerunJobManager.enqueue(...)`
 * directly with the same payload the Django view would proxy through.
 *
 * Flow under test:
 *   1. Hog function runs -> producer writes a 'succeeded' lifecycle row to
 *      Kafka -> MV lands it in `hog_invocation_results`.
 *   2. Simulated Django POST: `rerunManager.enqueue({ invocation_ids })`.
 *   3. Real `CdpRerunWorkerConsumer` dequeues the wrapper job, queries the
 *      real `hog_invocation_results`, rehydrates globals (rebuilding inputs),
 *      and re-enqueues onto the regular cyclotron queue.
 *   4. The real cyclotron worker picks up the rerun invocation and writes a
 *      second lifecycle row, this time with `is_retry=1` and `attempts > 1`.
 */
describe('CDP hog invocation rerun e2e', () => {
    jest.setTimeout(60_000)

    let hub: Hub
    let kafkaProducer: KafkaProducerWrapper
    let team: Team
    let fnFetch: HogFunctionType
    let globals: HogFunctionInvocationGlobals
    let mockProducerObserver: KafkaProducerObserver
    let eventsConsumer: CdpEventsConsumer
    let cyclotronWorker: CdpCyclotronWorker
    let rerunManager: RerunJobManager
    let rerunWorker: CdpRerunWorkerConsumer
    let kafkaQueue: CyclotronJobQueueKafka
    let postgresV2Queue: CyclotronJobQueuePostgresV2
    let nodeAssertPool: Pool
    let clickhouse: Clickhouse
    let cdpDeps: CdpConsumerBaseDeps

    beforeAll(() => {
        clickhouse = Clickhouse.create()
    })

    afterAll(() => {
        clickhouse?.close()
        jest.useRealTimers()
    })

    beforeEach(async () => {
        // Use a real KafkaProducerWrapper per the cdp-e2e pattern — gives us a
        // real producer to observe via KafkaProducerObserver.
        MockKafkaProducerWrapper.create = jest.fn((...args: any[]) => ActualKafkaProducerWrapper.create(...args))

        // Ensure all topics exist (idempotently, without deleting) so the ClickHouse
        // Kafka engine consumers keep their connections. Includes KAFKA_HOG_INVOCATION_RESULTS,
        // which this test's MV needs but the shared set does not cover.
        await ensureKafkaTopics([...TEST_KAFKA_TOPICS, KAFKA_HOG_INVOCATION_RESULTS])
        await clickhouse.truncate('hog_invocation_results_data')
        await waitForHogInvocationResultsMvReady(clickhouse)
        await resetTestDatabase()
        await clickhouse.truncate('hog_invocation_results_data')

        hub = await createHub()
        kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        mockProducerObserver = new KafkaProducerObserver(kafkaProducer)

        team = await getFirstTeam(hub.postgres)

        // The rerun strips `person` from invocation_globals — the cyclotron
        // worker reloads it via getCyclotronPerson(distinct_id). Provide a mock
        // person so the rerun can resolve `{person}` in the function's inputs.
        const mockPersonRepo: jest.Mocked<PersonReadRepository> = {
            fetchPerson: jest.fn().mockResolvedValue(undefined),
            fetchPersonsByDistinctIds: jest.fn().mockResolvedValue([
                {
                    id: '1',
                    uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1',
                    team_id: team.id,
                    properties: { email: 'rerun-e2e@posthog.com' },
                    properties_last_updated_at: {},
                    properties_last_operation: null,
                    created_at: DateTime.utc(),
                    version: 1,
                    is_identified: true,
                    is_user_id: null,
                    last_seen_at: null,
                    distinct_id: 'distinct_id',
                },
            ]),
            fetchPersonsByPersonIds: jest.fn().mockResolvedValue([]),
            fetchDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
        }

        mockProducerObserver.resetKafkaProducer()

        hub.CDP_FETCH_RETRIES = 0
        hub.CDP_FETCH_BACKOFF_BASE_MS = 1
        hub.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA = true
        hub.CYCLOTRON_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron'
        hub.CYCLOTRON_NODE_DATABASE_URL = NODE_DB_URL
        hub.HOG_INVOCATION_RESULTS_ENABLED = true

        // Clean any stale rerun wrapper jobs from prior runs.
        nodeAssertPool = new Pool({ connectionString: NODE_DB_URL })
        await nodeAssertPool.query('DELETE FROM cyclotron_jobs WHERE queue_name = $1', [RERUN_QUEUE_NAME])

        const hog = `
        let res := fetch(inputs.url, {
            'headers': { 'Content-Type': 'application/json' },
            'body': inputs.body,
            'method': inputs.method
        });
        print('Fetch response:', res);
        `

        fnFetch = await _insertHogFunction(hub.postgres, team.id, {
            type: 'destination',
            hog,
            bytecode: await compileHog(hog),
            inputs_schema: HOG_INPUTS_EXAMPLES.simple_fetch.inputs_schema ?? [],
            inputs: HOG_INPUTS_EXAMPLES.simple_fetch.inputs,
            ...HOG_FILTERS_EXAMPLES.no_filters,
        })

        kafkaQueue = new CyclotronJobQueueKafka(hub.KAFKA_CLIENT_RACK, hub, hub.CONSUMER_BATCH_SIZE)
        postgresV2Queue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)

        cdpDeps = { ...createCdpConsumerDeps(hub, kafkaProducer), personRepository: mockPersonRepo }

        eventsConsumer = new CdpEventsConsumer(hub, cdpDeps, {
            hogQueue: kafkaQueue,
            hogflowQueue: postgresV2Queue,
        })
        // We call processBatch directly — no need to actually join the kafka group.
        // Stubbing keeps the test off Redpanda's stale-group-protocol coordinator,
        // which otherwise fails the join with "Inconsistent group protocol".
        eventsConsumer['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn(),
        } as any
        await eventsConsumer.start()

        cyclotronWorker = new CdpCyclotronWorker(hub, cdpDeps, kafkaQueue)
        await cyclotronWorker.start()

        rerunManager = new RerunJobManager({ dbUrl: NODE_DB_URL, maxCount: 10000 })
        await rerunManager.connect()

        globals = createHogExecutionGlobals({
            project: { id: team.id } as any,
            event: {
                uuid: '0d0ff14e-1b15-4afe-99e3-1ea83f0e3aab',
                event: '$pageview',
                properties: { $current_url: 'https://posthog.com' },
                timestamp: '2026-05-10T09:00:00Z',
            } as any,
        })
    })

    afterEach(async () => {
        await Promise.all([
            eventsConsumer?.stop().catch(() => undefined),
            cyclotronWorker?.stop().catch(() => undefined),
            rerunWorker?.stop().catch(() => undefined),
            rerunManager?.disconnect().catch(() => undefined),
        ])
        await kafkaProducer?.disconnect()
        await closeHub(hub)
        await nodeAssertPool.end()
        mockProducerObserver?.resetKafkaProducer()
    })

    it('produces a succeeded lifecycle row, then reruns the invocation via the wrapper-job pipeline', async () => {
        // ── 1. Original invocation succeeds ─────────────────────────────────
        mockFetch.mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({ ok: true }),
            text: () => Promise.resolve('{"ok":true}'),
            headers: { 'Content-Type': 'application/json' },
            dump: () => Promise.resolve(),
        })

        const { invocations } = await eventsConsumer.processBatch([globals])
        expect(invocations).toHaveLength(1)

        // Wait for the terminal 'succeeded' row to flow Kafka -> MV -> ClickHouse.
        await waitForExpect(async () => {
            const rows = await clickhouse.query<PersistedRow>(
                `SELECT invocation_id, status, is_retry, attempts, error_kind, function_kind
                 FROM hog_invocation_results
                 WHERE team_id = ${team.id} AND function_id = '${fnFetch.id}' AND status = 'succeeded'`
            )
            expect(rows.length).toBeGreaterThanOrEqual(1)
        }, 30_000)

        const originalRows = await clickhouse.query<PersistedRow>(
            `SELECT invocation_id, status, is_retry, attempts, error_kind, function_kind, invocation_globals
             FROM hog_invocation_results
             WHERE team_id = ${team.id} AND function_id = '${fnFetch.id}' AND status = 'succeeded'`
        )
        const originalInvocationId = originalRows[0].invocation_id
        expect(originalRows[0].is_retry).toBe(0)
        expect(originalRows[0].function_kind).toBe('hog_function')
        // invocation_globals is stored gzip+base64'd, not raw JSON — base64
        // never starts with `{`. The rerun below proves the round-trip: it can
        // only rehydrate and re-run if `decodeInvocationGlobals` decompresses
        // this value correctly.
        expect(originalRows[0].invocation_globals.length).toBeGreaterThan(0)
        expect(originalRows[0].invocation_globals.startsWith('{')).toBe(false)
        // The prior cyclotron_jobs row is in a terminal 'completed' state by
        // this point. The rerun path's `overwriteExisting: true` upsert
        // (cyclotron-v2 ON CONFLICT) handles the PK collision without us
        // having to manually delete the row.

        // ── 2. Mimic Django POST /rerun — only the request itself is faked ──────
        // The rerun request requires a time window; we use a wide one around
        // "now" (the lifecycle row's scheduled_at = current time) and restrict
        // to a specific invocation_id via the optional filter field.
        const windowStart = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
        const windowEnd = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()
        const rerunJobId = await rerunManager.enqueue(team.id, 'hog_function', fnFetch.id, {
            filter: {
                window_start: windowStart,
                window_end: windowEnd,
                status: ['succeeded'],
                invocation_ids: [originalInvocationId],
            },
        })

        // Wrapper job is real and durable in test_cyclotron_node postgres.
        const wrapperRow = await nodeAssertPool.query(
            'SELECT id, queue_name, status FROM cyclotron_jobs WHERE id = $1',
            [rerunJobId]
        )
        expect(wrapperRow.rows[0]).toMatchObject({
            id: rerunJobId,
            queue_name: RERUN_QUEUE_NAME,
            status: 'available',
        })

        // ── 3. Rerun worker drains the wrapper job ────────────────────────────────
        rerunWorker = new CdpRerunWorkerConsumer(
            { ...hub, CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: 'postgres' },
            cdpDeps,
            { hog_function: kafkaQueue, hog_flow: postgresV2Queue }
        )
        await rerunWorker.start()

        // ── 4. Wait for the wrapper job to complete ────────────────────────────────
        await waitForExpect(async () => {
            const res = await nodeAssertPool.query('SELECT status FROM cyclotron_jobs WHERE id = $1', [rerunJobId])
            // 'completed' = the paginator marked done=true and the worker acked.
            expect(res.rows[0]?.status).toBe('completed')
        }, 30_000)

        // ── 5. Reruned invocation flows through the real cyclotron worker ─────────
        // The paginator emits a 'running' row at re-enqueue time and the worker
        // emits the terminal row when the rerun invocation completes. Both
        // rows now correctly carry `is_retry=1` / `attempts=1` because the
        // paginator sets `state.rerunAttempts=1` on the rehydrated invocation
        // and `queueLifecycleRow` derives those columns from that field.
        await waitForExpect(async () => {
            const rows = await clickhouse.query<PersistedRow>(
                `SELECT invocation_id, status, is_retry, attempts, error_kind, function_kind
                 FROM hog_invocation_results
                 WHERE team_id = ${team.id}
                   AND function_id = '${fnFetch.id}'
                   AND invocation_id = '${originalInvocationId}'
                   AND is_retry = 1`
            )
            // Either the paginator's running row, the worker's terminal row,
            // or both should be present and tagged is_retry=1.
            expect(rows.length).toBeGreaterThanOrEqual(1)
            for (const row of rows) {
                expect(row.attempts).toBe(1)
            }
        }, 30_000)

        // ── 6. The hog function's fetch was called twice — once original, once rerun ─
        expect(mockFetch.mock.calls.length).toBeGreaterThanOrEqual(2)
    })

    // Reproduces the class of bug observed on Google Ads reruns during the
    // 2026-07-02 DEVELOPER_TOKEN_INVALID incident: the template's input
    // resolves to `{person.properties.gclid}`; on rerun the paginator strips
    // `person` from `invocation_globals` and the cyclotron worker rehydrates
    // it from Postgres via `getCyclotronPerson(distinct_id)`. So the rerun
    // runs against *current* person state, not the state at the time of the
    // original send. If the customer's person no longer has `gclid` (drift
    // between send-time and rerun-time), the rerun hits the template's
    // `if (empty(inputs.gclid)) skip` guard and the send never fires — even
    // though the original invocation legitimately had a gclid.
    //
    // Both tests here run the same paginator → worker → executor loop; the
    // difference is what the mock personRepo returns on the rerun-time lookup.
    describe('when the input resolves via person.properties', () => {
        const buildGclidFn = async (): Promise<HogFunctionType> => {
            // Mirrors the shape of the Google Ads template: skip if gclid is
            // empty, otherwise fetch. Simpler than the real template so the
            // test surface stays small.
            const hog = `
            if (empty(inputs.gclid)) {
                print('Empty gclid. Skipping...')
                return
            }
            let res := fetch(inputs.url, { 'method': 'POST', 'body': f'gclid={inputs.gclid}' });
            print('Fetch response:', res);
            `
            return await _insertHogFunction(hub.postgres, team.id, {
                type: 'destination',
                hog,
                bytecode: await compileHog(hog),
                inputs_schema: [
                    { key: 'url', type: 'string', label: 'URL', secret: false, required: true },
                    { key: 'gclid', type: 'string', label: 'gclid', secret: false, required: false },
                ],
                inputs: {
                    url: {
                        value: 'https://example.com/google-ads-webhook',
                        bytecode: ['_h', 32, 'https://example.com/google-ads-webhook'],
                    },
                    // Exact expression from `google.template.ts:24` so the
                    // reproduction also verifies hog can access `$initial_gclid`
                    // via dot notation (the `$` prefix is a common gotcha
                    // point).
                    gclid: {
                        value: '{person.properties.gclid ?? person.properties.$initial_gclid}',
                        bytecode: await compileHog(
                            'return person.properties.gclid ?? person.properties.$initial_gclid'
                        ),
                    },
                },
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })
        }

        // The parent beforeEach inserts a `simple_fetch` destination (`fnFetch`)
        // that also has `no_filters` and gets triggered by our `$pageview`. We
        // don't care about its invocations or fetches — filter them out.
        const GCLID_WEBHOOK_URL = 'https://example.com/google-ads-webhook'
        const gclidFetchCalls = (): unknown[][] =>
            mockFetch.mock.calls.filter(([url]) => String(url).startsWith(GCLID_WEBHOOK_URL))

        const runOriginalAndAssertLifecycleRow = async (gclidFn: HogFunctionType): Promise<string> => {
            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ ok: true }),
                text: () => Promise.resolve('{"ok":true}'),
                headers: { 'Content-Type': 'application/json' },
                dump: () => Promise.resolve(),
            })

            // Original invocation carries `gclid: 'ABC123'` on globals.person
            // so the template's empty-check passes and the fetch fires.
            const gclidGlobals = createHogExecutionGlobals({
                project: { id: team.id } as any,
                event: {
                    uuid: '11111111-1111-1111-1111-111111111111',
                    event: '$pageview',
                    distinct_id: 'distinct_id',
                    properties: { $current_url: 'https://posthog.com?gclid=ABC123' },
                    timestamp: '2026-07-02T09:00:00Z',
                } as any,
                person: {
                    id: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1',
                    name: 'test',
                    url: 'http://localhost:8000/persons/1',
                    properties: { email: 'rerun-e2e@posthog.com', gclid: 'ABC123' },
                },
            })

            const { invocations } = await eventsConsumer.processBatch([gclidGlobals])
            // At least one for our gclidFn — the parent beforeEach's fnFetch
            // also matches this event, so we don't pin an exact count.
            const gclidInvocations = invocations.filter((inv) => inv.functionId === gclidFn.id)
            expect(gclidInvocations).toHaveLength(1)

            await waitForExpect(async () => {
                const rows = await clickhouse.query<PersistedRow>(
                    `SELECT invocation_id, status, is_retry, attempts, error_kind, function_kind
                     FROM hog_invocation_results
                     WHERE team_id = ${team.id} AND function_id = '${gclidFn.id}' AND status = 'succeeded'`
                )
                expect(rows.length).toBeGreaterThanOrEqual(1)
            }, 30_000)

            const rows = await clickhouse.query<PersistedRow>(
                `SELECT invocation_id, status, is_retry, attempts, error_kind, function_kind, invocation_globals
                 FROM hog_invocation_results
                 WHERE team_id = ${team.id} AND function_id = '${gclidFn.id}' AND status = 'succeeded'`
            )
            expect(gclidFetchCalls()).toHaveLength(1)
            return rows[0].invocation_id
        }

        const triggerRerunAndWaitForCompletion = async (
            gclidFn: HogFunctionType,
            originalInvocationId: string
        ): Promise<void> => {
            const windowStart = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
            const windowEnd = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()
            const rerunJobId = await rerunManager.enqueue(team.id, 'hog_function', gclidFn.id, {
                filter: {
                    window_start: windowStart,
                    window_end: windowEnd,
                    status: ['succeeded'],
                    invocation_ids: [originalInvocationId],
                },
            })

            rerunWorker = new CdpRerunWorkerConsumer(
                { ...hub, CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: 'postgres' },
                cdpDeps,
                { hog_function: kafkaQueue, hog_flow: postgresV2Queue }
            )
            await rerunWorker.start()

            await waitForExpect(async () => {
                const res = await nodeAssertPool.query('SELECT status FROM cyclotron_jobs WHERE id = $1', [rerunJobId])
                expect(res.rows[0]?.status).toBe('completed')
            }, 30_000)
        }

        it('reruns via the `$initial_gclid` fallback when the person has it set', async () => {
            // Matches the production scenario the customer's persons actually
            // have: bare `gclid` isn't on the person (it lives on the event),
            // but `$initial_gclid` is set via $set_once from first touch. The
            // template's coalesce should fall through to `$initial_gclid` and
            // the rerun should fetch with that value.
            //
            // If this test FAILS (fetch fires only once), hog can't access
            // `$initial_gclid` via dot notation on the input expression, and
            // the production bug is a compiler / input-eval issue, not a
            // person-lookup issue.
            const gclidFn = await buildGclidFn()
            const originalInvocationId = await runOriginalAndAssertLifecycleRow(gclidFn)

            const personRepo = cdpDeps.personRepository as jest.Mocked<PersonReadRepository>
            personRepo.fetchPersonsByDistinctIds.mockReset()
            personRepo.fetchPersonsByDistinctIds.mockResolvedValue([
                {
                    id: '1',
                    uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1',
                    team_id: team.id,
                    properties: {
                        email: 'rerun-e2e@posthog.com',
                        // No bare `gclid` here — matches production person
                        // state where SDK autocapture only writes
                        // `$initial_gclid` via $set_once on first touch.
                        $initial_gclid: 'INITIAL_TOKEN_ABC',
                    },
                    properties_last_updated_at: {},
                    properties_last_operation: null,
                    created_at: DateTime.utc(),
                    version: 1,
                    is_identified: true,
                    is_user_id: null,
                    last_seen_at: null,
                    distinct_id: 'distinct_id',
                },
            ])

            await triggerRerunAndWaitForCompletion(gclidFn, originalInvocationId)

            // Diagnostic: was the rehydration path taken at all? If the mock
            // was never called, `getCyclotronPerson` bypassed the loader
            // (cached from earlier, or a different code path). If it WAS
            // called but properties came back wrong, we'll see the actual
            // Record it returned.
            expect(personRepo.fetchPersonsByDistinctIds.mock.calls.length).toBeGreaterThanOrEqual(1)
            const lastResult = await personRepo.fetchPersonsByDistinctIds.mock.results.at(-1)?.value
            expect(lastResult?.[0]?.properties).toEqual(
                expect.objectContaining({ $initial_gclid: 'INITIAL_TOKEN_ABC' })
            )

            // Original + rerun both fetched to our webhook URL. The second
            // one's body should carry the value from `$initial_gclid` —
            // proves the coalesce reached the fallback branch.
            const calls = gclidFetchCalls()
            expect(calls.length).toBeGreaterThanOrEqual(2)
            const rerunBody = String((calls[calls.length - 1] as any)[1]?.body ?? '')
            expect(rerunBody).toContain('gclid=INITIAL_TOKEN_ABC')
        })

        it('skips the rerun when Postgres person no longer has the field', async () => {
            // Drift path: the Postgres person no longer has `gclid`, so the
            // worker's rehydration returns `properties` without it. The
            // template's `if (empty(inputs.gclid))` guard fires and the fetch
            // is never called on the rerun — matching the production symptom.
            const gclidFn = await buildGclidFn()
            const originalInvocationId = await runOriginalAndAssertLifecycleRow(gclidFn)

            const personRepo = cdpDeps.personRepository as jest.Mocked<PersonReadRepository>
            personRepo.fetchPersonsByDistinctIds.mockResolvedValue([
                {
                    id: '1',
                    uuid: 'dd3d6f80-60ad-45c3-bd61-e2300f2ba7e1',
                    team_id: team.id,
                    // No `gclid` here — simulates the value being missing on
                    // the current Postgres person (drift, merge, whatever
                    // path we're actually hitting in production).
                    properties: { email: 'rerun-e2e@posthog.com' },
                    properties_last_updated_at: {},
                    properties_last_operation: null,
                    created_at: DateTime.utc(),
                    version: 1,
                    is_identified: true,
                    is_user_id: null,
                    last_seen_at: null,
                    distinct_id: 'distinct_id',
                },
            ])

            await triggerRerunAndWaitForCompletion(gclidFn, originalInvocationId)

            // Only the original fetch to our webhook — rerun hit the
            // empty-gclid skip and never fetched.
            expect(gclidFetchCalls()).toHaveLength(1)
        })
    })
})
