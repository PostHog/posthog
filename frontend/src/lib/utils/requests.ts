/** We issue a cancel request, when the request is aborted or times out (frontend side), since in these cases the backend query might still be running. */
export function shouldCancelQuery(error: any): boolean {
    return isAbortedRequest(error) || isTimedOutRequest(error)
}

export function isAbortedRequest(error: any): boolean {
    return error?.name === 'AbortError' || error?.message?.name === 'AbortError'
}

export function isTimedOutRequest(error: any): boolean {
    return error?.status === 504
}
