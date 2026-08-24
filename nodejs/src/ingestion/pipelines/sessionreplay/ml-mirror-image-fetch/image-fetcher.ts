import { InvalidRequestError, ResolutionError, SecureRequestError, fetchStreamed } from '~/common/utils/request'

import { OriginPolicyReason, ResponseOptOutReason, responseOptOutReason } from './configuration-policy'
import { HttpCacheMetadata } from './crawl-history'
import { ImageFetchRequestMetrics } from './metrics'
import { canonicalizeUrl } from './politeness-key'
import { WebBotAuthRequestSigner } from './web-bot-auth'

/**
 * The raster formats that the fetch lane and image scrubber accept.
 *
 * SVG is absent on purpose. It is a text format that can carry the page's own data, so its redaction
 * belongs on the inline path rather than on an image model.
 */
const ALLOWED_CONTENT_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif'] as const

export type ImageContentType = (typeof ALLOWED_CONTENT_TYPES)[number]

export type FetchOutcome =
    | 'ok'
    | 'not_found'
    | 'forbidden'
    | 'rate_limited'
    | 'server_error'
    | 'unexpected_status'
    | 'bad_redirect'
    | 'request_deferred'
    | 'redirect_policy_refused'
    | 'redirect_offsite'
    | 'redirect_continuation'
    | 'too_large'
    | 'not_image'
    | 'unsupported_encoding'
    | 'blocked'
    | 'opt_out'
    | 'not_modified'
    | 'timeout'
    | 'error'

export type TransientFetchOutcome = Extract<FetchOutcome, 'timeout' | 'error' | 'rate_limited' | 'server_error'>
export type FetchRefusalReason = OriginPolicyReason | ResponseOptOutReason | 'configuration_refused'

export interface ImageFetchResult {
    outcome: FetchOutcome
    redirects: number
    currentUrl: string
    status?: number
    bytes?: Buffer
    contentType?: ImageContentType
    contentEncoding?: string
    cache?: HttpCacheMetadata
    refusalReason?: FetchRefusalReason
    /** Set by a 429 or a 503 that named a period. The caller holds the registrable domain for that period. */
    retryAfterMs?: number
    schedulingReason?: RequestScheduleBlockReason
    schedulingWaitMs?: number
    policyTransient?: boolean
    /** Where a redirect this lane did not follow points. The caller republishes it rather than fetching it. */
    redirectTarget?: { url: string; host: string }
}

export interface ImageFetchOptions {
    maxBytes: number
    /** Covers the redirect chain as a whole, so a chain of slow hops cannot outlive one hop's budget. */
    timeoutMs: number
    maxRedirects: number
    scheduleRequest: <T>(
        url: URL,
        deadlineMs: number,
        request: () => Promise<T>
    ) => Promise<{ ran: true; value: T } | { ran: false; reason: RequestScheduleBlockReason; waitMs: number }>
    checkRedirectPolicy: (url: string) => Promise<RedirectTargetPolicy>
    isDifferentOrigin: (url: URL) => boolean
    cache?: HttpCacheMetadata
    tdmrepReservation: boolean
    onRedirectResponse?: () => void
}

export type RequestScheduleBlockReason =
    | 'breaker_open'
    | 'backoff'
    | 'deadline'
    | 'origin_map_full'
    | 'registrable_domain_map_full'
    | 'connection_limit'

export type RedirectTargetPolicy =
    | { allowed: true; tdmrepReservation: boolean }
    | { allowed: false; transient: boolean; reason: OriginPolicyReason | 'configuration_refused' }

export interface ImageFetcher {
    fetch(url: string, options: ImageFetchOptions): Promise<ImageFetchResult>
}

const USER_AGENT = 'PostHogImageFetcherBot/1.0 (+https://posthog.com/docs/ai-research/image-fetcher-bot)'

const REQUEST_HEADERS: Record<string, string> = {
    'user-agent': USER_AGENT,
    accept: 'image/*',
    'accept-encoding': 'gzip, deflate, br, zstd',
}

const REDIRECT_STATUSES = new Set([301, 302, 303, 307, 308])

/**
 * This sends no user credential: no cookie, no `Authorization`, and no `Referer`. This lane must not
 * reach an image behind a login, and a `Referer` would tell the origin which page of the customer's
 * site the image sat on. Web Bot Auth identifies PostHog as the operator of the request.
 *
 * Every refusal is an outcome rather than a throw. This runs inside a Kafka batch, one URL at a
 * time, and a throw would abandon the URLs after it in the same batch.
 */
