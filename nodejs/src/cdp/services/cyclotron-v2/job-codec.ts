import { get, omit, set } from 'lodash'

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
    stateUnreadable?: true
}

export type StateOpener = Pick<EncryptedFields, 'tryDecrypt'>
export type StateSealer = Pick<EncryptedFields, 'encrypt'>

const SEALED_PATHS = [
    ['state', 'variables'],
    ['state', 'send'],
    ['state', 'globals'],
    ['state', 'vmState'],
    ['state', 'event', 'properties'],
    ['state', 'currentAction', 'hogFunctionState'],
    ['queueParameters'],
]

/** Moves the content fields of an invocation into a `sealed` token, and leaves the invocation in memory unchanged. */
export function sealInvocation(invocation: CyclotronJobInvocation, sealer: StateSealer): CyclotronJobInvocation {
    const fields = SEALED_PATHS.filter((path) => get(invocation, path) !== undefined).map(
        (path): [string[], unknown] => [path, get(invocation, path)]
    )
    if (!fields.length) {
        return invocation
    }
    const content: SealedContent = { teamId: invocation.teamId, id: invocation.id, fields }
    return {
        // lodash reads each element of one array argument as a deep path, which its types do not express.
        ...omit(invocation, SEALED_PATHS as unknown as string[]),
        sealed: sealer.encrypt(JSON.stringify(content)),
    } as CyclotronJobInvocation
}

/**
 * The plaintext of a `sealed` token. Each field is a path from the top of the stored object, such as
 * ['state', 'variables'], so a reader opens fields that a newer writer seals without knowing them in advance.
 */
type SealedContent = { teamId: number; id: string; fields: [string[], unknown][] }

type Sealable = { state: Record<string, any> | null; sealed?: string; stateUnreadable?: true }

/**
 * Puts the fields of a `sealed` token back into the state. A token that no key opens, or one that was sealed for
 * another team or job, leaves only the plaintext fields and marks the state unreadable, so the worker fails the run
 * and records it, and never runs it without its content.
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
        if (
            content?.teamId === job.teamId &&
            content.id === job.id &&
            content.fields.every(([path]) => path[0] === 'state' || path[0] === 'queueParameters')
        ) {
            for (const [path, value] of content.fields) {
                set(opened, path, value)
            }
            return opened as T
        }
    } catch {
        // A reader with no keys throws, and so does content that is not a list of fields.
    }
    logger.error('Could not open sealed V2 job state', { jobId: job.id, teamId: job.teamId })
    return { ...opened, stateUnreadable: true } as T
}

function serializeState(invocation: CyclotronJobInvocation): Buffer {
    const blob: SerializedJobState = {
        state: invocation.state,
        queueParameters: invocation.queueParameters ?? undefined,
        queueMetadata: invocation.queueMetadata ?? undefined,
        sealed: invocation.sealed,
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

    if (parsed.stateUnreadable) {
        invocation.stateUnreadable = true
    }

    return invocation
}
