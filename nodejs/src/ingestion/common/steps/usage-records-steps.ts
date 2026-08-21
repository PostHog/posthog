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
    preparedEvent: { teamId: number; event: string; eventUuid: string }
    eventUsageBatch: UsageRecordBatch
    processPerson?: boolean
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
 * One record per event, identified by the event UUID. The UUID travels with the
 * event, so a replay reproduces the identity whatever the consumer's batching,
 * which an offset-derived identity cannot.
 */
export function createRecordEventUsageStep<T extends RecordEventUsageInput>(
    resolveUsageKey: UsageKeyResolver
): ProcessingStep<T, T & EventUsageRecordContext> {
    return function recordEventUsageStep(input: T): Promise<PipelineResult<T & EventUsageRecordContext>> {
        const usageKey = resolveUsageKey(input.preparedEvent.event)
        const eventUsageRecords: EventUsageRecord[] = []
        if (usageKey) {
            eventUsageRecords.push({
                teamId: input.preparedEvent.teamId,
                usageKey,
                recordId: `${usageKey}:${input.preparedEvent.eventUuid}`,
            })
            if (input.processPerson) {
                eventUsageRecords.push({
                    teamId: input.preparedEvent.teamId,
                    usageKey: 'enhanced_person_events',
                    recordId: `enhanced_person_events:${input.preparedEvent.eventUuid}`,
                })
            }
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
