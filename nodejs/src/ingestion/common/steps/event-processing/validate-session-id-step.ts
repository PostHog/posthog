import { UUID } from '~/common/utils/utils'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'

export interface ValidateSessionIdInput {
    normalizedEvent: PluginEvent
}

// Cap the offending value stored in the warning details so a bloated $session_id
// can't blow up the warning payload.
const MAX_SESSION_ID_DETAIL_LENGTH = 200

/**
 * Emits an `invalid_session_id` warning when `$session_id` is present but isn't a
 * valid UUID. Such events still ingest, but their session id is dropped from
 * session analytics (the v3 sessions table only keeps UUIDv7 ids, and the
 * `$session_id_uuid` materialized column is NULL for anything non-UUID), so
 * without this warning the exclusion is invisible to the customer.
 *
 * The event is never modified or dropped here — this is a visibility signal only.
 * Runs after `normalizeEvent`, which lowercases valid-UUID session ids and leaves
 * everything else untouched, so the same UUID check as `normalizeSessionId` applies.
 */
export function createValidateSessionIdStep<T extends ValidateSessionIdInput>(): ProcessingStep<T, T> {
    return function validateSessionIdStep(input: T): Promise<PipelineResult<T>> {
        const { normalizedEvent } = input
        const sessionId = normalizedEvent.properties?.$session_id

        if (sessionId === undefined || sessionId === null || UUID.validateString(sessionId, false)) {
            return Promise.resolve(ok(input))
        }

        const warning: PipelineWarning = {
            type: 'invalid_session_id',
            details: {
                eventUuid: normalizedEvent.uuid,
                distinctId: normalizedEvent.distinct_id,
                sessionId: String(sessionId).slice(0, MAX_SESSION_ID_DETAIL_LENGTH),
            },
        }

        return Promise.resolve(ok(input, [], [warning]))
    }
}
