import { LookupAddress } from 'dns'
import dns from 'dns/promises'
import * as ipaddr from 'ipaddr.js'
import net from 'node:net'
import { Counter } from 'prom-client'
import { Agent, errors, fetch as undiciFetch, RequestInfo, RequestInit, Response } from 'undici'
import { URL } from 'url'

import { isProdEnv } from './env-utils'

export { Response } from 'undici'

const unsafeRequestCounter = new Counter({
    name: 'node_request_unsafe',
    help: 'Total number of unsafe requests detected and blocked',
    labelNames: ['reason'],
})

export class SecureRequestError extends errors.UndiciError {
    constructor(message: string) {
        super(message)
        this.name = 'SecureRequestError'
    }
}

export class InvalidRequestError extends errors.UndiciError {
    constructor(message: string) {
        super(message)
        this.name = 'InvalidRequestError'
    }
}

export class ResolutionError extends errors.UndiciError {
    constructor(message: string) {
        super(message)
        this.name = 'ResolutionError'
    }
}

function validateUrl(url: string): URL {
    // Raise if the provided URL seems unsafe, otherwise do nothing.
    let parsedUrl: URL
    try {
        parsedUrl = new URL(url)
    } catch (err) {
        throw new InvalidRequestError('Invalid URL')
    }
    const { hostname, protocol } = parsedUrl
    if (!hostname) {
        throw new InvalidRequestError('No hostname')
    }
    if (!['http:', 'https:'].includes(protocol)) {
        throw new InvalidRequestError('Scheme must be either HTTP or HTTPS')
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
        throw new ResolutionError('Invalid hostname')
    }
    for (const { address } of addrinfo) {
        const parsed = ipaddr.parse(address)
        // We don't support IPv6 for now
        if (!isIPv4(parsed)) {
            continue
        }

        // TRICKY: We need this for tests and local dev
        const allowUnsafe = process.env.NODE_ENV?.includes('functional-tests') || !isProdEnv()

        // Check if the IPv4 address is global
        if (!allowUnsafe && !isGlobalIPv4(parsed)) {
            unsafeRequestCounter.inc({ reason: 'internal_hostname' })
            throw new SecureRequestError('Internal hostname')
        }
    }
    if (addrinfo.length === 0) {
        unsafeRequestCounter.inc({ reason: 'unable_to_resolve' })
        throw new ResolutionError(`Unable to resolve ${hostname}`)
    }

    return addrinfo[0]
}

export const httpStaticLookup: net.LookupFunction = async (hostname, _options, cb) => {
    try {
        const addrinfo = await staticLookupAsync(hostname)
        cb(null, addrinfo.address, addrinfo.family)
    } catch (err) {
        cb(err as Error, '', 4)
    }
}

/**
 * Legacy function used by parts of the codebase. Generally speaking this should be replaced with secureFetch.
 */
export async function raiseIfUserProvidedUrlUnsafe(url: string): Promise<void> {
    const parsedUrl = validateUrl(url)
    await staticLookupAsync(parsedUrl.hostname)
}

class SecureAgent extends Agent {
    constructor() {
        super({
            keepAliveTimeout: 10_000,
            connections: 500,
            connect: {
                lookup: httpStaticLookup,
            },
        })
    }
}

const sharedSecureAgent = new SecureAgent()

export async function legacyFetch(input: RequestInfo, options?: RequestInit): Promise<Response> {
    let parsed: URL
    try {
        parsed = typeof input === 'string' ? new URL(input) : input instanceof URL ? input : new URL(input.url)
    } catch {
        throw new Error('Invalid URL')
    }

    if (!parsed.hostname || !(parsed.protocol === 'http:' || parsed.protocol === 'https:')) {
        throw new Error('URL must have HTTP or HTTPS protocol and a valid hostname')
    }

    // options.timeoutMs = options.timeoutMs ?? defaultConfig.EXTERNAL_REQUEST_TIMEOUT_MS

    const requestOptions = options ?? {}
    requestOptions.dispatcher = sharedSecureAgent

    return undiciFetch(parsed.toString(), requestOptions)
}
