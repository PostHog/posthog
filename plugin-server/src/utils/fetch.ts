import { LookupAddress } from 'dns'
import dns from 'dns/promises'
import http from 'http'
import https from 'https'
import * as ipaddr from 'ipaddr.js'
import net from 'node:net'
import fetch, { type RequestInfo, type RequestInit, type Response, FetchError, Request } from 'node-fetch'
import { URL } from 'url'

import { defaultConfig } from '../config/config'
import { runInstrumentedFunction } from '../main/utils'
import { isProdEnv } from './env-utils'

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

function isGlobalIPv4(ip: ipaddr.IPv4): boolean {
    const [a, b, c, d] = ip.octets
    if (a === 0) {
        return false // "This network" (0.0.0.0/8)
    }
    if (ip.range() !== 'unicast') {
        return false // Non-unicast addresses
    }
    if (a === 127) {
        return false // Loopback (127.0.0.0/8)
    }
    if (a === 169 && b === 254) {
        return false // Link-local (169.254.0.0/16)
    }
    if (a === 255 && b === 255 && c === 255 && d === 255) {
        return false // Broadcast
    }
    return true
}

function isIPv4(addr: ipaddr.IPv4 | ipaddr.IPv6): addr is ipaddr.IPv4 {
    return addr.kind() === 'ipv4'
}

async function staticLookupAsync(hostname: string): Promise<LookupAddress> {
    let addrinfo: LookupAddress[]
    try {
        addrinfo = await dns.lookup(hostname, { all: true })
    } catch (err) {
        throw new FetchError('Invalid hostname', 'posthog-host-guard')
    }
    for (const { address } of addrinfo) {
        const parsed = ipaddr.parse(address)
        // We don't support IPv6 for now
        if (!isIPv4(parsed)) {
            continue
        }
        // Check if the IPv4 address is global
        if (!isGlobalIPv4(parsed)) {
            throw new FetchError('Internal hostname', 'posthog-host-guard')
        }
    }
    if (addrinfo.length === 0) {
        throw new FetchError(`Unable to resolve ${hostname}`, 'posthog-host-guard')
    }

    return addrinfo[0]
}

const httpStaticLookup: net.LookupFunction = async (hostname, options, cb) => {
    try {
        const addrinfo = await staticLookupAsync(hostname)
        cb(null, addrinfo.address, addrinfo.family)
    } catch (err) {
        cb(err as Error, '', 4)
    }
}

const COMMON_AGENT_OPTIONS: http.AgentOptions = { keepAlive: false }

const getSafeAgent = (url: URL) => {
    return url.protocol === 'http:'
        ? new http.Agent({ ...COMMON_AGENT_OPTIONS, lookup: httpStaticLookup })
        : new https.Agent({ ...COMMON_AGENT_OPTIONS, lookup: httpStaticLookup })
}

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

export const trackedFetch = (url: RequestInfo, init?: RequestInit): Promise<Response> => {
    return defaultSecureFetch.fetch(url, init)
}

/**
 * Legacy function used by parts of the codebase. Generally speaking this should be replaced with secureFetch.
 */
export async function raiseIfUserProvidedUrlUnsafe(url: string): Promise<void> {
    const parsedUrl = validateUrl(url)
    await staticLookupAsync(parsedUrl.hostname)
}
