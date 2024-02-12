// This module wraps node-fetch with a sentry tracing-aware extension

import { LookupAddress } from 'dns'
import dns from 'dns/promises'
import * as ipaddr from 'ipaddr.js'
import fetch, { type RequestInfo, type RequestInit, type Response, FetchError, Request } from 'node-fetch'
import { URL } from 'url'

import { runInSpan } from '../sentry'
import { isProdEnv } from './env-utils'

export async function trackedFetch(url: RequestInfo, init?: RequestInit): Promise<Response> {
    const request = new Request(url, init)
    return await runInSpan(
        {
            op: 'fetch',
            description: `${request.method} ${request.url}`,
        },
        async () => {
            if (isProdEnv() && !process.env.NODE_ENV?.includes('functional-tests')) {
                await raiseIfUserProvidedUrlUnsafe(request.url)
            }
            return await fetch(url, init)
        }
    )
}

trackedFetch.isRedirect = fetch.isRedirect
trackedFetch.FetchError = FetchError

/**
 * Raise if the provided URL seems unsafe, otherwise do nothing.
 *
 * Equivalent of Django raise_if_user_provided_url_unsafe.
 */
export async function raiseIfUserProvidedUrlUnsafe(url: string): Promise<void> {
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
    let addrinfo: LookupAddress[]
    try {
        addrinfo = await dns.lookup(parsedUrl.hostname, { all: true })
    } catch (err) {
        throw new FetchError('Invalid hostname', 'posthog-host-guard')
    }
    for (const { address } of addrinfo) {
        // Prevent addressing internal services
        if (ipaddr.parse(address).range() !== 'unicast') {
            throw new FetchError('Internal hostname', 'posthog-host-guard')
        }
    }
}
