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

// When `fetch()` fails at the network level (no response ever arrives) it rejects with a `TypeError`
// whose message varies by browser. These are interrupted requests (tab backgrounding, flaky mobile
// networks, ad blockers, DNS hiccups), not application bugs, so they're noise in error tracking rather
// than real defects. WebKit's "Load failed" is the Safari equivalent of Chromium's "Failed to fetch".
const NETWORK_ERROR_MESSAGES = [
    'Failed to fetch', // Chromium
    'Load failed', // WebKit / Safari
    'NetworkError when attempting to fetch resource', // Firefox
    'The network connection was lost', // WebKit
    'The Internet connection appears to be offline', // WebKit
    'A server with the specified hostname could not be found', // WebKit
]

export function isNetworkError(error: any): boolean {
    return error instanceof TypeError && NETWORK_ERROR_MESSAGES.some((message) => error.message?.includes(message))
}
