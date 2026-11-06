/** We issue a cancel request, when the request is aborted or times out (frontend side), since in these cases the backend query might still be running. */
export function shouldCancelQuery(error: any): boolean {
    return isAbortedRequest(error) || isTimedOutRequest(error)
}

export function isAbortedRequest(error: any): boolean {
    return error.name === 'AbortError' || error.message?.name === 'AbortError'
}

export function isTimedOutRequest(error: any): boolean {
    return error.status === 504
}

/**
 * A 4xx (except 408 timeout and 429 rate limit) means the request is deterministically bad, so
 * retrying it can't succeed and only delays the error reaching the user. Used to short-circuit
 * retry loops so a broken query isn't hammered several times before failing.
 */
export function isDeterministicClientError(error: any): boolean {
    const status = error?.status
    return typeof status === 'number' && status >= 400 && status < 500 && status !== 408 && status !== 429
}
