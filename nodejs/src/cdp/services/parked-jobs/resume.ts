import { Pool } from 'pg'

import { parseJSON } from '~/common/utils/json-parse'

import { HogFlowInvocationContext } from '../../types'

// Generic park-and-resume primitive for hogflow jobs.
//
// A long-running step parks its Cyclotron job (returns `{ scheduledAt }` so the worker is freed in
// milliseconds) and is later woken *by id* when an external response lands — an LLM completion
// today, a task/agent callback or an authenticated form submission tomorrow. Everything here is
// caller-agnostic: the caller supplies how to write its own payload into the parked state; this
// module owns the race-safe wake against `cyclotron_jobs`.

// The cyclotron_jobs.state bytea is `Buffer.from(JSON.stringify({ state, queueParameters, queueMetadata }))`
// (see job-queue-postgres-v2 serializeState). We round-trip the whole blob and only touch the
// nested HogFlowInvocationContext, exactly as the subscription matcher's applyMatchToState does.
type SerializedBlob = {
    state: HogFlowInvocationContext
    queueParameters?: unknown
    queueMetadata?: unknown
}

// A parked step's currentAction — the shared per-step state bag where each caller stashes its own
// dispatch nonce and result/error keys (e.g. the LLM step uses `llmRequestId` / `llmResult` /
// `llmError`; a future task step would add its own). This module only round-trips the blob.
export type ParkedAction = NonNullable<HogFlowInvocationContext['currentAction']>

export type WakeOutcome =
    | 'woken' // the job was parked at this step and we pulled it forward with the result
    | 'missed' // no available row for this id: the timeout already won the race, or the job is gone
    | 'stale' // the row exists but advanced past this step, or the dispatch nonce no longer matches

// Applies a caller mutation to a parked job's serialized state. `mutate` inspects the parked step's
// currentAction (checking its own dispatch nonce) and writes its payload; returning false skips the
// write (nonce mismatch / wrong step) so the caller reports 'stale'. Returns the new state buffer,
// or null when the write was skipped or there is no parked step.
export function applyResumeToState(
    stateBuffer: Buffer,
    mutate: (currentAction: ParkedAction) => boolean
): Buffer | null {
    const parsed = parseJSON(stateBuffer.toString('utf-8')) as SerializedBlob
    const currentAction = parsed.state?.currentAction
    if (!currentAction) {
        return null
    }
    if (!mutate(currentAction)) {
        return null
    }
    return Buffer.from(JSON.stringify(parsed))
}

// Wakes exactly one parked job by id. Mirrors the subscription matcher's wake write, but addressed
// to a single primary key instead of a scanned set:
//   - `status = 'available'` is the race guard: if the timeout already flipped the row to 'running'
//     the SELECT returns nothing and we report 'missed' (the run takes its timeout path).
//   - `action_id` must still match the parked step: after a timeout advance it differs, so we report
//     'stale' rather than clobbering an unrelated step's state.
//   - `applyOutcome` writes the caller's payload (returning null to report 'stale', e.g. on a nonce
//     mismatch), all under FOR UPDATE in one transaction so two deliveries can't both write.
export async function wakeParkedJob(
    pool: Pick<Pool, 'connect'>,
    args: { jobId: string; actionId: string; applyOutcome: (stateBuffer: Buffer) => Buffer | null }
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

        const newState = args.applyOutcome(row.state)
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
