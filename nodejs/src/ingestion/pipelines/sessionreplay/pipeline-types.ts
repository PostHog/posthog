/** Types carried across the session replay pipeline steps (step-to-step data contracts). */
import { Message } from 'node-rdkafka'

import { ParsedMessageData } from './kafka/types'
import { SessionRef } from './sessions/session-batch-recorder'
import { ExtractedConsoleLogs } from './sessions/session-console-log-recorder'
import { SerializedSessionData } from './sessions/snappy-session-recorder'
import { SessionKey } from './shared/types'

/** The per-message context threaded through every stage of the session replay pipeline. */
export interface MessageContext {
    message: Message
}

/**
 * What the inner pipeline emits per message: everything the cycle reducer needs to aggregate it —
 * the session it belongs to (retention and key resolved along the way) plus the serialized session
 * data and console logs derived by the serialize step. `parsedMessage` still rides along for
 * feature extraction, which is sequential across a session's messages and can't be precomputed.
 */
export interface SessionReplayPipelineOutput {
    session: SessionRef
    data: SerializedSessionData
    logs: ExtractedConsoleLogs
    parsedMessage: ParsedMessageData
}

/**
 * The message headers a session replay message is guaranteed to carry and that the pipeline consumes.
 * These are exactly the fields capture sets for the replay path (see `rust/capture/src/events/recordings.rs`),
 * narrowed to their required, non-optional form — downstream steps take this instead of the wide,
 * all-optional `EventHeaders` so they can read them without re-checking. `session_id` is normalized in
 * the validate step so every downstream step (retention keys, batch lookup, parse) keys on the same
 * canonical form the record path uses.
 */
export interface SessionReplayHeaders {
    token: string
    session_id: string
    distinct_id: string
}

/** Tags an element with whether its session is being seen for the first time in this batch. */
export interface NewSessionFlag {
    isNewSession: boolean
}

/**
 * The gate's verdict for a session that survives rate limiting: `allowed`, on its way to key resolution.
 * Blocked (rate-limited) sessions are dropped at the gate itself, so they never flow downstream — a
 * blocked session is kept out of its team's new-session budget by its block key, not by riding the
 * pipeline to be marked seen, so the seen flag stays reserved for sessions that actually hold a key.
 */
export type Allowed<T> = T & { status: 'allowed' }

/**
 * An {@link Allowed} element after key resolution. `allowed` now carries its key; `deleted` (key
 * crypto-shredded) carries none. A `deleted` session is dropped at the mark-seen step but IS marked seen
 * first — safe because its keystore tombstone outlives the seen flag, so while seen it always resolves as
 * deleted, never cleartext — which also keeps it out of the budget without re-counting.
 */
export type Resolved<T> = Recordable<T> | (T & { status: 'deleted' })

/**
 * The one branch of {@link Resolved} that reaches recording: an `allowed` session carrying its resolved
 * key. This is what the mark-seen step emits after dropping the deleted sessions.
 */
export type Recordable<T> = Allowed<T> & { sessionKey: SessionKey }
