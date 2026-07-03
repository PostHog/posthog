/** Types shared across the record-phase session replay pipeline steps. */

/** Tags an element with whether its session is being seen for the first time in this batch. */
export interface NewSessionFlag {
    isNewSession: boolean
}