export class HttpImageFetcher implements ImageFetcher {
    constructor(
        private readonly policy: RedirectPolicy,
        private readonly webBotAuthSigner: WebBotAuthRequestSigner
    ) {}

    public async fetch(url: string, options: ImageFetchOptions): Promise<ImageFetchResult> {
        const deadlineMs = Date.now() + options.timeoutMs
        let target = url
        let currentCache = options.cache
        let tdmrepReservation = options.tdmrepReservation
        for (let redirects = 0; ; redirects++) {
            const remainingMs = deadlineMs - Date.now()
            if (remainingMs <= 0) {
                return { outcome: 'timeout', redirects, currentUrl: target }
            }
            let scheduled:
                | { ran: true; value: HopResult }
                | { ran: false; reason: RequestScheduleBlockReason; waitMs: number }
            try {
                scheduled = await options.scheduleRequest(new URL(target), deadlineMs, () =>
                    this.hop(
                        target,
                        Math.max(1, deadlineMs - Date.now()),
                        options.maxBytes,
                        currentCache,
                        tdmrepReservation
                    )
                )
            } catch (error) {
                return { outcome: classifyError(error), redirects, currentUrl: target }
            }
            if (!scheduled.ran) {
                return {
                    outcome: 'request_deferred',
                    redirects,
                    currentUrl: target,
                    schedulingReason: scheduled.reason,
                    schedulingWaitMs: scheduled.waitMs,
                }
            }
            const hop = scheduled.value
            if (hop.kind !== 'redirect') {
                return { ...hop.result, redirects, currentUrl: target }
            }
            const next = resolveRedirect(target, hop.location, this.policy)
            if (!next) {
                return { outcome: 'bad_redirect', redirects, currentUrl: target, status: hop.status }
            }
            options.onRedirectResponse?.()
            if (options.isDifferentOrigin(next)) {
                return {
                    outcome: 'redirect_offsite',
                    redirects,
                    currentUrl: target,
                    status: hop.status,
                    redirectTarget: { url: next.toString(), host: next.hostname },
                }
            }
            if (redirects >= options.maxRedirects) {
                return {
                    outcome: 'redirect_continuation',
                    redirects,
                    currentUrl: target,
                    status: hop.status,
                    redirectTarget: { url: next.toString(), host: next.hostname },
                    cache: hop.cache,
                }
            }
            const redirectPolicy = await options.checkRedirectPolicy(next.toString())
            if (!redirectPolicy.allowed) {
                return {
                    outcome: 'redirect_policy_refused',
                    redirects: redirects + 1,
                    currentUrl: next.toString(),
                    status: hop.status,
                    refusalReason: redirectPolicy.reason,
                    policyTransient: redirectPolicy.transient,
                    cache: hop.cache,
                }
            }
            target = next.toString()
            currentCache = undefined
            tdmrepReservation = redirectPolicy.tdmrepReservation
        }
    }

