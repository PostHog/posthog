import http from 'http'
import https from 'https'
import fetch, { type RequestInfo, type RequestInit, type Response, FetchError, Request } from 'node-fetch'
import { URL } from 'url'

import { defaultConfig } from '../config/config'
import { runInstrumentedFunction } from '../main/utils'
import { isProdEnv } from './env-utils'
import { httpStaticLookup } from './request'

export type { Response }

function validateUrl(url: string): URL {
    // Raise if the provided URL seems unsafe, otherwise do nothing.
    let parsedUrl: URL
    try {
        parsedUrl = new URL(url)
    } catch (err) {
        throw new FetchError('Invalid URL', 'posthog-host-guard')
    }
    if (!parsedUrl.hostname) {
        throw new FetchError('No hostname', 'posthog-host-guard')
    }
    if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
        throw new FetchError('Scheme must be either HTTP or HTTPS', 'posthog-host-guard')
    }
    return parsedUrl
}

const COMMON_AGENT_OPTIONS: http.AgentOptions = { keepAlive: false }

const getSafeAgent = (url: URL) => {
    return url.protocol === 'http:'
        ? new http.Agent({ ...COMMON_AGENT_OPTIONS, lookup: httpStaticLookup })
        : new https.Agent({ ...COMMON_AGENT_OPTIONS, lookup: httpStaticLookup })
}

// @deprecated Use the fetch function from request.ts instead
export class SecureFetch {
    constructor(private options?: { allowUnsafe?: boolean }) {}

    fetch(url: RequestInfo, init: RequestInit = {}): Promise<Response> {
        return runInstrumentedFunction({
            statsKey: 'secureFetch',
            func: async () => {
                init.timeout = init.timeout ?? defaultConfig.EXTERNAL_REQUEST_TIMEOUT_MS
                const request = new Request(url, init)

                const allowUnsafe =
                    this.options?.allowUnsafe ?? (process.env.NODE_ENV?.includes('functional-tests') || !isProdEnv())

                if (allowUnsafe) {
                    // NOTE: Agent is false to disable keep alive, and increase parallelization
                    return await fetch(url, { ...init, agent: false })
                }

                validateUrl(request.url)
                return await fetch(url, {
                    ...init,
                    agent: getSafeAgent,
                })
            },
        })
    }
}

const defaultSecureFetch = new SecureFetch()

// @deprecated Use the fetch function from request.ts instead
export const trackedFetch = (url: RequestInfo, init?: RequestInit): Promise<Response> => {
    return defaultSecureFetch.fetch(url, init)
}
