import { LookupAddress } from 'dns'
import dns from 'dns/promises'
import * as ipaddr from 'ipaddr.js'
import net from 'node:net'
import { Counter, Gauge } from 'prom-client'
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

import { getExternalRequestConfig } from '../common/config'
import { isProdEnv } from './env-utils'
import { parseJSON } from './json-parse'

const requestConfig = getExternalRequestConfig()

// eslint-disable-next-line no-restricted-imports
export { Response } from 'undici'

const unsafeRequestCounter = new Counter({
    name: 'node_request_unsafe',
    help: 'Total number of unsafe requests detected and blocked',
    labelNames: ['reason'],
})

// Gauge tracking the number of external HTTP requests currently in flight.
// This is the primary scaling signal for the cdp-cyclotron-worker: it directly
// measures I/O saturation rather than CPU (which stays low while waiting on responses)
// or batch utilization (which measures demand, not capacity).
const inflightExternalRequests = new Gauge({
    name: 'cdp_http_inflight_requests',
    help: 'Number of currently inflight external HTTP requests (undici). Use as HPA scaling metric for cdp-cyclotron-worker.',
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
    } catch {
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
    } catch {
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
            keepAliveTimeout: Number(requestConfig.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS),
            connections: requestConfig.EXTERNAL_REQUEST_CONNECTIONS,
            connect: {
                lookup: httpStaticLookup,
                timeout: requestConfig.EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS,
            },
        })
    }
}

// Safe way to use the same helpers for talking to internal endpoints such as other services
class InsecureAgent extends Agent {
    constructor() {
        super({
            keepAliveTimeout: requestConfig.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS,
            connections: requestConfig.EXTERNAL_REQUEST_CONNECTIONS,
            connect: {
                timeout: requestConfig.EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS,
            },
        })
    }
}

// When a proxy URL is available, external requests go through a CONNECT tunnel.
// The proxy handles SSRF blocking (private IP rejection) at the network level,
// so we skip the DNS lookup (httpStaticLookup) which would be redundant.
function makeSecureDispatcher(): Dispatcher {
    const proxyUrl =
        process.env.HTTPS_PROXY || process.env.HTTP_PROXY || process.env.https_proxy || process.env.http_proxy

    if (proxyUrl) {
        return new ProxyAgent({
            uri: proxyUrl,
            keepAliveTimeout: requestConfig.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS,
            connections: requestConfig.EXTERNAL_REQUEST_CONNECTIONS,
            requestTls: {},
        })
    }
    return new SecureAgent()
}

const sharedSecureAgent = makeSecureDispatcher()
const sharedInsecureAgent = new InsecureAgent()

/**
 * Reads a response body stream and destroys it immediately after to release
 * the underlying socket and its off-heap buffers. Without explicit destruction,
 * undici holds onto these buffers until GC, and V8 never returns the ~64MB
 * ArrayBuffer arenas they live in to the OS.
 */
async function readAndDestroyBody(body: Dispatcher.ResponseData['body']): Promise<string> {
    const text = await body.text()
    // After text() fully consumes the stream, destroy to release socket buffers.
    // At this point the stream is already ended so destroy is a cleanup no-op,
    // but it signals undici to release the underlying socket immediately.
    try {
        body.destroy()
    } catch {
        // Ignore destroy errors — the body is already fully consumed
    }
    return text
}

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

    options.timeoutMs = options.timeoutMs ?? requestConfig.EXTERNAL_REQUEST_TIMEOUT_MS

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

    // On first .text()/.json() call, read the full body and destroy the
    // stream immediately after. This releases undici's socket buffers
    // without waiting for GC.
    let bodyPromise: Promise<string> | undefined

    const readBody = (): Promise<string> => {
        if (!bodyPromise) {
            bodyPromise = readAndDestroyBody(result.body)
        }
        return bodyPromise
    }

    return {
        status: result.statusCode,
        headers,
        json: async () => parseJSON(await readBody()),
        text: async () => await readBody(),
        dump: () => {
            if (!bodyPromise) {
                bodyPromise = Promise.resolve('')
                try {
                    result.body.on('error', () => {})
                    result.body.destroy()
                } catch {
                    // Ignore destroy errors
                }
            }
            return Promise.resolve()
        },
    }
}

export async function internalFetch(url: string, options: FetchOptions = {}): Promise<FetchResponse> {
    return await _fetch(url, options, sharedInsecureAgent)
}

export async function fetch(url: string, options: FetchOptions = {}): Promise<FetchResponse> {
    const parsed = new URL(url)
    validateHostnameIPLiteral(parsed.hostname, !isProdEnv())
    inflightExternalRequests.inc()
    try {
        return await _fetch(url, options, sharedSecureAgent)
    } finally {
        inflightExternalRequests.dec()
    }
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
    requestOptions.signal = AbortSignal.timeout(requestConfig.EXTERNAL_REQUEST_TIMEOUT_MS)

    return undiciFetch(parsed.toString(), requestOptions)
}
