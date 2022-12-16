// This module wraps node-fetch with a sentry tracing-aware extension

import fetch, { FetchError, Request, Response } from 'node-fetch'

import { runInSpan } from '../sentry'

function fetchWrapper(...args: Parameters<typeof fetch>): Promise<Response> {
    const request = new Request(...args)
    return runInSpan(
        {
            op: 'fetch',
            description: `${request.method} ${request.url}`,
        },
        () => fetch(...args)
    )
}

fetchWrapper.isRedirect = fetch.isRedirect
fetchWrapper.FetchError = FetchError

export default fetchWrapper
