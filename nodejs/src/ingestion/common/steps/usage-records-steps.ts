import { Message } from 'node-rdkafka'

import { UsageKeyResolver } from '~/ingestion/common/usage-records/billable-events'
import { EventUsageBatch } from '~/ingestion/common/usage-records/event-usage-batch'
import { BeforeBatchStep } from '~/ingestion/framework/batching-pipeline'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

export interface EventUsageBatchContext {
    eventUsageBatch: EventUsageBatch
}

export function createEventUsageBeforeBatchStep<TInput, CInput, CBatch>(
    createBatch: () => EventUsageBatch
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
    preparedEvent: { teamId: number; event: string }
    message: Message
    eventUsageBatch: EventUsageBatch
}

export function createRecordEventUsageStep<T extends RecordEventUsageInput>(
    resolveUsageKey: UsageKeyResolver
): ProcessingStep<T, T> {
    return function recordEventUsageStep(input: T): Promise<PipelineResult<T>> {
        const usageKey = resolveUsageKey(input.preparedEvent.event)
        if (usageKey) {
            input.eventUsageBatch.increment(input.preparedEvent.teamId, usageKey, input.message, 1)
        }
        return Promise.resolve(ok(input))
    }
}

export function createFlushEventUsageStep<T extends { batchContext: EventUsageBatchContext }>(): ProcessingStep<T, T> {
    return function flushEventUsageStep(input: T): Promise<PipelineResult<T>> {
        return Promise.resolve(ok(input, [input.batchContext.eventUsageBatch.flush()]))
    }
}
