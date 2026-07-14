import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'

import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'

import { DateTime } from 'luxon'
import { Pool } from 'pg'

import { KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_FILTERS_EXAMPLES } from '../_tests/examples'
import { insertHogFlow } from '../_tests/fixtures-hogflows'
import { CdpConsumerBaseDeps } from '../consumers/cdp-base.consumer'
import { CdpRerunWorkerConsumer } from '../consumers/cdp-rerun-worker.consumer'
import { createCdpOutputsRegistry } from '../outputs/registry'
import { CyclotronV2Janitor, JANITOR_POISON_PILL_ERROR_KIND } from '../services/cyclotron-v2'
import { CyclotronJobQueueKafka } from '../services/job-queue/job-queue-kafka'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { HogInvocationResultsService } from '../services/monitoring/hog-invocation-results.service'
import { RerunJobManager } from './rerun-job.manager'
import { RERUN_QUEUE_NAME } from './rerun-job.types'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

const NODE_DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

/**
 * Probe the ClickHouse Kafka MV for the hog_invocation_results topic. With
 * auto.offset.reset=latest, rows produced before the MV's consumer has attached
 * are silently dropped — send probes until one lands so we know the MV is live.
 * (Copied from rerun-e2e.test.ts — same MV-readiness concern.)
 */
