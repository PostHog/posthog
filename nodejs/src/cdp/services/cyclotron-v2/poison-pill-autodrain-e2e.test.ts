import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { CyclotronV2Janitor } from './janitor'
import { CyclotronPoisonPillAutodrain } from './poison-pill-autodrain'

const NODE_DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

// Isolated synthetic team so these rows never collide with the rest of the suite.
const TEST_TEAM_ID = 920250718
const MAX_ATTEMPTS = 3

/**
 * Postgres-backed integration test for the poison-pill park-and-retry flow.
 *
 * The janitor PARKS a poison pill (keeps the real row, pushes `scheduled` to
 * infinity so no worker dequeues it, stamps poison_retry_count) instead of deleting
 * it, and the autodrain RELEASES it back to its queue by moving `scheduled` to now.
 * The whole loop is Postgres — no ClickHouse, no Kafka — so it can't double-execute
 * from ClickHouse-visibility lag the way the old delete + ClickHouse-rediscover
 * design could. These tests pin that: park (not delete), release exactly once, and
 * a bounded number of retries.
 */
describe('CyclotronPoisonPillAutodrain (park-and-retry)', () => {
    let pool: Pool
    let janitor: CyclotronV2Janitor
    let autodrain: CyclotronPoisonPillAutodrain

    beforeEach(async () => {
        pool = new Pool({ connectionString: NODE_DB_URL })
        await pool.query('DELETE FROM cyclotron_jobs WHERE team_id = $1', [TEST_TEAM_ID])

        // No results service: the janitor skips the best-effort ClickHouse record and
        // just parks — which is all this flow needs, and keeps the test CH/Kafka-free.
        janitor = new CyclotronV2Janitor({
            pool: { dbUrl: NODE_DB_URL },
            cleanupGraceMs: 0,
            stallTimeoutMs: 1_000,
            maxTouchCount: 2,
            stallBackoffBaseMs: 0,
        })
        autodrain = new CyclotronPoisonPillAutodrain(pool, {
            intervalMs: 60_000,
            maxAttempts: MAX_ATTEMPTS,
            batchSize: 100,
        })
    })

    afterEach(async () => {
        await janitor?.stop().catch(() => undefined)
        await pool?.query('DELETE FROM cyclotron_jobs WHERE team_id = $1', [TEST_TEAM_ID]).catch(() => undefined)
        await pool?.end()
    })

    const insertStuckJob = async (jobId: string): Promise<void> => {
        // status='running' with a stale heartbeat and touch_count past the cap is the
        // "classic poison pill" the janitor gives up on.
        await pool.query(
            `INSERT INTO cyclotron_jobs
                (id, team_id, function_id, queue_name, status, priority, scheduled, created,
                 lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition, parent_run_id, state)
             VALUES ($1, $2, $3, 'hogflow', 'running'::CyclotronJobStatus, 0, $4, $4,
                     $5, $6, 3, 0, $4, NULL, NULL)`,
            [jobId, TEST_TEAM_ID, uuidv7(), new Date(), uuidv7(), new Date(Date.now() - 60_000)]
        )
    }

    const insertParkedJob = async (jobId: string, retryCount: number): Promise<void> => {
        await pool.query(
            `INSERT INTO cyclotron_jobs
                (id, team_id, function_id, queue_name, status, priority, scheduled, created,
                 janitor_touch_count, transition_count, last_transition, parent_run_id, state, poison_retry_count)
             VALUES ($1, $2, $3, 'hogflow', 'available'::CyclotronJobStatus, 0, 'infinity', NOW(),
                     0, 0, NOW(), NULL, NULL, $4)`,
            [jobId, TEST_TEAM_ID, uuidv7(), retryCount]
        )
    }

    const readJob = async (
        jobId: string
    ): Promise<{ status: string; parked: boolean; count: number | null } | null> => {
        const res = await pool.query<{ status: string; parked: boolean; count: number | null }>(
            `SELECT status::text, scheduled = 'infinity' AS parked, poison_retry_count AS count
             FROM cyclotron_jobs WHERE id = $1`,
            [jobId]
        )
        return res.rows[0] ?? null
    }

    it('parks a poison pill instead of deleting it, then releases it back to its queue exactly once', async () => {
        const jobId = uuidv7()
        await insertStuckJob(jobId)

        // Janitor gives up on it: parks (does NOT delete).
        const janitorResult = await janitor.runOnce()
        expect(janitorResult.poisonedIds).toEqual([jobId])
        const afterPark = await readJob(jobId)
        expect(afterPark).toEqual({ status: 'available', parked: true, count: 0 })

        // Autodrain releases it: scheduled moves off 'infinity', count increments.
        expect(await autodrain.runOnce()).toEqual({ released: 1 })
        const afterRelease = await readJob(jobId)
        expect(afterRelease).toEqual({ status: 'available', parked: false, count: 1 })

        // The no-duplicate guarantee: the next tick must NOT release it again — it is
        // no longer parked (scheduled != 'infinity'), so it can't be re-released while
        // it waits for / runs on a worker. A second release here would be a duplicate
        // execution, which is exactly what this design removes by construction.
        expect(await autodrain.runOnce()).toEqual({ released: 0 })
        expect((await readJob(jobId))?.count).toBe(1)
    })

    it('stops releasing a parked poison pill once it reaches max attempts', async () => {
        const belowCap = uuidv7()
        const atCap = uuidv7()
        await insertParkedJob(belowCap, MAX_ATTEMPTS - 1)
        await insertParkedJob(atCap, MAX_ATTEMPTS)

        // Only the under-cap job is released; the at-cap job is left parked (dead-letter).
        expect(await autodrain.runOnce()).toEqual({ released: 1 })
        expect(await readJob(belowCap)).toEqual({ status: 'available', parked: false, count: MAX_ATTEMPTS })
        expect(await readJob(atCap)).toEqual({ status: 'available', parked: true, count: MAX_ATTEMPTS })
    })
})
