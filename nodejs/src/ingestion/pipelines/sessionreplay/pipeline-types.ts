/** Types carried across the session replay pipeline steps (step-to-step data contracts). */
import { Message } from 'node-rdkafka'

import { SessionKey } from './shared/types'

/** The per-message context threaded through every stage of the session replay pipeline. */
export interface MessageContext {
    message: Message
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
 * The gate's verdict for a session. `allowed` proceeds to key resolution; `blocked` (rate-limited) is
 * carried through key resolution untouched. Both are marked seen at the mark-seen step, and blocked ones
 * are dropped only after — so a rate-limited session isn't re-counted against its team's new-session
 * budget on the next batch, while it never reaches recording (block and seen share a TTL, so it stays
 * blocked for as long as it's seen).
 */
export type Gated<T> = (T & { status: 'allowed' }) | (T & { status: 'blocked' })

/**
 * A {@link Gated} element after key resolution. `allowed` now carries its key; `blocked` and `deleted`
 * (key crypto-shredded) carry no key. Blocked and deleted are dropped after the mark-seen step — marking
 * them seen keeps them from being re-counted against the budget on later batches, and neither reaches
 * recording (a deleted session's tombstone outlives its seen flag, so while it's seen it always resolves
 * as deleted).
 */
export type Resolved<T> = Recordable<T> | (T & { status: 'blocked' }) | (T & { status: 'deleted' })

/**
 * The one branch of {@link Resolved} that reaches recording: an `allowed` session carrying its resolved
 * key. This is what the mark-seen step emits after dropping the blocked and deleted sessions.
 */
export type Recordable<T> = T & { status: 'allowed'; sessionKey: SessionKey }
