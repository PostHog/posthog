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
            const recordId = analyticsRecordId(input.preparedEvent)
            input.eventUsageBatch.add(input.preparedEvent.teamId, usageKey, recordId)
            if (input.processPerson) {
                input.eventUsageBatch.add(input.preparedEvent.teamId, 'enhanced_person_events', recordId)
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
