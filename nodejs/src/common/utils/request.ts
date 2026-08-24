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
    request,
    fetch as undiciFetch,
} from 'undici'
import { URL } from 'url'

import { getExternalRequestConfig } from '~/common/config'

import { isProdEnv } from './env-utils'
import { fetchAttribution } from './fetch-attribution'
import { parseJSON } from './json-parse'
import { logger } from './logger'

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
    allowH2?: boolean
}

export type FetchResponse = {
    status: number
    headers: Record<string, string>
    json: () => Promise<any>
    text: () => Promise<string>
    dump: () => Promise<void>
}

// These extend Error, not undici's UndiciError: UndiciError defines a code-based Symbol.hasInstance, so every
// UndiciError subclass matches `instanceof` against every other one, which would defeat isFetchResponseRetriable.
export class SecureRequestError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'SecureRequestError'
    }
}

export class InvalidRequestError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'InvalidRequestError'
    }
}

export class ResolutionError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ResolutionError'
    }
}

// Logged only when a check blocks the request. The check runs inside undici's connect flow
// where the thrown error can't carry caller context, so attribution comes from the ALS store;
// it reflects the request that opened the connection (keep-alive reuse skips the check).
function logBlockedUrlValidation(hostname: string, resolvedIps: string[]): void {
    logger.warn('[SSRF] Request blocked by URL validation check', {
        hostname,
        resolvedIps,
        ...fetchAttribution.getStore(),
    })
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
            logBlockedUrlValidation(hostname, [bare])
            throw new SecureRequestError('Hostname is not allowed')
        }
        return
    }

    if (!isGlobalIPv4(ipv4)) {
        unsafeRequestCounter.inc({ reason: 'internal_ip_literal' })
        logBlockedUrlValidation(hostname, [bare])
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
    const resolvedIps = addrinfo.map((a) => a.address)
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
                logBlockedUrlValidation(hostname, resolvedIps)
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
            logBlockedUrlValidation(hostname, resolvedIps)
            throw new SecureRequestError('Hostname is not allowed')
        }
        validAddrinfo.push(addrInfo)
    }
    if (validAddrinfo.length === 0) {
        unsafeRequestCounter.inc({ reason: 'unable_to_resolve' })
        logBlockedUrlValidation(hostname, resolvedIps)
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
// Unlike `makeSecureDispatcher`, this agent deliberately skips the ProxyAgent branch: CDP workers don't
// set the proxy env vars, and SSRF stays covered via `httpStaticLookup`. If CDP egress ever moves behind
// the proxy (see #49170), swap this for a `ProxyAgent` — undici's `ProxyAgent` supports `allowH2` — so
// H2 traffic (e.g. APNs) doesn't silently keep going direct.
const sharedSecureH2Agent = new Agent({
    keepAliveTimeout: Number(requestConfig.EXTERNAL_REQUEST_KEEP_ALIVE_TIMEOUT_MS),
    connections: requestConfig.EXTERNAL_REQUEST_CONNECTIONS,
    allowH2: true,
    connect: {
        lookup: httpStaticLookup,
        timeout: requestConfig.EXTERNAL_REQUEST_CONNECT_TIMEOUT_MS,
    },
})
const sharedInsecureAgent = new InsecureAgent()

function destroyBody(body: Dispatcher.ResponseData['body']): void {
    try {
        body.on('error', () => {})
        body.destroy()
    } catch {
        // The body already ended, or another caller destroyed it.
    }
}

/**
 * The prototype is null because every key comes from the remote server, and `__proto__` on a plain
 * object literal is a setter rather than a key.
 */
function flattenHeaders(raw: Dispatcher.ResponseData['headers']): Record<string, string> {
    const headers: Record<string, string> = Object.create(null)
    for (const [key, value] of Object.entries(raw)) {
        const singleValue = Array.isArray(value) ? value[0] : value
        if (singleValue) {
            headers[key] = singleValue
        }
    }
    return headers
}

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
    destroyBody(body)
    return text
}

export async function _fetch(
    url: string,
    options: FetchOptions = {},
    dispatcher: Dispatcher,
    defaultTimeoutMs: number = requestConfig.EXTERNAL_REQUEST_TIMEOUT_MS
): Promise<FetchResponse> {
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        throw new Error('Invalid URL')
    }

    if (!parsed.hostname || !(parsed.protocol === 'http:' || parsed.protocol === 'https:')) {
        throw new Error('URL must have HTTP or HTTPS protocol and a valid hostname')
    }

    options.timeoutMs = options.timeoutMs ?? defaultTimeoutMs

    const result = await request(parsed.toString(), {
        method: options.method ?? 'GET',
        headers: options.headers,
        body: options.body,
        dispatcher,
        // request() does not follow redirects, so a response can never bounce to an unvalidated host
        signal: options.timeoutMs ? AbortSignal.timeout(options.timeoutMs) : undefined,
    })

    const headers = flattenHeaders(result.headers)

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
                destroyBody(result.body)
            }
            return Promise.resolve()
        },
    }
}

export async function internalFetch(url: string, options: FetchOptions = {}): Promise<FetchResponse> {
    return await _fetch(url, options, sharedInsecureAgent)
}

/**
 * Requests to a host we don't run, meaning CDP destinations and anything else pointed at a
 * customer-supplied URL. These take the third-party response budget, which is tunable separately
 * from the internal-service one that `internalFetch` keeps; see
 * DEFAULT_THIRD_PARTY_REQUEST_TIMEOUT_MS.
 */
