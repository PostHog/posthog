import { LookupAddress } from 'dns'
import dns from 'dns/promises'
import * as ipaddr from 'ipaddr.js'
import net from 'node:net'
import { Counter } from 'prom-client'
// eslint-disable-next-line no-restricted-imports
import {
    Agent,
    Dispatcher,
    type HeadersInit,
    ProxyAgent,
    RequestInfo,
    RequestInit,
    Response,
    errors,
    request,
    fetch as undiciFetch,
} from 'undici'
import { URL } from 'url'

import { defaultConfig } from '../config/config'
import { isProdEnv } from './env-utils'
import { parseJSON } from './json-parse'

// eslint-disable-next-line no-restricted-imports
export { Response } from 'undici'

const unsafeRequestCounter = new Counter({
    name: 'node_request_unsafe',
    help: 'Total number of unsafe requests detected and blocked',
    labelNames: ['reason'],
})

// NOTE: This isn't exactly fetch - it's meant to be very close but limited to only options we actually want to expose
export type FetchOptions = {
    method?: string
    headers?: HeadersInit
    body?: string | Buffer
    timeoutMs?: number
}

export type FetchResponse = {
    status: number
    headers: Record<string, string>
    json: () => Promise<any>
    text: () => Promise<string>
    dump: () => Promise<void>
}

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

/**
 * Validate IP literal hostnames directly. Undici skips the DNS lookup callback
 * for IP literals (both IPv4 and IPv6), so staticLookupAsync never runs for them.
 * We must check these before passing the URL to undici.
 */
