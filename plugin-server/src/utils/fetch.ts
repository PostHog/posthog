// This module wraps node-fetch with a sentry tracing-aware extension

import fetch, { Request, Response } from 'node-fetch'

import { runInSpan } from '../sentry'

function fetchWrapper(...args: Parameters<typeof fetch>): Promise<Response> {
    const request = new Request(...args)
    return runInSpan(
        {
            op: 'fetch',
            description: `${request.method} ${request.hostname}`,
        },
        () => fetch(...args)
    )
}

fetchWrapper.isRedirect = fetch.isRedirect

export default fetchWrapper
