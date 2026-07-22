import { ClickHouseClient } from '@clickhouse/client'
import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'

import { RerunJobManager } from '../../rerun/rerun-job.manager'
import { RERUN_QUEUE_NAME } from '../../rerun/rerun-job.types'
import { HogInvocationResultsService } from '../monitoring/hog-invocation-results.service'
import { CyclotronV2Janitor, JANITOR_POISON_PILL_ERROR_KIND } from './janitor'
import { CyclotronPoisonPillAutodrain, CyclotronPoisonPillAutodrainConfig } from './poison-pill-autodrain'

const ActualKafkaProducerWrapper = jest.requireActual('~/common/kafka/producer').KafkaProducerWrapper

const NODE_DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

// A synthetic team the rest of the suite never touches — the autodrain path works
// purely off ClickHouse rows + cyclotron_jobs, so no real Team/HogFunction is
// needed, and an isolated team_id keeps this test's rows out of everyone else's.
const TEST_TEAM_ID = 920250716

// A normal invocation queue (NOT a wrapper queue) — the janitor records these as
// replayable poison pills, which is exactly what the autodrain then drains.
const INVOCATION_QUEUE = 'hog_function'

const autodrainConfig: CyclotronPoisonPillAutodrainConfig = {
    intervalMs: 60_000,
    windowHours: 24,
    maxAttempts: 3,
    groupBatch: 100,
    maxCountPerGroup: 1000,
}

/**
 * Probe the ClickHouse Kafka MV for hog_invocation_results. With
 * auto.offset.reset=latest, rows produced before the MV's consumer attaches are
 * silently dropped — send probes until one lands so we know the MV is live.
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
                            function_kind: 'hog_function',
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
 * End-to-end exercise of the poison-pill autodrain — nothing is mocked.
 *
 * The janitor records a real give-up (real HogInvocationResultsService -> real
 * Kafka -> real ClickHouse Kafka MV -> hog_invocation_results) and deletes the
 * cyclotron row, exactly as it does in production. Then the real autodrain runs
 * its real `discoverGroups` ClickHouse query against that recorded row and
 * enqueues a real rerun wrapper into cyclotron_jobs via the real RerunJobManager.
 *
 * This is the integration seam the unit test can't reach: it mocks ClickHouse and
 * the RerunJobManager, so it never proves the discovery SQL actually matches a row
 * the janitor writes (schema/argMax/ReplacingMergeTree agreement), nor that a
 * wrapper really lands — nor that the in-flight guard self-dedups on the next tick.
 */