const waitForHogInvocationResultsMvReady = async (clickhouse: Clickhouse): Promise<void> => {
    const producer = await ActualKafkaProducerWrapper.create(undefined)
    const probeTeamId = -999_998
    try {
        await waitForExpect(async () => {
            await producer.queueMessages({
                topic: KAFKA_HOG_INVOCATION_RESULTS,
                messages: [
                    {
                        key: 'probe',
                        value: JSON.stringify({
                            team_id: probeTeamId,
                            function_kind: 'hog_flow',
                            function_id: 'probe',
                            invocation_id: 'probe',
                            parent_run_id: '',
                            status: 'running',
                            attempts: 0,
                            is_retry: 0,
                            scheduled_at: DateTime.utc().toFormat("yyyy-MM-dd HH:mm:ss.SSS'000'"),
                            first_scheduled_at: DateTime.utc().toFormat("yyyy-MM-dd HH:mm:ss.SSS'000'"),
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
 * Full-loop recovery e2e: proves the janitor→ClickHouse→rerun seam end to end.
 *
 * The janitor's give-up record and rerun's read query are a producer/consumer
 * contract (the same contract the date-`RangeError` broke). Every other test
 * proves half of it — the janitor writing to Kafka, or rerun reading a
 * hand-seeded row. This is the only one where the janitor's OWN output flows
 * through the real ClickHouse MV and is found + rehydrated by rerun's real
 * query, re-enqueuing the hog flow with its resume point (`currentAction`)
 * intact — which is what makes replay resume instead of re-sending.
 *
 * Real: Kafka, ClickHouse MV, cyclotron-v2 postgres, the janitor, the rerun
 * wrapper-job loop. The only fake is the Django POST (RerunJobManager.enqueue).
 */
describe('CDP janitor poison-pill recovery e2e (janitor → ClickHouse → rerun)', () => {
    jest.setTimeout(60_000)

    let hub: Hub
    let kafkaProducer: KafkaProducerWrapper
    let mockProducerObserver: KafkaProducerObserver
    let team: Team
    let clickhouse: Clickhouse
    let cdpDeps: CdpConsumerBaseDeps
    let kafkaQueue: CyclotronJobQueueKafka
    let postgresV2Queue: CyclotronJobQueuePostgresV2
    let rerunManager: RerunJobManager
    let rerunWorker: CdpRerunWorkerConsumer | undefined
    let janitor: CyclotronV2Janitor | undefined
    let invocationResults: HogInvocationResultsService
    let nodePool: Pool

    beforeAll(() => {
        clickhouse = Clickhouse.create()
    })

    afterAll(() => {
        clickhouse?.close()
    })

    beforeEach(async () => {
        MockKafkaProducerWrapper.create = jest.fn((...args: any[]) => ActualKafkaProducerWrapper.create(...args))

        await ensureKafkaTopics([...TEST_KAFKA_TOPICS, KAFKA_HOG_INVOCATION_RESULTS])
        await clickhouse.truncate('hog_invocation_results_data')
        await waitForHogInvocationResultsMvReady(clickhouse)
        await resetTestDatabase()
        await clickhouse.truncate('hog_invocation_results_data')

        hub = await createHub()
        hub.CYCLOTRON_NODE_DATABASE_URL = NODE_DB_URL
        hub.HOG_INVOCATION_RESULTS_ENABLED = true

        kafkaProducer = await ActualKafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        mockProducerObserver = new KafkaProducerObserver(kafkaProducer)
        team = await getFirstTeam(hub.postgres)
        mockProducerObserver.resetKafkaProducer()

        nodePool = new Pool({ connectionString: NODE_DB_URL })
        await nodePool.query('DELETE FROM cyclotron_jobs')

        cdpDeps = createCdpConsumerDeps(hub, kafkaProducer)
        kafkaQueue = new CyclotronJobQueueKafka(hub.KAFKA_CLIENT_RACK, hub, hub.CONSUMER_BATCH_SIZE)
        postgresV2Queue = new CyclotronJobQueuePostgresV2(hub.CONSUMER_BATCH_SIZE, hub)
        // The rerun re-enqueues hog flows via this queue as a producer.
        await postgresV2Queue.startAsProducer()

        // A janitor wired the same way server.ts wires it: its own results service
        // built from the shared CDP producer registry + outputs.
        const outputs = createCdpOutputsRegistry().build(cdpDeps.cdpProducerRegistry, hub)
        invocationResults = new HogInvocationResultsService(outputs, hub)

        rerunManager = new RerunJobManager({ dbUrl: NODE_DB_URL, maxCount: 10000 })
        await rerunManager.connect()
    })

    afterEach(async () => {
        await Promise.all([
            janitor?.stop().catch(() => undefined),
            rerunWorker?.stop().catch(() => undefined),
            rerunManager?.disconnect().catch(() => undefined),
            postgresV2Queue?.stopProducer().catch(() => undefined),
        ])
        janitor = undefined
        rerunWorker = undefined
        await kafkaProducer?.disconnect()
        await closeHub(hub)
        await nodePool.end()
        mockProducerObserver?.resetKafkaProducer()
    })

    it('records a given-up hog flow to ClickHouse and rerun re-enqueues it with its resume point intact', async () => {
        // trigger → wait → exit. currentAction sits at the wait step, so a
        // correct recovery resumes there rather than restarting from the trigger.
        const flow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withWorkflow({
                actions: {
                    trigger: {
                        type: 'trigger',
                        config: { type: 'event', filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {} },
                    },
                    wait_1: {
                        type: 'wait_until_condition',
                        config: {
                            condition: { filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters },
                            max_wait_duration: '5m',
                        },
                    },
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'wait_1', type: 'continue' },
                    { from: 'wait_1', to: 'exit', type: 'continue' },
                ],
            })
            .build()
        await insertHogFlow(hub.postgres, flow)

        // ── 1. Force a poison pill: running, long-stale heartbeat, over the touch
        //       budget, parked at wait_1 with some progress already made. ──────
        const invocationId = new UUIDT().toString()
        const serializedState = Buffer.from(
            JSON.stringify({
                state: {
                    event: { uuid: '11111111-1111-1111-1111-111111111111', distinct_id: 'recover-me' },
                    actionStepCount: 2,
                    variables: { ticket_id: '4242' },
                    currentAction: { id: 'wait_1', startedAtTimestamp: 1 },
                },
            })
        )
        await nodePool.query(
            `INSERT INTO cyclotron_jobs
                (id, team_id, function_id, queue_name, status, priority, scheduled, created,
                 lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition, state)
             VALUES ($1, $2, $3, 'hogflow', 'running'::CyclotronJobStatus, 0, NOW(), NOW(),
                     $4, NOW() - INTERVAL '5 minutes', 5, 10, NOW(), $5)`,
            [invocationId, team.id, flow.id, new UUIDT().toString(), serializedState]
        )

        // ── 2. Janitor gives up: records the failed, replayable row then deletes ──
        janitor = new CyclotronV2Janitor(
            {
                pool: { dbUrl: NODE_DB_URL },
                cleanupGraceMs: 0,
                stallTimeoutMs: 1000,
                maxTouchCount: 3,
                fleetMinStalledCount: 5,
                fleetStallRatioThreshold: 0.5,
            },
            invocationResults
        )
        const result = await janitor.runOnce()
        expect(result.poisonedIds).toEqual([invocationId])

        // The cyclotron row is gone; the give-up record flows Kafka → MV → CH.
        expect((await nodePool.query('SELECT 1 FROM cyclotron_jobs WHERE id = $1', [invocationId])).rowCount).toBe(0)
        await waitForExpect(async () => {
            const rows = await clickhouse.query<{ c: number }>(
                `SELECT count() AS c FROM hog_invocation_results
                 WHERE team_id = ${team.id} AND function_id = '${flow.id}'
                   AND function_kind = 'hog_flow' AND status = 'failed'
                   AND error_kind = '${JANITOR_POISON_PILL_ERROR_KIND}'
                   AND invocation_id = '${invocationId}'`
            )
            expect(Number(rows[0]?.c ?? 0)).toBeGreaterThanOrEqual(1)
        }, 30_000)

        // ── 3. Operator replays the poison-pill give-ups (fake Django POST) ──────
        const windowStart = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
        const windowEnd = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()
        const rerunJobId = await rerunManager.enqueue(team.id, 'hog_flow', flow.id, {
            filter: {
                window_start: windowStart,
                window_end: windowEnd,
                status: ['failed'],
                error_kind: [JANITOR_POISON_PILL_ERROR_KIND],
            },
        })

        // ── 4. Rerun worker drains the wrapper: real fetchPage query finds the
        //       janitor's row, rehydrates it, re-enqueues to postgres-v2. ────────
        rerunWorker = new CdpRerunWorkerConsumer(
            { ...hub, CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: 'postgres' },
            cdpDeps,
            { hog_function: kafkaQueue, hog_flow: postgresV2Queue }
        )
        await rerunWorker.start()

        await waitForExpect(async () => {
            const res = await nodePool.query('SELECT status FROM cyclotron_jobs WHERE id = $1', [rerunJobId])
            expect(res.rows[0]?.status).toBe('completed')
        }, 30_000)

        // ── 5. The re-enqueued hog flow carries its resume point, not a fresh start ──
        // Same invocation_id (rerun reuses it), back on the hogflow queue, and its
        // serialized state resumes at wait_1 with the pre-give-up variables — proving
        // the janitor's state survived the ClickHouse round-trip and rehydration.
        await waitForExpect(async () => {
            const res = await nodePool.query<{ queue_name: string; status: string; state: Buffer | null }>(
                'SELECT queue_name, status, state FROM cyclotron_jobs WHERE id = $1',
                [invocationId]
            )
            expect(res.rows).toHaveLength(1)
            expect(res.rows[0].queue_name).toBe('hogflow')
            const parsed = JSON.parse(res.rows[0].state!.toString('utf-8'))
            expect(parsed.state.currentAction?.id).toBe('wait_1')
            expect(parsed.state.variables).toEqual({ ticket_id: '4242' })
            expect(parsed.state.actionStepCount).toBe(2)
            // Rehydration stamps the sticky rerun counter so max_attempts guards apply.
            expect(parsed.state.rerunAttempts).toBe(1)
        }, 30_000)
    })
})
