/** Types carried across the session replay pipeline steps (step-to-step data contracts). */

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
