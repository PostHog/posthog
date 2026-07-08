import { normalizeSessionId } from '~/common/utils/utils'
import { dlq, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders } from '~/types'

import { SessionReplayHeaders } from './pipeline-types'

export interface ValidateSessionReplayHeadersStepInput {
    headers: EventHeaders
}

/**
 * Validates that a session replay message carries the headers capture guarantees, and replaces the
 * wide header object with the narrowed {@link SessionReplayHeaders} so downstream steps can trust them.
 *
 * Capture's recordings handler rejects a snapshot before it reaches Kafka unless it has a token, a
 * valid `session_id`, and a `distinct_id` (see `rust/capture/src/events/recordings.rs`), so their
 * absence here indicates a bug upstream rather than bad user input — such messages are sent to the DLQ.
 */
export function createValidateSessionReplayHeadersStep<
    T extends ValidateSessionReplayHeadersStepInput,
>(): ProcessingStep<T, Omit<T, 'headers'> & { headers: SessionReplayHeaders }> {
    return async function validateReplayHeadersStep(input) {
        const { token, session_id, distinct_id } = input.headers

        if (!token) {
            return dlq('no_token_in_header')
        }
        if (!session_id) {
            return dlq('no_session_id_in_header')
        }
        if (!distinct_id) {
            return dlq('no_distinct_id_in_header')
        }

        return Promise.resolve(
            ok({ ...input, headers: { token, session_id: normalizeSessionId(session_id), distinct_id } })
        )
    }
}
