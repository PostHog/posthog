import { Duration } from 'luxon'
import { Pool } from 'pg'
import { Counter } from 'prom-client'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { buildWorkflowStepDispatchKey } from '../../utils/workflow-step-dispatch-key'

export const WorkflowStepResumeSchema = z.object({
    origin_key: z.string().min(1),
    status: z.enum(['completed', 'failed', 'cancelled']),
    result: z.record(z.string(), z.unknown()).optional().nullable(),
})

export const AWAITED_STEP_MAX_WAIT = Duration.fromObject({ hours: 24 })

export type StepResume = z.infer<typeof WorkflowStepResumeSchema> & { jobId: string; actionId: string }

// `job_<status>` covers every non-parked cyclotron status; `delivered` is the only success.
export type StepResumeOutcome = 'delivered' | 'stale_key' | 'not_parked' | 'expired' | 'job_missing' | `job_${string}`

type StepResumeRejection = 'stale_key' | 'not_parked' | 'expired'

type ResumableJobState = {
    actionStepCount?: number
    rerunAttempts?: number
    currentAction?: {
        id: string
        awaitingResume?: { key: string; deadlineAt: string }
        resumeResult?: { key: string }
    }
}

export const isRetryableStepResumeOutcome = (outcome: StepResumeOutcome): boolean =>
    outcome === 'job_running' || outcome === 'not_parked'

export const counterStepResume = new Counter({
    name: 'cdp_hogflow_step_resume',
    help: 'Workflow step resumes by outcome.',
    labelNames: ['outcome'],
})

export function applyStepResumeToState(stateBuffer: Buffer, resume: StepResume): Buffer | StepResumeRejection {
    try {
        const parsed = parseJSON(stateBuffer.toString('utf-8'))
        const rejection = stepResumeRejection(parsed.state, resume)
        if (rejection) {
            return rejection
        }
        parsed.state = {
            ...parsed.state,
            currentAction: {
                ...parsed.state.currentAction,
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
        return 'stale_key'
    }
}

function stepResumeRejection(state: ResumableJobState | undefined, resume: StepResume): StepResumeRejection | null {
    const currentAction = state?.currentAction
    if (!state || currentAction?.id !== resume.actionId) {
        return 'stale_key'
    }
    const awaiting = currentAction.awaitingResume
    if (!awaiting) {
        return isCurrentVisit(state, resume) ? 'not_parked' : 'stale_key'
    }
    const replyAlreadyTaken = currentAction.resumeResult?.key === resume.origin_key
    if (awaiting.key !== resume.origin_key || replyAlreadyTaken) {
        return 'stale_key'
    }
    if (Date.parse(awaiting.deadlineAt) <= Date.now()) {
        return 'expired'
    }
    return null
}

function isCurrentVisit(state: ResumableJobState, resume: StepResume): boolean {
    return (
        typeof state.actionStepCount === 'number' &&
        buildWorkflowStepDispatchKey(resume.jobId, resume.actionId, state.actionStepCount, state.rerunAttempts) ===
            resume.origin_key
    )
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
        const rows = await client.query(
            `SELECT id, status, state FROM cyclotron_jobs WHERE id = ANY($1::uuid[])${
                teamId === undefined ? '' : ' AND team_id = $2'
            } ORDER BY id FOR UPDATE`,
            teamId === undefined ? [[...byJob.keys()]] : [[...byJob.keys()], teamId]
        )
        const updates: { id: string; state: Buffer }[] = []
        for (const row of rows.rows) {
            const jobResumes = byJob.get(row.id)!
            byJob.delete(row.id)
            // A job that is not parked yet cannot take the wake: the worker owns `state` while it
            // runs, so its flush would drop the write. The caller decides whether to retry.
            if (row.status !== 'available') {
                outcomes.set(row.id, `job_${row.status}`)
                continue
            }
            const applied = row.state ? applyFirstStepResume(row.state, jobResumes) : 'stale_key'
            if (!Buffer.isBuffer(applied)) {
                outcomes.set(row.id, applied)
                continue
            }
            updates.push({ id: row.id, state: applied })
        }
        for (const jobId of byJob.keys()) {
            outcomes.set(jobId, 'job_missing')
        }
        if (updates.length > 0) {
            const updated = await client.query(
                `UPDATE cyclotron_jobs cj
                 SET scheduled = NOW(), state = u.state
                 FROM (SELECT unnest($1::uuid[]) AS id, unnest($2::bytea[]) AS state) u
                 WHERE cj.id = u.id AND cj.status = 'available'
                 RETURNING cj.id`,
                [updates.map((update) => update.id), updates.map((update) => update.state)]
            )
            const written = new Set(updated.rows.map((row) => row.id))
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

// One batch can carry a stale wake from an earlier visit next to the current one.
function applyFirstStepResume(state: Buffer, resumes: StepResume[]): Buffer | StepResumeRejection {
    const rejections: StepResumeRejection[] = []
    for (const resume of resumes) {
        const applied = applyStepResumeToState(state, resume)
        if (Buffer.isBuffer(applied)) {
            return applied
        }
        rejections.push(applied)
    }
    return rejections.find((rejection) => rejection !== 'stale_key') ?? 'stale_key'
}
