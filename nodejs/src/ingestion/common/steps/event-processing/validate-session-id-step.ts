import { UUID } from '~/common/utils/utils'
import { IngestionWarningType } from '~/ingestion/common/ingestion-warnings'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'

export type ValidateSessionIdStepInput = {
    normalizedEvent: PluginEvent
}

// Cap the offending value stored in the warning so a bloated $session_id can't blow up the payload.
const MAX_SESSION_ID_DETAIL_LENGTH = 200

const INVALID_EVENT_SESSION_ID: IngestionWarningType = 'invalid_event_session_id'

// `$session_id` is arbitrary, caller-controlled JSON, so the offending value can be an object whose
// primitive coercion throws (e.g. `{ toString: null }`, or a throwing `valueOf`/`toJSON`). Coerce it
// defensively: this only feeds the warning's diagnostic `details`, and a crash here would re-throw up
// the pipeline and poison the partition (Kafka redelivers the same event forever).
function describeSessionId(sessionId: unknown): string {
    try {
        return String(sessionId).slice(0, MAX_SESSION_ID_DETAIL_LENGTH)
    } catch {
        return '[unserializable $session_id]'
    }
}

/**
 * Emits an `invalid_event_session_id` warning when `$session_id` is present but isn't a valid UUID.
 *
 * Such events still ingest, but their session id is dropped from session analytics: the v3 sessions
 * table and the `$session_id_uuid` materialized column keep only valid-UUID ids — the same
 * `UUID.validateString` check `normalizeSessionId` applies — so without this warning the exclusion is
 * invisible to the customer. Distinct from the capture-produced replay `invalid_session_id`, which
 * rejects the recording outright; here the analytics event is kept and only its session id is unusable.
 *
 * Runs after `normalizeEvent`, which lowercases valid-UUID session ids and leaves everything else
 * untouched, so the same check that governs normalization decides the warning.
 */
export function createValidateSessionIdStep<TInput extends ValidateSessionIdStepInput>(): ProcessingStep<
    TInput,
    TInput
> {
    return function validateSessionIdStep(input: TInput) {
        const warnings: PipelineWarning[] = []
        const sessionId = input.normalizedEvent.properties?.['$session_id']

        if (sessionId != null && !UUID.validateString(sessionId, false)) {
            warnings.push({
                type: INVALID_EVENT_SESSION_ID,
                details: {
                    eventUuid: input.normalizedEvent.uuid,
                    sessionId: describeSessionId(sessionId),
                },
            })
        }

        return Promise.resolve(ok(input, [], warnings))
    }
}
