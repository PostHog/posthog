/**
 * An expected request failure: the backend said no (4xx/5xx), the network was unavailable,
 * or the response body was unusable. These are normal outcomes of talking to the API from
 * a customer's page - they must never be reported to error tracking.
 *
 * `toolbarApi` itself never throws (it returns a `ToolbarApiResult` union). Logics that
 * need a kea `*Failure` action to fire (to drive UI state or a toast) convert a failed
 * result into a throw - that throw must be a `ToolbarRequestError`, so the global kea
 * loader handler (see `index.tsx`) can log it without capturing an exception. Throwing a
 * plain `Error` from a loader is reserved for genuine bugs, which SHOULD be captured.
 */
export class ToolbarRequestError extends Error {
    /** HTTP status of the failed response, or 0 for a network-level failure. */
    status: number

    constructor(message: string, status: number = 0) {
        super(message)
        this.name = 'ToolbarRequestError'
        this.status = status
    }
}
