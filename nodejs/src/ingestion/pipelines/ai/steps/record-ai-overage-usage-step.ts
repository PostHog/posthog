import { AI_INCLUDED_BYTES_PER_EVENT } from '~/ingestion/common/ai-event-limits'
import { RecordedEventUsage } from '~/ingestion/common/steps/usage-records-steps'
import { AI_EVENTS_USAGE_KEY, AI_OVERAGE_BYTES_USAGE_KEY } from '~/ingestion/common/usage-records/billable-events'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

type RecordAiOverageUsageInput = RecordedEventUsage & {
    eventBytes: number
}

// The size is in the record ID because `ai_events` keeps every copy of an event: a resend with other
// content bills its own overage, while an identical retry collapses into one record.
export function createRecordAiOverageUsageStep<TInput extends RecordAiOverageUsageInput>(): ProcessingStep<
    TInput,
    TInput
> {
    return function recordAiOverageUsageStep(input) {
        const overageBytes = input.eventBytes - AI_INCLUDED_BYTES_PER_EVENT
        const eventRecord = input.eventUsageRecords?.find((record) => record.usageKey === AI_EVENTS_USAGE_KEY)
        if (overageBytes <= 0 || !eventRecord) {
            return Promise.resolve(ok(input))
        }
        return Promise.resolve(
            ok({
                ...input,
                eventUsageRecords: [
                    ...(input.eventUsageRecords ?? []),
                    {
                        teamId: eventRecord.teamId,
                        usageKey: AI_OVERAGE_BYTES_USAGE_KEY,
                        recordId: `${eventRecord.recordId}:${input.eventBytes}`,
                        quantity: overageBytes,
                        unit: 'bytes',
                        timestampMs: eventRecord.timestampMs,
                    },
                ],
            })
        )
    }
}
