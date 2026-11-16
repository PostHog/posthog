import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import type { CyclotronJobInvocation, CyclotronJobQueueKind } from '../../types'
import type { EncryptedFields } from '../../utils/encryption-utils'
import type { CyclotronV2DequeuedJob, CyclotronV2JobInit } from './types'

/**
 * State blob stored in the single `state` BYTEA column.
 * Mirrors the Kafka serialization: everything in one JSON object.
 */
export type SerializedJobState = {
    state: CyclotronJobInvocation['state']
    queueParameters?: CyclotronJobInvocation['queueParameters']
    queueMetadata?: CyclotronJobInvocation['queueMetadata']
    sealed?: string
}

export type StateOpener = Pick<EncryptedFields, 'tryDecrypt'>

/**
 * The plaintext of a `sealed` token. Each field is a path from the top of the stored object, such as
 * ['state', 'variables'], so a reader opens fields that a newer writer seals without knowing them in advance.
 */
type SealedContent = { teamId: number; id: string; fields: [string[], unknown][] }

type Sealable = { state: Record<string, any> | null; sealed?: string }

/**
 * Puts the fields of a sensitive run's `sealed` token back into its state. A token that no key opens, or one
 * that was sealed for another team or job, gives a null state, so the run fails as corrupt state does and
 * never runs without its content.
 */
export function openSealedState<T extends Sealable>(
    stored: T,
    job: { id: string; teamId: number },
    opener: StateOpener
): T {
    const { sealed, ...opened } = stored
    if (sealed === undefined) {
        return stored
    }
    try {
        const decrypted = opener.tryDecrypt(sealed)
        const content: SealedContent | undefined = decrypted.ok ? parseJSON(decrypted.value) : undefined
        if (content?.teamId === job.teamId && content.id === job.id) {
            for (const [path, value] of content.fields) {
                let target: Record<string, any> = opened
                for (const key of path.slice(0, -1)) {
                    target = target[key] ??= {}
                }
                target[path[path.length - 1]] = value
            }
            return opened as T
        }
    } catch {
        // A reader with no keys throws, and so does content that is not a list of fields.
    }
    logger.error('Could not open sealed V2 job state', { jobId: job.id, teamId: job.teamId })
    return { ...opened, state: null } as T
}

function serializeState(invocation: CyclotronJobInvocation): Buffer {
    const blob: SerializedJobState = {
        state: invocation.state,
        queueParameters: invocation.queueParameters ?? undefined,
        queueMetadata: invocation.queueMetadata ?? undefined,
    }
    return Buffer.from(JSON.stringify(blob))
}

export type EncodedStateColumns = {
    state: Buffer
    distinctId: string | null
    personId: string | null
    actionId: string | null
}

export function encodeStateColumns(invocation: CyclotronJobInvocation): EncodedStateColumns {
    return {
        state: serializeState(invocation),
        distinctId: extractDistinctId(invocation),
        personId: extractPersonId(invocation),
        actionId: extractActionId(invocation),
    }
}

export function encodeJob(invocation: CyclotronJobInvocation): CyclotronV2JobInit {
    return {
        id: invocation.id,
        teamId: invocation.teamId,
        functionId: invocation.functionId,
        queueName: invocation.queue,
        priority: invocation.queuePriority,
        scheduled: invocation.queueScheduledAt?.toJSDate() ?? new Date(),
        parentRunId: invocation.parentRunId ?? null,
        ...encodeStateColumns(invocation),
    }
}

type LookupColumnSource = {
    person?: { id?: string }
    state?: {
        event?: { distinct_id?: string }
        personId?: string
        currentAction?: { id?: string }
    } | null
}

export function extractDistinctId(invocation: CyclotronJobInvocation): string | null {
    return (invocation as LookupColumnSource).state?.event?.distinct_id || null
}

export function extractPersonId(invocation: CyclotronJobInvocation): string | null {
    const inv = invocation as LookupColumnSource
    return inv.person?.id || inv.state?.personId || null
}

export function extractActionId(invocation: CyclotronJobInvocation): string | null {
    return (invocation as LookupColumnSource).state?.currentAction?.id || null
}

export function decodeJobState(
    row: Pick<CyclotronV2DequeuedJob, 'id' | 'teamId' | 'state'>,
    opener?: StateOpener
): SerializedJobState {
    if (!row.state) {
        return { state: null }
    }
    try {
        const stored: SerializedJobState = parseJSON(row.state.toString('utf-8'))
        return opener ? openSealedState(stored, row, opener) : stored
    } catch (e) {
        logger.error('Error parsing V2 job state', { error: String(e), jobId: row.id })
        return { state: null }
    }
}

export function withReschedule(
    state: Buffer | null,
    scheduledAt: string,
    now: Date
): { state: Buffer; rescheduledAt: Date } {
    const blob: SerializedJobState = state ? parseJSON(state.toString('utf-8')) : { state: null }
    const previous = Date.parse(blob.state?.statusAt ?? '')
    const rescheduledAt = new Date(Number.isNaN(previous) ? now.getTime() : Math.max(now.getTime(), previous + 1))
    return {
        state: Buffer.from(
            JSON.stringify({
                ...blob,
                state: { ...blob.state, scheduledAt, statusAt: rescheduledAt.toISOString() },
            })
        ),
        rescheduledAt,
    }
}

export type JobRow = Pick<
    CyclotronV2DequeuedJob,
    | 'id'
    | 'teamId'
    | 'functionId'
    | 'queueName'
    | 'priority'
    | 'scheduled'
    | 'created'
    | 'parentRunId'
    | 'state'
    | 'cancelRequestedAt'
> &
    Partial<Pick<CyclotronV2DequeuedJob, 'lockId'>>

/** Without an opener the invocation holds only the plaintext fields, which is enough for a reader that does not run the job. */
export function v2JobToInvocation(job: JobRow, opener?: StateOpener): CyclotronJobInvocation {
    const parsed = decodeJobState(job, opener)

    const invocation: CyclotronJobInvocation = {
        id: job.id,
        teamId: job.teamId,
        functionId: job.functionId ?? '',
        queue: job.queueName as CyclotronJobQueueKind,
        queuePriority: job.priority,
        queueScheduledAt: job.scheduled ?? undefined,
        queueCreatedAt: job.created,
        queueDueAt: job.scheduled ?? undefined,
        queueMetadata: parsed.queueMetadata ?? undefined,
        queueParameters: parsed.queueParameters ?? undefined,
        state: parsed.state,
        queueSource: 'postgres-v2',
        queueLockId: job.lockId,
    }

    if (job.parentRunId) {
        invocation.parentRunId = job.parentRunId
    }

    if (job.cancelRequestedAt) {
        invocation.cancelRequestedAt = job.cancelRequestedAt
    }

    return invocation
}