function validateHostnameIPLiteral(hostname: string, allowUnsafe: boolean): void {
    if (allowUnsafe) {
        return
    }

    // Strip brackets from IPv6 literals — URL.hostname includes them for IPv6
    const bare = hostname.startsWith('[') && hostname.endsWith(']') ? hostname.slice(1, -1) : hostname

    let parsed: ipaddr.IPv4 | ipaddr.IPv6
    try {
        parsed = ipaddr.parse(bare)
    } catch {
        // Not an IP literal (it's a regular hostname) — DNS lookup will handle validation
        return
    }

    let ipv4: ipaddr.IPv4 | null = null
    if (isIPv4(parsed)) {
        ipv4 = parsed
    } else if (parsed.isIPv4MappedAddress()) {
        ipv4 = parsed.toIPv4Address()
    } else {
        if (!isGlobalIPv6(parsed)) {
            unsafeRequestCounter.inc({ reason: 'internal_ip_literal' })
            throw new SecureRequestError('Hostname is not allowed')
        }
        return
    }

    if (!isGlobalIPv4(ipv4)) {
        unsafeRequestCounter.inc({ reason: 'internal_ip_literal' })
        throw new SecureRequestError('Hostname is not allowed')
    }
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

function isGlobalIPv6(ip: ipaddr.IPv6): boolean {
    const range = ip.range()
    // Only allow globally routable unicast IPv6 addresses
    return range === 'unicast'
}

function isIPv4(addr: ipaddr.IPv4 | ipaddr.IPv6): addr is ipaddr.IPv4 {
    return addr.kind().toLowerCase() === 'ipv4'
}

async function staticLookupAsync(hostname: string): Promise<LookupAddress[]> {
    let addrinfo: LookupAddress[]
    const validAddrinfo: LookupAddress[] = []
    try {
        addrinfo = await dns.lookup(hostname, { all: true })
    } catch (err) {
        throw new ResolutionError('Invalid hostname')
    }
    for (const addrInfo of addrinfo) {
        const parsed = ipaddr.parse(addrInfo.address)

        let ipv4: ipaddr.IPv4 | null = null
        if (isIPv4(parsed)) {
            ipv4 = parsed
        } else if (parsed.isIPv4MappedAddress()) {
            // IPv6-mapped IPv4 (e.g. ::ffff:169.254.169.254) must be unwrapped and validated
            ipv4 = parsed.toIPv4Address()
        } else {
            // Pure IPv6 — validate directly
            const allowUnsafe = !isProdEnv()
            if (!allowUnsafe && !isGlobalIPv6(parsed)) {
                unsafeRequestCounter.inc({ reason: 'internal_hostname' })
                throw new SecureRequestError('Hostname is not allowed')
            }
            validAddrinfo.push(addrInfo)
            continue
        }

        // TRICKY: We need this for tests and local dev
        const allowUnsafe = !isProdEnv()

        // Check if the IPv4 address is global
        if (!allowUnsafe && !isGlobalIPv4(ipv4)) {
            unsafeRequestCounter.inc({ reason: 'internal_hostname' })
            throw new SecureRequestError('Hostname is not allowed')
        }
        validAddrinfo.push(addrInfo)
    }
    if (validAddrinfo.length === 0) {
        unsafeRequestCounter.inc({ reason: 'unable_to_resolve' })
        throw new ResolutionError(`Unable to resolve ${hostname}`)
    }

    return validAddrinfo
}

export const httpStaticLookup: net.LookupFunction = async (hostname, _options, cb) => {
    try {
        const addrinfo = await staticLookupAsync(hostname)
        cb(null, addrinfo)
    } catch (err) {
        cb(err as Error, '', 4)
    }
}

/**
 * Legacy function used by parts of the codebase. Generally speaking this should be replaced with secureFetch.
 */
export async function raiseIfUserProvidedUrlUnsafe(url: string): Promise<void> {
    const parsedUrl = validateUrl(url)
    validateHostnameIPLiteral(parsedUrl.hostname, !isProdEnv())
    await staticLookupAsync(parsedUrl.hostname)
}

class SecureAgent extends Agent {
    constructor() {
        super({
            keepAliveTimeout: defaultConfig.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS,
            connections: defaultConfig.EXTERNAL_REQUEST_CONNECTIONS,
            connect: {
                lookup: httpStaticLookup,
                timeout: defaultConfig.EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS,
            },
        })
    }
}

// Safe way to use the same helpers for talking to internal endpoints such as other services
class InsecureAgent extends Agent {
    constructor() {
        super({
            keepAliveTimeout: defaultConfig.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS,
            connections: defaultConfig.EXTERNAL_REQUEST_CONNECTIONS,
            connect: {
                timeout: defaultConfig.EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS,
            },
        })
    }
}

// When the outbound proxy is enabled, external requests go through a CONNECT tunnel.
// The proxy handles SSRF blocking (private IP rejection) at the network level,
// so we skip the DNS lookup (httpStaticLookup) which would be redundant.
function makeSecureDispatcher(): Dispatcher {
    if (defaultConfig.OUTBOUND_PROXY_ENABLED && defaultConfig.OUTBOUND_PROXY_URL) {
        return new ProxyAgent({
            uri: defaultConfig.OUTBOUND_PROXY_URL,
            keepAliveTimeout: defaultConfig.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS,
            connections: defaultConfig.EXTERNAL_REQUEST_CONNECTIONS,
            requestTls: {},
        })
    }
    return new SecureAgent()
}

const sharedSecureAgent = makeSecureDispatcher()
const sharedInsecureAgent = new InsecureAgent()

export async function _fetch(url: string, options: FetchOptions = {}, dispatcher: Dispatcher): Promise<FetchResponse> {
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        throw new Error('Invalid URL')
    }

    if (!parsed.hostname || !(parsed.protocol === 'http:' || parsed.protocol === 'https:')) {
        throw new Error('URL must have HTTP or HTTPS protocol and a valid hostname')
    }

    options.timeoutMs = options.timeoutMs ?? defaultConfig.EXTERNAL_REQUEST_TIMEOUT_MS

    const result = await request(parsed.toString(), {
        method: options.method ?? 'GET',
        headers: options.headers,
        body: options.body,
        dispatcher,
        maxRedirections: 0, // No redirects allowed by default
        signal: options.timeoutMs ? AbortSignal.timeout(options.timeoutMs) : undefined,
    })

    const headers: Record<string, string> = {}
    for (const [key, value] of Object.entries(result.headers)) {
        const singleValue = Array.isArray(value) ? value[0] : value
        if (singleValue) {
            headers[key] = singleValue
        }
    }

    let consumed = false

    const returnValue = {
        status: result.statusCode,
        headers,
        json: async () => {
            consumed = true
            return parseJSON(await result.body.text())
        },
        text: async () => {
            consumed = true
            return await result.body.text()
        },
        dump: async () => {
            if (consumed) {
                return
            }
            consumed = true
            await result.body.dump()
        },
    }
    return returnValue
}

export async function internalFetch(url: string, options: FetchOptions = {}): Promise<FetchResponse> {
    return await _fetch(url, options, sharedInsecureAgent)
}

export async function fetch(url: string, options: FetchOptions = {}): Promise<FetchResponse> {
    const parsed = new URL(url)
    validateHostnameIPLiteral(parsed.hostname, !isProdEnv())
    return await _fetch(url, options, sharedSecureAgent)
}

// Legacy fetch implementation that exposes the entire fetch implementation
export function legacyFetch(input: RequestInfo, options?: RequestInit): Promise<Response> {
    let parsed: URL
    try {
        parsed = typeof input === 'string' ? new URL(input) : input instanceof URL ? input : new URL(input.url)
    } catch {
        throw new Error('Invalid URL')
    }

    if (!parsed.hostname || !(parsed.protocol === 'http:' || parsed.protocol === 'https:')) {
        throw new Error('URL must have HTTP or HTTPS protocol and a valid hostname')
    }

    validateHostnameIPLiteral(parsed.hostname, !isProdEnv())

    const requestOptions = options ?? {}
    requestOptions.dispatcher = sharedSecureAgent
    requestOptions.signal = AbortSignal.timeout(defaultConfig.EXTERNAL_REQUEST_TIMEOUT_MS)

    return undiciFetch(parsed.toString(), requestOptions)
}
