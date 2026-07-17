import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { parseJSON } from '~/common/utils/json-parse'

import { CyclotronV2Manager } from '../cyclotron-v2/manager'
import { wakeParkedLlmJob } from './llm-wake'

// Exercises the real wake path against a live cyclotron_jobs table: park a job (status='available'
// with an action_id and a serialized state blob), then prove wakeParkedLlmJob pulls it forward with
// the completion, and that the timeout / advanced-step races are handled as the RFC claims. Runs in
// the main test group alongside cyclotron-v2.test.ts, which requires the cyclotron DB. Guarded so it
// skips (loudly) rather than crashing where that DB isn't available (e.g. a local subset run).

const DB_URL =
    process.env.CYCLOTRON_NODE_DATABASE_URL ?? 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

function parkedStateBuffer(actionId: string, nonce: string): Buffer {
    return Buffer.from(
        JSON.stringify({
            state: {
                event: {},
                actionStepCount: 1,
                currentAction: { id: actionId, startedAtTimestamp: 0, llmRequestId: nonce },
            },
        })
    )
}

describe('wakeParkedLlmJob (integration)', () => {
    let pool: Pool
    let manager: CyclotronV2Manager
    let dbAvailable = true

    beforeAll(async () => {
        pool = new Pool({ connectionString: DB_URL })
        try {
            await pool.query('SELECT 1 FROM cyclotron_jobs LIMIT 1')
            manager = new CyclotronV2Manager({
                pool: { dbUrl: DB_URL },
                depthLimit: 1_000_000,
                depthCheckIntervalMs: 0,
            })
            await manager.connect()
        } catch {
            dbAvailable = false
            // eslint-disable-next-line no-console
            console.warn(`[llm-wake.integration] cyclotron DB unavailable at ${DB_URL} - skipping integration tests`)
        }
    })

    afterAll(async () => {
        if (manager) {
            await manager.disconnect()
        }
        await pool?.end()
    })

    beforeEach(async () => {
        if (dbAvailable) {
            await pool.query('DELETE FROM cyclotron_jobs')
        }
    })

    // Parks a job at an LLM step and returns its id.
    const parkJob = async (actionId: string, nonce: string): Promise<string> => {
        return await manager.createJob({
            teamId: 1,
            queueName: 'hogflow',
            functionId: uuidv7(),
            actionId,
            state: parkedStateBuffer(actionId, nonce),
            scheduled: new Date(Date.now() + 60 * 60 * 1000), // parked an hour out
        })
    }

    const jobRow = async (id: string): Promise<{ scheduled: Date; status: string; state: Buffer }> => {
        const res = await pool.query('SELECT scheduled, status, state FROM cyclotron_jobs WHERE id = $1', [id])
        return res.rows[0]
    }

    it('wakes a parked job and writes the completion into its state', async () => {
        if (!dbAvailable) {
            return
        }
        const id = await parkJob('a1', 'n1')

        const outcome = await wakeParkedLlmJob(pool, {
            jobId: id,
            actionId: 'a1',
            nonce: 'n1',
            completion: { text: 'the answer', model: 'gpt-4o-mini' },
        })

        expect(outcome).toBe('woken')
        const row = await jobRow(id)
        // Pulled forward to ~now (was an hour out), still available for a worker to pick up.
        expect(row.status).toBe('available')
        expect(row.scheduled.getTime()).toBeLessThan(Date.now() + 5_000)
        // The completion is now in the parked step's state.
        const state = parseJSON(row.state.toString('utf-8'))
        expect(state.state.currentAction.llmResult).toEqual({ text: 'the answer', model: 'gpt-4o-mini' })
    })

    it('reports missed and leaves the row untouched when the job is already running (timeout won)', async () => {
        if (!dbAvailable) {
            return
        }
        const id = await parkJob('a1', 'n1')
        // Simulate the timeout dequeue winning the race: a worker flipped it to running.
        await pool.query(`UPDATE cyclotron_jobs SET status = 'running' WHERE id = $1`, [id])

        const outcome = await wakeParkedLlmJob(pool, {
            jobId: id,
            actionId: 'a1',
            nonce: 'n1',
            completion: { text: 'the answer' },
        })

        expect(outcome).toBe('missed')
        const state = parseJSON((await jobRow(id)).state.toString('utf-8'))
        expect(state.state.currentAction.llmResult).toBeUndefined()
    })

    it('reports stale when the job has advanced to a different step', async () => {
        if (!dbAvailable) {
            return
        }
        const id = await parkJob('a2', 'n1') // parked at a different action than we dispatched from

        const outcome = await wakeParkedLlmJob(pool, {
            jobId: id,
            actionId: 'a1',
            nonce: 'n1',
            completion: { text: 'the answer' },
        })

        expect(outcome).toBe('stale')
    })
})
