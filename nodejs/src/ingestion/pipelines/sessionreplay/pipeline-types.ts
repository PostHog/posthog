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
 * The gate's verdict for a session, carried through key resolution to the mark-seen step. A blocked
 * (rate-limited) session rides through key resolution untouched and is dropped only after being marked
 * seen — so it isn't re-counted against its team's new-session budget on the next batch, while it never
 * reaches recording (block and seen share a TTL, so it stays blocked for as long as it's seen).
 */
export type Gated<T> = (T & { blocked: false }) | (T & { blocked: true })

/** A {@link Gated} element after key resolution: allowed sessions now carry their key, blocked ones don't. */
export type Resolved<T> = (T & { blocked: false; sessionKey: SessionKey }) | (T & { blocked: true })
