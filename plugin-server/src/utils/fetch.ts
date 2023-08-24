// This module wraps node-fetch with a sentry tracing-aware extension

import { LookupAddress } from 'dns'
import dns from 'dns/promises'
import * as ipaddr from 'ipaddr.js'
import fetch, { FetchError, Request, Response } from 'node-fetch'
import { URL } from 'url'

import { runInSpan } from '../sentry'
import { isProdEnv } from './env-utils'

export function filteredFetch(...args: Parameters<typeof fetch>): Promise<Response> {
    const request = new Request(...args)
    return runInSpan(
        {
            op: 'fetch',
            description: `${request.method} ${request.url}`,
        },
        async () => {
            if (isProdEnv()) {
                // TODO: Only run this check on Cloud
                await raiseIfUserProvidedUrlUnsafe(request.url)
            }
            return await fetch(...args)
        }
    )
}

filteredFetch.isRedirect = fetch.isRedirect
filteredFetch.FetchError = FetchError

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
    let port: URL['port']
    if (parsedUrl.protocol === 'http:') {
        port = '80'
    } else if (parsedUrl.protocol === 'https:') {
        port = '443'
    } else {
        throw new FetchError('Protocol must be either HTTP or HTTPS', 'posthog-host-guard')
    }
    if (parsedUrl.port.length > 0 && parsedUrl.port !== port) {
        throw new FetchError('Port does not match protocol', 'posthog-host-guard')
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
            throw new FetchError('Invalid hostname', 'posthog-host-guard')
        }
    }
}
