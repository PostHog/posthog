import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { IngestedEventInfo } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { UsageKeyResolver } from '~/ingestion/common/usage-records/billable-events'
import { BeforeBatchStep } from '~/ingestion/framework/batching-pipeline'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

export interface EventUsageBatchContext {
    eventUsageBatch: UsageRecordBatch
}

export function createEventUsageBeforeBatchStep<TInput, CInput, CBatch>(
    createBatch: () => UsageRecordBatch
): BeforeBatchStep<TInput, CInput, CBatch, CBatch & EventUsageBatchContext> {
    return function eventUsageBeforeBatchStep(input) {
        return Promise.resolve(
            ok({
                elements: input.elements,
                batchContext: { ...input.batchContext, eventUsageBatch: createBatch() },
            })
        )
    }
}

export interface RecordEventUsageInput {
    preparedEvent: { teamId: number; event: string; eventUuid: string; distinctId: string; timestamp: string }
    eventUsageBatch: UsageRecordBatch
    processPerson?: boolean
}

/**
 * Mirrors the events table's dedup identity, `(team_id, toDate(timestamp), event,
 * distinct_id, uuid)`, minus the team the billing sorting key already carries. The UUID alone
 * is not that identity: two events sharing one but differing in day, name or distinct_id are
 * separate rows there, and the nightly report counts them separately, so billing must too.
 *
 * The timestamp is UTC-normalized upstream, so its first ten characters are the same day
 * `toDate` resolves.
 */
function analyticsRecordId(preparedEvent: RecordEventUsageInput['preparedEvent']): string {
    const day = preparedEvent.timestamp.slice(0, 10)
    return `${day}:${preparedEvent.event}:${preparedEvent.distinctId}:${preparedEvent.eventUuid}`
}

export interface EventUsageRecord {
    teamId: number
    usageKey: string
    recordId: string
}

export interface EventUsageRecordContext {
    eventUsageRecords?: EventUsageRecord[]
}

/**
 * One record per event. Its identity travels inside the event, so a replay reproduces it
 * whatever the consumer's batching, which an offset-derived identity cannot.
 *
 * Person processing bills a second record under its own usage key. It shares the identity,
 * which the usage key separates, and it waits on the same acknowledgement: an event that
 * never lands should not bill for the person work either.
 */
export function createRecordEventUsageStep<T extends RecordEventUsageInput>(
    resolveUsageKey: UsageKeyResolver
): ProcessingStep<T, T & EventUsageRecordContext> {
    return function recordEventUsageStep(input: T): Promise<PipelineResult<T & EventUsageRecordContext>> {
        const usageKey = resolveUsageKey(input.preparedEvent.event)
        if (!usageKey) {
            return Promise.resolve(ok({ ...input, eventUsageRecords: undefined }))
        }
        const { teamId } = input.preparedEvent
        const recordId = analyticsRecordId(input.preparedEvent)
        const eventUsageRecords: EventUsageRecord[] = [{ teamId, usageKey, recordId }]
        if (input.processPerson) {
            eventUsageRecords.push({ teamId, usageKey: 'enhanced_person_events', recordId })
        }
        return Promise.resolve(ok({ ...input, eventUsageRecords }))
    }
}

export interface RecordEventUsageAfterIngestInput extends EventUsageRecordContext {
    eventUsageBatch?: UsageRecordBatch
    ingested: Promise<IngestedEventInfo | null>[]
}

/** Queues billing only once every Kafka write for the logical event has been acknowledged. */
export function createRecordEventUsageAfterIngestStep<T extends RecordEventUsageAfterIngestInput>(): ProcessingStep<
    T,
    T
> {
    return function recordEventUsageAfterIngestStep(input: T): Promise<PipelineResult<T>> {
        if (input.eventUsageBatch) {
            for (const record of input.eventUsageRecords ?? []) {
                input.eventUsageBatch.addAfterAcknowledgements(
                    input.ingested,
                    record.teamId,
                    record.usageKey,
                    record.recordId
                )
            }
        }
        return Promise.resolve(ok(input))
    }
}

export function createFlushEventUsageStep<T extends { batchContext: EventUsageBatchContext }>(): ProcessingStep<T, T> {
    return function flushEventUsageStep(input: T): Promise<PipelineResult<T>> {
        return Promise.resolve(ok(input, [input.batchContext.eventUsageBatch.flush()]))
    }
}