describe('CyclotronPoisonPillAutodrain e2e', () => {
    jest.setTimeout(60_000)

    let clickhouse: Clickhouse
    let chClient: ClickHouseClient
    let kafkaProducer: KafkaProducerWrapper
    let nodePool: Pool
    let resultsService: HogInvocationResultsService
    let janitor: CyclotronV2Janitor
    let rerunManager: RerunJobManager
    let autodrain: CyclotronPoisonPillAutodrain

    beforeAll(() => {
        clickhouse = Clickhouse.create()
        chClient = Clickhouse.createClient()
    })

    afterAll(() => {
        clickhouse?.close()
        chClient?.close()
    })

    beforeEach(async () => {
        await ensureKafkaTopics([...TEST_KAFKA_TOPICS, KAFKA_HOG_INVOCATION_RESULTS])
        await clickhouse.truncate('hog_invocation_results_data')
        await waitForHogInvocationResultsMvReady(clickhouse)
        await clickhouse.truncate('hog_invocation_results_data')

        kafkaProducer = await ActualKafkaProducerWrapper.create(undefined)

        nodePool = new Pool({ connectionString: NODE_DB_URL })
        await nodePool.query('DELETE FROM cyclotron_jobs WHERE team_id = $1', [TEST_TEAM_ID])

        // Real results service over a real producer targeting the lifecycle topic —
        // the same buildLifecycleRow + produce path the janitor uses in production.
        const outputs = {
            produce: async (_output: string, message: { key: Buffer; value: Buffer }): Promise<void> => {
                await kafkaProducer.queueMessages({
                    topic: KAFKA_HOG_INVOCATION_RESULTS,
                    messages: [{ key: message.key, value: message.value }],
                })
                await kafkaProducer.flush()
            },
        }
        resultsService = new HogInvocationResultsService(outputs as any, { HOG_INVOCATION_RESULTS_ENABLED: true })

        janitor = new CyclotronV2Janitor(
            {
                pool: { dbUrl: NODE_DB_URL },
                cleanupGraceMs: 0,
                stallTimeoutMs: 1_000,
                maxTouchCount: 2,
                stallBackoffBaseMs: 0,
            },
            resultsService
        )

        rerunManager = new RerunJobManager({ dbUrl: NODE_DB_URL, maxCount: 10_000 })
        await rerunManager.connect()

        autodrain = new CyclotronPoisonPillAutodrain(chClient, rerunManager, autodrainConfig)
    })

    afterEach(async () => {
        await janitor?.stop().catch(() => undefined)
        await rerunManager?.disconnect().catch(() => undefined)
        await nodePool?.query('DELETE FROM cyclotron_jobs WHERE team_id = $1', [TEST_TEAM_ID]).catch(() => undefined)
        await nodePool?.end()
        await kafkaProducer?.disconnect()
    })

    it('records a poison pill, then discovers and drains it into a rerun wrapper, deduping next tick', async () => {
        const functionId = uuidv7()
        const jobId = uuidv7()

        // ── 1. A poisoned invocation the janitor will give up on ────────────────
        // status='running', a stale heartbeat and touch_count past the cap is the
        // "classic poison pill" the janitor records-then-deletes.
        await nodePool.query(
            `INSERT INTO cyclotron_jobs
                (id, team_id, function_id, queue_name, status, priority, scheduled, created,
                 lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition,
                 parent_run_id, state)
             VALUES ($1, $2, $3, $4, 'running'::CyclotronJobStatus, 0, $5, $5,
                     $6, $7, 3, 0, $5, NULL, NULL)`,
            [jobId, TEST_TEAM_ID, functionId, INVOCATION_QUEUE, new Date(), uuidv7(), new Date(Date.now() - 60_000)]
        )

        // ── 2. Janitor records the give-up to ClickHouse and deletes the row ────
        const janitorResult = await janitor.runOnce()
        expect(janitorResult.poisonedIds).toEqual([jobId])
        // The cyclotron row is gone — recovery now lives only in the recorded row.
        const remaining = await nodePool.query('SELECT id FROM cyclotron_jobs WHERE id = $1', [jobId])
        expect(remaining.rows).toHaveLength(0)

        // ── 3. Recorded poison pill lands in ClickHouse via Kafka -> MV ─────────
        await waitForExpect(async () => {
            const rows = await clickhouse.query<{ c: number }>(
                `SELECT count() AS c FROM hog_invocation_results
                 WHERE team_id = ${TEST_TEAM_ID}
                   AND status = 'failed'
                   AND error_kind = '${JANITOR_POISON_PILL_ERROR_KIND}'`
            )
            expect(Number(rows[0]?.c ?? 0)).toBeGreaterThanOrEqual(1)
        }, 30_000)

        // ── 4. Autodrain discovers the group and enqueues a real rerun wrapper ──
        const drain = await autodrain.runOnce()
        expect(drain).toEqual({ groups: 1, enqueued: 1 })

        const wrappers = await nodePool.query(
            `SELECT id, function_id, status FROM cyclotron_jobs
             WHERE team_id = $1 AND queue_name = $2`,
            [TEST_TEAM_ID, RERUN_QUEUE_NAME]
        )
        expect(wrappers.rows).toHaveLength(1)
        // The janitor tags every poisoned row hog_flow, so the wrapper drains the
        // recorded function under that same target function_id.
        expect(wrappers.rows[0].function_id).toBe(functionId)

        // ── 5. Next tick self-dedups: the wrapper is still in-flight, so the
        // group is skipped rather than piling up a second wrapper ───────────────
        const drainAgain = await autodrain.runOnce()
        expect(drainAgain).toEqual({ groups: 1, enqueued: 0 })
        const wrappersAfter = await nodePool.query(
            `SELECT count(*)::int AS c FROM cyclotron_jobs WHERE team_id = $1 AND queue_name = $2`,
            [TEST_TEAM_ID, RERUN_QUEUE_NAME]
        )
        expect(wrappersAfter.rows[0].c).toBe(1)
    })
})
