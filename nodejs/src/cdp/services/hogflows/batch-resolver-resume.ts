import { Pool } from 'pg'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { HOGFLOW_BATCH_RESOLVE_QUEUE, deserializeResolverState, serializeResolverState } from './batch-resolver.types'

// `job_<status>` covers a resolver that is not parked; `resumed` and `already_resumed` both mean
// the run is on its way.
export type BatchResolverResumeOutcome = 'resumed' | 'already_resumed' | 'job_missing' | `job_${string}`

export const counterBatchResolverParked = new Counter({
    name: 'cdp_batch_hog_flow_resolver_parked',
    help: 'Batch resolvers created parked because their realtime cohort is still calculating.',
})

export const counterBatchResolverResume = new Counter({
    name: 'cdp_batch_hog_flow_resolver_resume',
    help: 'Resumes of batch resolvers parked on a realtime cohort, by outcome.',
    labelNames: ['outcome'],
})

/**
 * Wakes a batch resolver parked until its realtime cohort finishes calculating. Clears the wait
 * from its state and makes it due now, the same way a step resume wakes a parked workflow step.
 */
export async function resumeParkedBatchResolver(
    pool: Pool,
    { teamId, functionId, batchJobId }: { teamId: number; functionId: string; batchJobId: string }
): Promise<BatchResolverResumeOutcome> {
    const outcome = await resume(pool, teamId, functionId, batchJobId)
    counterBatchResolverResume.labels({ outcome }).inc()
    return outcome
}

async function resume(
    pool: Pool,
    teamId: number,
    functionId: string,
    batchJobId: string
): Promise<BatchResolverResumeOutcome> {
    const client = await pool.connect()
    try {
        await client.query('BEGIN')
        const rows = await client.query(
            `SELECT id, status, state FROM cyclotron_jobs
             WHERE team_id = $1 AND function_id = $2 AND parent_run_id = $3 AND queue_name = $4
             FOR UPDATE`,
            [teamId, functionId, batchJobId, HOGFLOW_BATCH_RESOLVE_QUEUE]
        )
        const row = rows.rows[0]
        if (!row) {
            await client.query('COMMIT')
            return 'job_missing'
        }
        // A running resolver owns its state, so a write here would be dropped by its flush.
        if (row.status !== 'available') {
            await client.query('COMMIT')
            return `job_${row.status}`
        }
        const state = deserializeResolverState(row.state)
        if (!state.realtimeCohort?.waitUntil) {
            await client.query('COMMIT')
            return 'already_resumed'
        }
        const { waitUntil: _waitUntil, ...realtimeCohort } = state.realtimeCohort
        await client.query(`UPDATE cyclotron_jobs SET scheduled = NOW(), state = $2 WHERE id = $1`, [
            row.id,
            serializeResolverState({ ...state, realtimeCohort }),
        ])
        await client.query('COMMIT')
        return 'resumed'
    } catch (err) {
        await client.query('ROLLBACK').catch(() => {})
        logger.error('🔴', 'Failed to resume a parked batch resolver', { batchJobId, error: String(err) })
        throw err
    } finally {
        client.release()
    }
}
