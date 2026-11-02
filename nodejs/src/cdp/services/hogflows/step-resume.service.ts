import { Pool } from 'pg'
import { Counter } from 'prom-client'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { CYCLOTRON_JOB_TABLES } from '../cyclotron-v2/tables'

export const WorkflowStepResumeSchema = z.object({
    origin_key: z.string().min(1),
    status: z.enum(['completed', 'failed', 'cancelled']),
    result: z.record(z.string(), z.unknown()).optional().nullable(),
})

export type StepResume = z.infer<typeof WorkflowStepResumeSchema> & { jobId: string; actionId: string }

// `job_<status>` covers every non-parked cyclotron status; `delivered` is the only success.
export type StepResumeOutcome = 'delivered' | 'stale_key' | 'job_missing' | `job_${string}`

export const counterStepResume = new Counter({
    name: 'cdp_hogflow_step_resume',
    help: 'Workflow step resumes by outcome.',
    labelNames: ['outcome'],
})

// Stamps the resume onto the parked step. Returns null when the job is not waiting on this exact
// key: the step already advanced, or the wake belongs to an earlier visit of the same step.
export function applyStepResumeToState(stateBuffer: Buffer, resume: StepResume): Buffer | null {
    try {
        const parsed = parseJSON(stateBuffer.toString('utf-8'))
        const currentAction = parsed.state?.currentAction
        if (currentAction?.id !== resume.actionId || currentAction.awaitingResume?.key !== resume.origin_key) {
            return null
        }
        parsed.state = {
            ...parsed.state,
            currentAction: {
                ...currentAction,
                resumeResult: {
                    key: resume.origin_key,
                    status: resume.status,
                    result: resume.result ?? undefined,
                },
            },
        }
        return Buffer.from(JSON.stringify(parsed))
    } catch (err) {
        logger.warn('Failed to parse state during step resume', { jobId: resume.jobId, err })
        return null
    }
}

// Hands each resume to its parked job. `teamId` narrows the lookup for callers whose auth is
// team-scoped; the matcher passes none because one Kafka batch spans teams.
export async function processStepResumes(
    pool: Pool,
    resumes: StepResume[],
    teamId?: number
): Promise<Map<string, StepResumeOutcome>> {
    const outcomes = new Map<string, StepResumeOutcome>()
    if (resumes.length === 0) {
        return outcomes
    }
    const byJob = new Map<string, StepResume[]>()
    for (const resume of resumes) {
        const pending = byJob.get(resume.jobId) ?? []
        pending.push(resume)
        byJob.set(resume.jobId, pending)
    }
    const client = await pool.connect()
    try {
        await client.query('BEGIN')
        // One statement per table rather than a UNION, because FOR UPDATE cannot lock
        // through one. Always in the same table order, so the lock order is stable.
        const selected: { id: string; status: string; state: Buffer | null }[] = []
        for (const table of CYCLOTRON_JOB_TABLES) {
            const rows = await client.query<{ id: string; status: string; state: Buffer | null }>(
                `SELECT id, status, state FROM ${table} WHERE id = ANY($1::uuid[])${
                    teamId === undefined ? '' : ' AND team_id = $2'
                } ORDER BY id FOR UPDATE`,
                teamId === undefined ? [[...byJob.keys()]] : [[...byJob.keys()], teamId]
            )
            selected.push(...rows.rows)
        }
        const updates: { id: string; state: Buffer }[] = []
        for (const row of selected) {
            const jobResumes = byJob.get(row.id)!
            byJob.delete(row.id)
            // A job that is not parked yet cannot take the wake: the worker owns `state` while it
            // runs, so its flush would drop the write. The caller decides whether to retry.
            if (row.status !== 'available') {
                outcomes.set(row.id, `job_${row.status}`)
                continue
            }
            // One batch can carry a stale wake from an earlier visit next to the current one.
            const current = row.state
            const state = current
                ? jobResumes.reduce<Buffer | null>(
                      (applied, resume) => applied ?? applyStepResumeToState(current, resume),
                      null
                  )
                : null
            if (!state) {
                outcomes.set(row.id, 'stale_key')
                continue
            }
            updates.push({ id: row.id, state })
        }
        for (const jobId of byJob.keys()) {
            outcomes.set(jobId, 'job_missing')
        }
        if (updates.length > 0) {
            const written = new Set<string>()
            for (const table of CYCLOTRON_JOB_TABLES) {
                const updated = await client.query<{ id: string }>(
                    `UPDATE ${table} cj
                 SET scheduled = NOW(), state = u.state
                 FROM (SELECT unnest($1::uuid[]) AS id, unnest($2::bytea[]) AS state) u
                 WHERE cj.id = u.id AND cj.status = 'available'
                 RETURNING cj.id`,
                    [updates.map((update) => update.id), updates.map((update) => update.state)]
                )
                for (const row of updated.rows) {
                    written.add(row.id)
                }
            }
            for (const update of updates) {
                outcomes.set(update.id, written.has(update.id) ? 'delivered' : 'job_missing')
            }
        }
        await client.query('COMMIT')
    } catch (err) {
        await client.query('ROLLBACK').catch(() => {})
        throw err
    } finally {
        client.release()
    }
    for (const outcome of outcomes.values()) {
        counterStepResume.labels({ outcome }).inc()
    }
    return outcomes
}
