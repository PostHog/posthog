// This module wraps node-fetch with a sentry tracing-aware extension

import fetch, { Request, RequestInfo, RequestInit, Response } from 'node-fetch'

import { runInSpan } from '../sentry'

function fetchWrapper(url: RequestInfo, init?: RequestInit): Promise<Response> {
    const request = new Request(url, init)
    return runInSpan(
        {
            op: 'fetch',
            description: `${request.method} ${request.hostname}`,
        },
        () => fetch(url, init)
    )
}

fetchWrapper.isRedirect = fetch.isRedirect

export default fetchWrapper
