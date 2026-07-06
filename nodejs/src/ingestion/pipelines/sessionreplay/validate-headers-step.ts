import { normalizeSessionId } from '~/common/utils/utils'
import { dlq, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders } from '~/types'

/**
 * The message headers a session replay message is guaranteed to carry and that the pipeline consumes.
 * These are exactly the fields capture sets for the replay path (see `rust/capture/src/events/recordings.rs`),
 * narrowed to their required, non-optional form — downstream steps take this instead of the wide,
 * all-optional {@link EventHeaders} so they can read them without re-checking. `session_id` is
 * normalized here so every downstream step (retention keys, batch lookup, parse) keys on the same
 * canonical form the record path uses.
 */
export interface SessionReplayHeaders {
    token: string
    session_id: string
    distinct_id: string
}

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
