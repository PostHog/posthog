import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
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
}

/**
 * One record per event, identified by the event UUID. The UUID travels with the
 * event, so a replay reproduces the identity whatever the consumer's batching,
 * which an offset-derived identity cannot.
 */
export function createRecordEventUsageStep<T extends RecordEventUsageInput>(
    resolveUsageKey: UsageKeyResolver
): ProcessingStep<T, T> {
    return function recordEventUsageStep(input: T): Promise<PipelineResult<T>> {
        const usageKey = resolveUsageKey(input.preparedEvent.event)
        if (usageKey) {
            input.eventUsageBatch.add(input.preparedEvent.teamId, usageKey, input.preparedEvent.eventUuid)
        }
        return Promise.resolve(ok(input))
    }
}

export function createFlushEventUsageStep<T extends { batchContext: EventUsageBatchContext }>(): ProcessingStep<T, T> {
    return function flushEventUsageStep(input: T): Promise<PipelineResult<T>> {
        return Promise.resolve(ok(input, [input.batchContext.eventUsageBatch.flush()]))
    }
}
