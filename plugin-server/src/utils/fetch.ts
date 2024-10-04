// This module wraps node-fetch with a sentry tracing-aware extension

import { LookupAddress } from 'dns'
import dns from 'dns/promises'
import http from 'http'
import https from 'https'
import * as ipaddr from 'ipaddr.js'
import net from 'node:net'
import fetch, { type RequestInfo, type RequestInit, type Response, FetchError, Request } from 'node-fetch'
import { URL } from 'url'

import { runInSpan } from '../sentry'
import { isProdEnv } from './env-utils'

const staticLookup: net.LookupFunction = async (hostname, options, cb) => {
    let addrinfo: LookupAddress[]
    try {
        addrinfo = await dns.lookup(hostname, { all: true })
    } catch (err) {
        cb(new Error('Invalid hostname'), '', 4)
        return
    }
    for (const { address } of addrinfo) {
        // Prevent addressing internal services
        if (ipaddr.parse(address).range() !== 'unicast') {
            cb(new Error('Internal hostname'), '', 4)
            return
        }
    }
    if (addrinfo.length === 0) {
        cb(new Error(`Unable to resolve ${hostname}`), '', 4)
        return
    }
    cb(null, addrinfo[0].address, addrinfo[0].family)
}

export async function trackedFetch(url: RequestInfo, init?: RequestInit): Promise<Response> {
    const request = new Request(url, init)
    return await runInSpan(
        {
            op: 'fetch',
            description: `${request.method} ${request.url}`,
        },
        async () => {
            const options = { ...init }
            if (isProdEnv() && !process.env.NODE_ENV?.includes('functional-tests')) {
                await raiseIfUserProvidedUrlUnsafe(request.url)
                options.agent = ({ protocol }: URL) =>
                    protocol === 'http:'
                        ? new http.Agent({ lookup: staticLookup })
                        : new https.Agent({ lookup: staticLookup })
            }
            return await fetch(url, options)
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
