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

// Insert a recorded poison-pill row straight into ClickHouse, in the exact shape the
// janitor's give-up produces (function_kind='hog_flow', status='failed',
// error_kind='janitor_poison_pill'). insert_distributed_sync makes it immediately
// visible to discovery, so a test that only exercises the autodrain's dedup logic —
// not the janitor -> MV write path — stays deterministic without the Kafka/MV probe.
const insertRecordedPoisonPill = async (
    chClient: ClickHouseClient,
    opts: { teamId: number; functionId: string; invocationId: string }
): Promise<void> => {
    const now = DateTime.utc().toFormat("yyyy-MM-dd HH:mm:ss.SSS'000'")
    await chClient.insert({
        table: 'hog_invocation_results',
        format: 'JSONEachRow',
        values: [
            {
                team_id: opts.teamId,
                function_kind: 'hog_flow',
                function_id: opts.functionId,
                invocation_id: opts.invocationId,
                parent_run_id: '',
                status: 'failed',
                attempts: 0,
                is_retry: 0,
                scheduled_at: now,
                first_scheduled_at: now,
                started_at: null,
                finished_at: null,
                duration_ms: null,
                error_kind: JANITOR_POISON_PILL_ERROR_KIND,
                error_message: 'poison pill',
                event_uuid: '',
                distinct_id: '',
                person_id: '',
                invocation_globals: '{}',
                version: String(BigInt(Date.now()) * 1000n),
                is_deleted: 0,
            },
        ],
        clickhouse_settings: { insert_distributed_sync: 1 },
    })
}

/**
 * End-to-end exercise of the poison-pill autodrain against real infrastructure
 * (Kafka + ClickHouse + Postgres), nothing mocked.
 *
 * Its reason to exist — the one thing only this test can prove: the autodrain's
 * real `discoverGroups` ClickHouse query actually matches a row the janitor really
 * WRITES (janitor buildLifecycleRow -> Kafka -> ClickHouse Kafka MV ->
 * hog_invocation_results: schema / argMax / ReplacingMergeTree agreement). The unit
 * test mocks ClickHouse, so it cannot catch a drift there — a renamed column or a
 * changed `version` semantics that silently makes discovery return nothing. It also
 * proves a real rerun wrapper lands, and that the real in-flight-wrapper query
 * skips a group whose wrapper is still outstanding.
 *
 * What it deliberately does NOT prove: that duplicates can't happen. The only dedup
 * it exercises is the in-flight-wrapper guard (the easy case). The harder duplicate
 * — a completed-and-swept rerun that gets re-discovered while ClickHouse still lags
 * behind — is a known gap, documented and reproduced by the second test below.
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

    afterAll(async () => {
        clickhouse?.close()
        await chClient?.close()
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

    it('discovers a janitor-recorded poison pill, drains it into a rerun wrapper, and skips while that wrapper is in-flight', async () => {
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

        // ── 5. In-flight guard: while the wrapper from step 4 is still on the rerun
        // queue, the next tick's real hasInFlightWrapper query finds it and skips the
        // group, so no second wrapper piles up. This proves ONLY the in-flight guard
        // (the real query, end to end) — it does NOT prove duplicates are impossible.
        // Once that wrapper completes and is swept, a stale ClickHouse row can
        // re-trigger a drain; the second test below documents and reproduces that gap.
        const drainAgain = await autodrain.runOnce()
        expect(drainAgain).toEqual({ groups: 1, enqueued: 0 })
        const wrappersAfter = await nodePool.query(
            `SELECT count(*)::int AS c FROM cyclotron_jobs WHERE team_id = $1 AND queue_name = $2`,
            [TEST_TEAM_ID, RERUN_QUEUE_NAME]
        )
        expect(wrappersAfter.rows[0].c).toBe(1)
    })

    // KNOWN GAP — a duplicate re-drain when ClickHouse lags behind the drain. This
    // test exists to make the gap the in-flight guard does NOT close visible in the
    // suite, rather than hidden behind a green "dedup" assertion.
    //
    // Mechanism: cross-tick dedup relies entirely on ClickHouse argMax visibility. The
    // only airtight guard (the in-flight wrapper) protects a group ONLY while its
    // cyclotron row exists. Once a drained rerun completes and its row is swept, but
    // the rerun's new running/succeeded lifecycle rows have not yet landed in
    // ClickHouse (ingestion lag), the next tick still sees the stale poison row, finds
    // no in-flight wrapper, and re-enqueues — a duplicate rerun that re-fires
    // post-currentAction side effects (emails/webhooks). Bounded by max_attempts, but
    // each cycle is a real duplicate. Reachable on a single pod whenever
    // ClickHouse-visibility-lag exceeds the autodrain interval.
    //
    // Closing it needs durable, strongly-consistent drain state that outlives the
    // cyclotron row — e.g. a Postgres drain-marker keyed by invocation_id — because
    // after a successful rerun is swept, the lagging ClickHouse row is the only trace
    // left to dedup against. When that lands, tick 2 below stops re-enqueuing
    // (enqueued: 0) and the final assertion here flips RED: change it to enqueued: 0,
    // delete this note, and it becomes the real regression guard against the duplicate.
    it('re-drains a completed invocation when its wrapper is gone but ClickHouse still shows the poison', async () => {
        const functionId = uuidv7()
        const invocationId = uuidv7()

        // A poison pill already recorded in ClickHouse (as if the janitor gave up on
        // it). Inserted directly — this test exercises the autodrain's cross-tick
        // dedup, not the janitor -> MV write path (the test above covers that), so it
        // skips the Kafka/MV hop and stays deterministic.
        await insertRecordedPoisonPill(chClient, { teamId: TEST_TEAM_ID, functionId, invocationId })
        await waitForExpect(async () => {
            const rows = await clickhouse.query<{ c: number }>(
                `SELECT count() AS c FROM hog_invocation_results
                 WHERE team_id = ${TEST_TEAM_ID} AND error_kind = '${JANITOR_POISON_PILL_ERROR_KIND}'`
            )
            expect(Number(rows[0]?.c ?? 0)).toBeGreaterThanOrEqual(1)
        }, 10_000)

        // Tick 1: discovers the group and enqueues a wrapper.
        expect(await autodrain.runOnce()).toEqual({ groups: 1, enqueued: 1 })

        // The drained rerun COMPLETED and its wrapper was swept by cleanupTerminalJobs,
        // but its running/succeeded lifecycle rows have NOT yet materialized in
        // ClickHouse. Modeled by deleting the wrapper while the stale poison row stays
        // in place: no in-flight wrapper, ClickHouse still shows the pill.
        await nodePool.query('DELETE FROM cyclotron_jobs WHERE team_id = $1 AND queue_name = $2', [
            TEST_TEAM_ID,
            RERUN_QUEUE_NAME,
        ])

        // Tick 2 SHOULD skip (the invocation already ran) -> enqueued 0. It does not
        // today: the stale ClickHouse row is re-discovered and re-enqueued. We assert
        // the current (buggy) value so the suite documents the gap and stays green
        // until the dedup fix lands, at which point this flips red (see the note above).
        const tick2 = await autodrain.runOnce()
        expect(tick2).toEqual({ groups: 1, enqueued: 1 }) // KNOWN GAP: should be { groups: 1, enqueued: 0 } once drain state is durable
    })
})