    private async hop(
        url: string,
        timeoutMs: number,
        maxBytes: number,
        previousCache: HttpCacheMetadata | undefined,
        tdmrepReservation: boolean
    ): Promise<HopResult> {
        const requestTimeMs = Date.now()
        const canonical = canonicalizeUrl(url)
        let requestOutcome = ImageFetchRequestMetrics.outcomeForHttpStatus()
        const headers: Record<string, string> = { ...REQUEST_HEADERS, ...this.webBotAuthSigner.headersForGet(url) }
        if (previousCache?.etag) {
            headers['if-none-match'] = previousCache.etag
        } else if (previousCache?.lastModified) {
            headers['if-modified-since'] = previousCache.lastModified
        }
        try {
            const response = await fetchStreamed(url, { headers, timeoutMs })
            const status = response.status
            requestOutcome = ImageFetchRequestMetrics.outcomeForHttpStatus(status)
            const cache = cacheMetadata(requestTimeMs, Date.now(), response.headerLines)
            const optOut = responseOptOutReason(response.headerLines, tdmrepReservation)
            if (optOut) {
                response.discard()
                return { kind: 'done', result: { outcome: 'opt_out', status, refusalReason: optOut, cache } }
            }

            if (REDIRECT_STATUSES.has(status)) {
                response.discard()
                const locations = headerValues(response.headerLines, 'location')
                const location = locations.length === 1 ? locations[0] : undefined
                return location
                    ? { kind: 'redirect', status, location, cache }
                    : { kind: 'done', result: { outcome: 'bad_redirect', status, cache } }
            }
            if (status === 304) {
                response.discard()
                const outcome =
                    previousCache?.etag || previousCache?.lastModified ? 'not_modified' : 'unexpected_status'
                return { kind: 'done', result: { outcome, status, cache } }
            }
            if (status !== 200) {
                response.discard()
                return {
                    kind: 'done',
                    result: { ...statusResult(status, headerValues(response.headerLines, 'retry-after')), cache },
                }
            }

            const contentTypes = headerValues(response.headerLines, 'content-type').map(normalizeContentType)
            const contentType = contentTypes[0]
            if (!contentType || contentTypes.some((candidate) => candidate !== contentType)) {
                response.discard()
                return { kind: 'done', result: { outcome: 'not_image', status, cache } }
            }
            const contentEncoding = normalizeContentEncoding(headerValues(response.headerLines, 'content-encoding'))
            if (contentEncoding === null) {
                response.discard()
                return { kind: 'done', result: { outcome: 'unsupported_encoding', status, cache } }
            }
            const declaredTooLarge = headerValues(response.headerLines, 'content-length').some((value) => {
                const declaredBytes = Number(value)
                return Number.isFinite(declaredBytes) && declaredBytes > maxBytes
            })
            if (declaredTooLarge) {
                response.discard()
                return { kind: 'done', result: { outcome: 'too_large', status, cache } }
            }

            const { bytes, overLimit } = await response.read(maxBytes, false)
            if (overLimit) {
                return { kind: 'done', result: { outcome: 'too_large', status, cache } }
            }
            return { kind: 'done', result: { outcome: 'ok', status, bytes, contentType, contentEncoding, cache } }
        } finally {
            if (canonical) {
                ImageFetchRequestMetrics.observeRequest(requestOutcome, (Date.now() - requestTimeMs) / 1000)
            }
        }
    }
}

type HopResult =
    | { kind: 'redirect'; status: number; location: string; cache: HttpCacheMetadata }
    | { kind: 'done'; result: Omit<ImageFetchResult, 'redirects' | 'currentUrl'> }

function statusResult(status: number, retryAfterValues: string[]): Omit<ImageFetchResult, 'redirects' | 'currentUrl'> {
    const retryAfterMs = maximumRetryAfterMs(retryAfterValues)
    if (status === 404 || status === 410) {
        return { outcome: 'not_found', status }
    }
    if (status === 401 || status === 403) {
        return { outcome: 'forbidden', status }
    }
    if (status === 408 || status === 425) {
        return { outcome: 'rate_limited', status }
    }
    if (status === 429) {
        return { outcome: 'rate_limited', status, retryAfterMs }
    }
    if (status === 503) {
        return { outcome: 'server_error', status, retryAfterMs }
    }
    if (status >= 500) {
        return { outcome: 'server_error', status }
    }
    return { outcome: 'unexpected_status', status }
}

function maximumRetryAfterMs(values: string[]): number | undefined {
    const parsed = values.flatMap((value) => {
        const retryAfterMs = parseRetryAfterMs(value)
        return retryAfterMs === undefined ? [] : [retryAfterMs]
    })
    return parsed.length > 0 ? Math.max(...parsed) : undefined
}

/** RFC 9110 allows a count of seconds or an HTTP date. Real responses use both. */
export function parseRetryAfterMs(value: string | undefined): number | undefined {
    if (!value) {
        return undefined
    }
    const trimmed = value.trim()
    if (/^\d+$/.test(trimmed)) {
        const seconds = Number(trimmed)
        return Number.isSafeInteger(seconds) && seconds <= Number.MAX_SAFE_INTEGER / 1000 ? seconds * 1000 : undefined
    }
    const dateMs = Date.parse(trimmed)
    if (Number.isNaN(dateMs)) {
        return undefined
    }
    const heldMs = dateMs - Date.now()
    return heldMs > 0 ? heldMs : undefined
}

