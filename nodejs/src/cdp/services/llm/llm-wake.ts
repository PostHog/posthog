import { Pool } from 'pg'

import { parseJSON } from '~/common/utils/json-parse'

import { HogFlowInvocationContext } from '../../types'
import { LlmStepCompletion, LlmStepError } from './llm-step.types'

// The cyclotron_jobs.state bytea is `Buffer.from(JSON.stringify({ state, queueParameters, queueMetadata }))`
// (see job-queue-postgres-v2 serializeState). We must round-trip the whole blob and only touch the
// nested HogFlowInvocationContext, exactly as the subscription matcher's applyMatchToState does.
type SerializedBlob = {
    state: HogFlowInvocationContext
    queueParameters?: unknown
    queueMetadata?: unknown
}

export type WakeOutcome =
    | 'woken' // the job was parked at this step and we pulled it forward with the result
    | 'missed' // no available row for this id: the timeout already won the race, or the job is gone
    | 'stale' // the row exists but advanced past this step, or the dispatch nonce no longer matches

// Writes an LLM completion or terminal error into a parked job's serialized state, guarded by the
// dispatch nonce so a redelivered/duplicate completion can't wake a later attempt of the same step.
// Returns the new state buffer, or null if the write should be skipped (nonce mismatch / no step).
export function applyLlmOutcomeToState(
    stateBuffer: Buffer,
    args: { nonce: string; completion?: LlmStepCompletion; error?: LlmStepError }
): Buffer | null {
    const parsed = parseJSON(stateBuffer.toString('utf-8')) as SerializedBlob
    const currentAction = parsed.state?.currentAction
    if (!currentAction) {
        return null
    }
    // The step must still be parked on the exact request we dispatched. After a timeout advance the
    // nonce is gone (or a re-dispatch minted a new one), so an old completion is correctly dropped.
    if (currentAction.llmRequestId !== args.nonce) {
        return null
    }
    if (args.completion) {
        currentAction.llmResult = args.completion
    } else if (args.error) {
        currentAction.llmError = args.error
    } else {
        return null
    }
    return Buffer.from(JSON.stringify(parsed))
}

// Wakes exactly one parked LLM job by id. Mirrors the subscription matcher's wake write, but
// addressed to a single primary key instead of a scanned set:
//   - `status = 'available'` is the race guard: if the timeout already flipped the row to 'running'
//     the SELECT returns nothing and we report 'missed' (the run takes its timeout path).
//   - `action_id` must still match this step: after a timeout advance it differs, so we report
//     'stale' rather than clobbering an unrelated step's state.
//   - the read-modify-write runs under FOR UPDATE in one transaction so two deliveries of the same
//     completion can't both write.
export async function wakeParkedLlmJob(
    pool: Pick<Pool, 'connect'>,
    args: { jobId: string; actionId: string; nonce: string; completion?: LlmStepCompletion; error?: LlmStepError }
): Promise<WakeOutcome> {
    const client = await pool.connect()
    try {
        await client.query('BEGIN')

        const selected = await client.query(
            `SELECT state, action_id FROM cyclotron_jobs WHERE id = $1 AND status = 'available' FOR UPDATE`,
            [args.jobId]
        )
        if (selected.rows.length === 0) {
            await client.query('ROLLBACK')
            return 'missed'
        }

        const row = selected.rows[0]
        if (row.action_id !== args.actionId || !row.state) {
            await client.query('ROLLBACK')
            return 'stale'
        }

        const newState = applyLlmOutcomeToState(row.state, {
            nonce: args.nonce,
            completion: args.completion,
            error: args.error,
        })
        if (!newState) {
            await client.query('ROLLBACK')
            return 'stale'
        }

        await client.query(
            `UPDATE cyclotron_jobs SET scheduled = NOW(), state = $2 WHERE id = $1 AND status = 'available'`,
            [args.jobId, newState]
        )
        await client.query('COMMIT')
        return 'woken'
    } catch (err) {
        await client.query('ROLLBACK').catch(() => {})
        throw err
    } finally {
        client.release()
    }
}
