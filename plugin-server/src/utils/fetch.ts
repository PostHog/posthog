import { LookupAddress } from 'dns'
import dns from 'dns/promises'
import http from 'http'
import https from 'https'
import * as ipaddr from 'ipaddr.js'
import net from 'node:net'
import fetch, { type RequestInfo, type RequestInit, type Response, FetchError, Request } from 'node-fetch'
import { URL } from 'url'

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
    const octets = ip.octets
    return !(
        (
            octets[0] === 0 || // "This network" (0.0.0.0/8)
            ip.range() !== 'unicast' || // Non-unicast addresses
            octets[0] === 127 || // Loopback (127.0.0.0/8)
            (octets[0] === 169 && octets[1] === 254) || // Link-local (169.254.0.0/16)
            (octets[0] === 255 && octets[1] === 255 && octets[2] === 255 && octets[3] === 255)
        ) // Broadcast
    )
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
        // We don't support IPv6 for now, just like the Rust version
        if (parsed.kind() === 'ipv6') {
            continue
        }
        // Check if the IPv4 address is global
        if (!isGlobalIPv4(parsed as ipaddr.IPv4)) {
            throw new FetchError('Internal hostname', 'posthog-host-guard')
        }
    }
    if (addrinfo.length === 0) {
        throw new FetchError(`Unable to resolve ${hostname}`, 'posthog-host-guard')
    }

    return addrinfo[0]
}

const httpStaticLookup: net.LookupFunction = async (hostname, options, cb) => {
    console.log('httpStaticLookup', hostname)
    try {
        const addrinfo = await staticLookupAsync(hostname)
        cb(null, addrinfo.address, addrinfo.family)
    } catch (err) {
        cb(err as Error, '', 4)
    }
}

export class SecureFetch {
    allowUnsafe: boolean

    constructor(options?: { allowUnsafe?: boolean }) {
        this.allowUnsafe = options?.allowUnsafe ?? (process.env.NODE_ENV === 'functional-tests' || !isProdEnv())
    }

    fetch(url: RequestInfo, init?: RequestInit): Promise<Response> {
        return runInstrumentedFunction({
            statsKey: 'secureFetch',
            func: async () => {
                const request = new Request(url, init)

                if (this.allowUnsafe) {
                    return await fetch(url, init)
                }

                validateUrl(request.url)
                return await fetch(url, {
                    ...init,
                    agent: ({ protocol }: URL) =>
                        protocol === 'http:'
                            ? new http.Agent({ lookup: httpStaticLookup })
                            : new https.Agent({ lookup: httpStaticLookup }),
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
