import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import type { CyclotronJobInvocation, CyclotronJobQueueKind } from '../../types'
import type { CyclotronV2DequeuedJob, CyclotronV2JobInit } from './types'

/**
 * State blob stored in the single `state` BYTEA column.
 * Mirrors the Kafka serialization: everything in one JSON object.
 */
export type SerializedJobState = {
    state: CyclotronJobInvocation['state']
    queueParameters?: CyclotronJobInvocation['queueParameters']
    queueMetadata?: CyclotronJobInvocation['queueMetadata']
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

export function decodeJobState(row: Pick<CyclotronV2DequeuedJob, 'id' | 'state'>): SerializedJobState {
    if (!row.state) {
        return { state: null }
    }
    try {
        return parseJSON(row.state.toString('utf-8'))
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
>

export function v2JobToInvocation(job: JobRow): CyclotronJobInvocation {
    const parsed = decodeJobState(job)

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
    }

    if (job.parentRunId) {
        invocation.parentRunId = job.parentRunId
    }

    if (job.cancelRequestedAt) {
        invocation.cancelRequestedAt = job.cancelRequestedAt
    }

    return invocation
}
