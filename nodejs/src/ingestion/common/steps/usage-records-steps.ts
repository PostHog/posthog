import { createHash } from 'node:crypto'

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
}

/**
 * Mirrors the events table's dedup identity, `(team_id, toDate(timestamp), event,
 * distinct_id, uuid)`, minus the team the billing sorting key already carries. The UUID alone
 * is not that identity: two events sharing one but differing in day, name or distinct_id are
 * separate rows there, and the nightly report counts them separately, so billing must too.
 *
 * Hashed rather than joined, because event names and distinct IDs are client-supplied and
 * together exceed the 512-byte identifier the service accepts. One oversized record makes the
 * service reject the whole request, which would drop every record batched with it.
 *
 * The timestamp is UTC-normalized upstream, so its first ten characters are the same day
 * `toDate` resolves.
 */
function analyticsRecordId(preparedEvent: RecordEventUsageInput['preparedEvent']): string {
    const day = preparedEvent.timestamp.slice(0, 10)
    // JSON rather than a separator: an event name and a distinct ID can both contain any
    // character, so `a\nb` with `c` and `a` with `b\nc` would hash the same and bill once.
    const identity = JSON.stringify([preparedEvent.event, preparedEvent.distinctId, preparedEvent.eventUuid])
    return `${day}:${createHash('sha256').update(identity).digest('hex').slice(0, 32)}`
}

export interface EventUsageRecord {
    teamId: number
    usageKey: string
    recordId: string
}

export interface EventUsageRecordContext {
    eventUsageRecord?: EventUsageRecord
}

/**
 * One record per event. Its identity travels inside the event, so a replay reproduces it
 * whatever the consumer's batching, which an offset-derived identity cannot.
 *
 * TODO: decide how usage records should treat events dated in the past. This step bills every
 * billable event at the moment it is processed, including a historical migration. The nightly
 * report does not: `get_teams_with_billable_event_count_in_period` filters the events table on
 * the event's own `timestamp`, so an event backdated outside the current period lands in a
 * period that has already been billed and is charged for nowhere. The two systems therefore
 * disagree on exactly the imports customers run deliberately, and the choice — bill regardless
 * of event age, or mirror the report and skip old events — is a pricing decision rather than an
 * implementation one. `historicalMigration` is available upstream in the pipeline if we pick
 * the second.
 */
export function createRecordEventUsageStep<T extends RecordEventUsageInput>(
    resolveUsageKey: UsageKeyResolver
): ProcessingStep<T, T & EventUsageRecordContext> {
    return function recordEventUsageStep(input: T): Promise<PipelineResult<T & EventUsageRecordContext>> {
        const usageKey = input.eventUsageBatch.accepts(input.preparedEvent.teamId)
            ? resolveUsageKey(input.preparedEvent.event)
            : undefined
        const eventUsageRecord = usageKey
            ? { teamId: input.preparedEvent.teamId, usageKey, recordId: analyticsRecordId(input.preparedEvent) }
            : undefined
        return Promise.resolve(ok({ ...input, eventUsageRecord }))
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
        const record = input.eventUsageRecord
        if (record && input.eventUsageBatch) {
            input.eventUsageBatch.addAfterAcknowledgements(
                input.ingested,
                record.teamId,
                record.usageKey,
                record.recordId
            )
        }
        return Promise.resolve(ok(input))
    }
}

/** Ends the batch's usage reporting: the batch object goes away after this, so it drains. */
export function createFlushEventUsageStep<T extends { batchContext: EventUsageBatchContext }>(): ProcessingStep<T, T> {
    return function flushEventUsageStep(input: T): Promise<PipelineResult<T>> {
        return Promise.resolve(ok(input, [input.batchContext.eventUsageBatch.drain()]))
    }
}