export async function fetch(url: string, options: FetchOptions = {}): Promise<FetchResponse> {
    const parsed = new URL(url)
    validateHostnameIPLiteral(parsed.hostname, !isProdEnv())
    inflightExternalRequests.inc()
    try {
        const dispatcher = options.allowH2 ? sharedSecureH2Agent : sharedSecureAgent
        return await _fetch(url, options, dispatcher, requestConfig.EXTERNAL_REQUEST_THIRD_PARTY_TIMEOUT_MS)
    } finally {
        inflightExternalRequests.dec()
    }
}

export type StreamedFetchOptions = {
    headers?: HeadersInit
    timeoutMs: number
}

export type StreamedResponse = {
    status: number
    headers: Record<string, string>
    headerLines: Array<{ name: string; value: string }>
    /**
     * Reads at most `maxBytes`, then abandons the rest. `overLimit` says the response had more, and
     * `bytes` then contains the first `maxBytes`, so parsers with a bounded-prefix rule can use it.
     */
    read: (maxBytes: number, retainPrefixOnOverflow?: boolean) => Promise<{ bytes: Buffer; overLimit: boolean }>
    discard: () => void
}

function orderedHeaderLines(raw: unknown): Array<{ name: string; value: string }> {
    if (Array.isArray(raw)) {
        const lines: Array<{ name: string; value: string }> = []
        for (let index = 0; index + 1 < raw.length; index += 2) {
            lines.push({ name: String(raw[index]).toLowerCase(), value: String(raw[index + 1]) })
        }
        return lines
    }
    if (!raw || typeof raw !== 'object') {
        return []
    }
    return Object.entries(raw).flatMap(([name, value]) =>
        (Array.isArray(value) ? value : [value]).flatMap((line) =>
            line === undefined ? [] : [{ name: name.toLowerCase(), value: String(line) }]
        )
    )
}

function flattenHeaderLines(lines: Array<{ name: string; value: string }>): Record<string, string> {
    const headers: Record<string, string> = Object.create(null)
    for (const { name, value } of lines) {
        headers[name] ??= value
    }
    return headers
}

/**
 * Memory here follows the bytes that arrive, never the bytes a response claims.
 *
 * One buffer sized from `Content-Length` would halve the peak for an honest response, because the
 * chunks and the concatenated copy exist together for a moment. It would also let an origin hold
 * `maxBytes` for the whole request timeout, once for every request in flight, by declaring a large
 * body and then sending almost nothing.
 */
async function readCappedBody(
    body: Dispatcher.ResponseData['body'],
    maxBytes: number,
    retainPrefixOnOverflow: boolean
): Promise<{ bytes: Buffer; overLimit: boolean }> {
    const chunks: Buffer[] = []
    let total = 0
    let overLimit = false
    try {
        for await (const chunk of body) {
            const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
            const remaining = maxBytes - total
            if (buffer.length > remaining) {
                if (remaining > 0) {
                    chunks.push(buffer.subarray(0, remaining))
                    total += remaining
                }
                overLimit = true
                if (!retainPrefixOnOverflow) {
                    chunks.length = 0
                    total = 0
                }
                break
            }
            chunks.push(buffer)
            total += buffer.length
        }
    } finally {
        destroyBody(body)
    }
    return { bytes: Buffer.concat(chunks, total), overLimit }
}

/**
 * A third-party request whose caller reads the body under a byte limit.
 *
 * `fetch` above gives the caller `text()`, which buffers a whole body of any size. An origin can
 * answer a request for a small image with gigabytes. Here the caller reads the status and the
 * headers first, then sets a byte limit or abandons the body.
 *
 * This does not follow redirects, as `fetch` does not, so a response cannot bounce to a host that no
 * check has seen. A caller that follows one must call this again for the new URL.
 *
 * The caller must call `read` or `discard`, and only one of them. The socket stays held until then.
 */
export async function fetchStreamed(url: string, options: StreamedFetchOptions): Promise<StreamedResponse> {
    const parsed = validateUrl(url)
    validateHostnameIPLiteral(parsed.hostname, !isProdEnv())

    inflightExternalRequests.inc()
    let result: Dispatcher.ResponseData
    try {
        result = await request(parsed.toString(), {
            method: 'GET',
            headers: options.headers,
            dispatcher: sharedSecureAgent,
            signal: AbortSignal.timeout(options.timeoutMs),
            responseHeaders: 'raw',
        })
    } catch (error) {
        inflightExternalRequests.dec()
        throw error
    }

    // The gauge holds until the body is done, not until the headers arrive, because the body takes
    // nearly all the time of an image request.
    let settled = false
    const settle = (): boolean => {
        if (settled) {
            return false
        }
        settled = true
        inflightExternalRequests.dec()
        return true
    }

    const headerLines = orderedHeaderLines(result.headers)
    const headers = flattenHeaderLines(headerLines)
    return {
        status: result.statusCode,
        headers,
        headerLines,
        read: async (maxBytes: number, retainPrefixOnOverflow = true) => {
            if (settled) {
                return { bytes: Buffer.alloc(0), overLimit: false }
            }
            try {
                return await readCappedBody(result.body, maxBytes, retainPrefixOnOverflow)
            } finally {
                settle()
            }
        },
        discard: () => {
            if (settle()) {
                destroyBody(result.body)
            }
        },
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
    requestOptions.signal = AbortSignal.timeout(requestConfig.EXTERNAL_REQUEST_THIRD_PARTY_TIMEOUT_MS)

    return undiciFetch(parsed.toString(), requestOptions)
}