/**
 * The rules a redirect target must pass, beyond the SSRF checks every hop re-enters.
 *
 * The collector applied all of these to the first candidate before it reached the topic. A redirect
 * target has passed none of them, so a hop could otherwise reach a host the collector would have
 * refused, such as a single-label name, or a name under a suffix that resolves only inside a
 * network. Requirement 8.
 */
export interface RedirectPolicy {
    maxUrlLength: number
    isPublicHost: (host: string) => boolean
}

function resolveRedirect(from: string, location: string, policy: RedirectPolicy): URL | null {
    let next: URL
    try {
        next = new URL(location, from)
    } catch {
        return null
    }
    // Requirement 9: no downgrade to plain HTTP. `URL.protocol` is lower case already, which a
    // comparison against the raw location string is not.
    if (next.protocol !== 'https:') {
        return null
    }
    // This lane sends no credentials, and a userinfo part would put some back on the next hop.
    if (next.username || next.password) {
        return null
    }
    // A port other than the scheme's own would turn this lane into a port prober. A page names any
    // host and port, the connection leaves from our egress addresses, and the outcome metric reports
    // what answered. Few images are served on another port, so this refuses the whole case.
    if (next.port !== '') {
        return null
    }
    const canonical = canonicalizeUrl(next.toString())
    if (!canonical || canonical.fetch.length > policy.maxUrlLength) {
        return null
    }
    if (!policy.isPublicHost(canonical.host)) {
        return null
    }
    return new URL(canonical.fetch)
}

function normalizeContentType(header: string | undefined): ImageContentType | undefined {
    if (!header) {
        return undefined
    }
    const type = header.split(';')[0].trim().toLowerCase()
    return ALLOWED_CONTENT_TYPES.find((allowed) => allowed === type)
}

const ALLOWED_CONTENT_ENCODINGS = new Set(['gzip', 'deflate', 'br', 'zstd'])
const MAX_CONTENT_ENCODING_LAYERS = 4

function normalizeContentEncoding(values: string[]): string | undefined | null {
    const declaredCodings = values.flatMap((value) => value.split(',')).map((coding) => coding.trim().toLowerCase())
    if (declaredCodings.length > MAX_CONTENT_ENCODING_LAYERS || declaredCodings.some((coding) => coding === '')) {
        return null
    }
    const codings = declaredCodings.filter((coding) => coding !== 'identity')
    if (codings.some((coding) => !ALLOWED_CONTENT_ENCODINGS.has(coding))) {
        return null
    }
    return codings.length > 0 ? codings.join(', ') : undefined
}

function headerValues(headerLines: Array<{ name: string; value: string }>, name: string): string[] {
    return headerLines.filter((line) => line.name === name).map((line) => line.value)
}

function cacheMetadata(
    requestTimeMs: number,
    responseTimeMs: number,
    headerLines: Array<{ name: string; value: string }>
): HttpCacheMetadata {
    return {
        requestTimeMs,
        responseTimeMs,
        etag: singletonHeader(headerLines, 'etag'),
        lastModified: singletonHeader(headerLines, 'last-modified'),
        date: singletonHeader(headerLines, 'date'),
        age: singletonHeader(headerLines, 'age'),
        cacheControl: combinedHeader(headerLines, 'cache-control'),
        expires: singletonHeader(headerLines, 'expires'),
    }
}

function singletonHeader(headerLines: Array<{ name: string; value: string }>, name: string): string | undefined {
    const values = headerValues(headerLines, name)
    return values.length === 1 ? values[0] : undefined
}

function combinedHeader(headerLines: Array<{ name: string; value: string }>, name: string): string | undefined {
    const values = headerValues(headerLines, name)
    return values.length > 0 ? values.join(', ') : undefined
}

export function classifyError(error: unknown): FetchOutcome {
    // `blocked` is terminal, so it must only cover a permanent property of the URL. A refused
    // address and an unparsable URL are permanent. A name that did not resolve is not, because the
    // shared lookup raises the same error for a resolver timeout as for a name that does not exist.
    if (error instanceof SecureRequestError || error instanceof InvalidRequestError) {
        return 'blocked'
    }
    if (error instanceof ResolutionError) {
        return 'error'
    }
    const name = error instanceof Error ? error.name : ''
    const code = typeof error === 'object' && error !== null ? String((error as { code?: unknown }).code ?? '') : ''
    if (name === 'TimeoutError' || name === 'AbortError' || code.includes('TIMEOUT')) {
        return 'timeout'
    }
    return 'error'
}
