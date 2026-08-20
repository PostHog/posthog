import { InvalidRequestError, ResolutionError, SecureRequestError, fetchStreamed } from '~/common/utils/request'

import { WebBotAuthRequestSigner } from './web-bot-auth'

/**
 * The raster set the anonymizer keeps on a collected ref, so a fetched image and an inline one reach
 * the scrub lane as the same kind of thing.
 *
 * SVG is absent on purpose. It is a text format that can carry the page's own data, so its redaction
 * belongs on the inline path rather than on an image model.
 */
const ALLOWED_CONTENT_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp', 'image/avif'] as const

export type ImageContentType = (typeof ALLOWED_CONTENT_TYPES)[number]

export type FetchOutcome =
    | 'ok'
    | 'not_found'
    | 'forbidden'
    | 'rate_limited'
    | 'server_error'
    | 'unexpected_status'
    | 'too_many_redirects'
    | 'bad_redirect'
    | 'redirect_deferred'
    | 'redirect_offsite'
    | 'too_large'
    | 'not_image'
    | 'unsupported_encoding'
    | 'blocked'
    | 'timeout'
    | 'error'

export interface ImageFetchResult {
    outcome: FetchOutcome
    redirects: number
    status?: number
    bytes?: Buffer
    contentType?: ImageContentType
    /** Set by a 429 or a 503 that named a period. The caller holds the whole domain for that period. */
    retryAfterMs?: number
    /** Where a redirect this lane did not follow points. The caller republishes it rather than fetching it. */
    redirectTarget?: { url: string; host: string }
}

export interface ImageFetchOptions {
    maxBytes: number
    /** Covers the redirect chain as a whole, so a chain of slow hops cannot outlive one hop's budget. */
    timeoutMs: number
    maxRedirects: number
    /**
     * The fetch asks this for every redirect target it will follow, so each hop spends a token.
     *
     * `remainingMs` is what is left of this request, so a wait longer than that must `defer`.
     *
     * A `defer` must not read as a `refuse`, because the caller writes a refusal to the crawl
     * history and writes nothing for a deferral.
     */
    authorizeRedirect: (url: URL, remainingMs: number) => Promise<RedirectDecision>
    /**
     * True when the target belongs to another operator, so this fetch must not follow it.
     *
     * The fetch asks this before it applies the redirect limit, and the question spends nothing. The
     * limit bounds the hops this request follows itself. Nobody here follows a target for another
     * operator, so it goes back to Kafka and costs one hop instead. Requirement 7.
     */
    isOffsite: (url: URL) => boolean
}

/**
 * `allow` follows the target here. `defer` means the budget is spent or the breaker is open.
 * `refuse` means this lane will never follow the target.
 */
export type RedirectDecision = 'allow' | 'refuse' | 'defer'

export interface ImageFetcher {
    fetch(url: string, options: ImageFetchOptions): Promise<ImageFetchResult>
}

const USER_AGENT = 'PostHogImageFetcherBot/1.0 (+https://posthog.com/docs/ai-research/image-fetcher-bot)'

const REQUEST_HEADERS: Record<string, string> = {
    'user-agent': USER_AGENT,
    accept: 'image/*',
    // Every type this lane accepts is compressed already, so gzip saves the origin almost nothing,
    // and the byte limit can count what arrives rather than what a decoder would produce from it.
    'accept-encoding': 'identity',
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
        for (let redirects = 0; ; redirects++) {
            const remainingMs = deadlineMs - Date.now()
            if (remainingMs <= 0) {
                return { outcome: 'timeout', redirects }
            }
            let hop: HopResult
            try {
                hop = await this.hop(target, remainingMs, options.maxBytes)
            } catch (error) {
                return { outcome: classifyError(error), redirects }
            }
            if (hop.kind !== 'redirect') {
                return { ...hop.result, redirects }
            }
            const next = resolveRedirect(target, hop.location, this.policy)
            if (!next) {
                return { outcome: 'bad_redirect', redirects, status: hop.status }
            }
            if (options.isOffsite(next)) {
                // The budget, the breaker, and the connection count for that domain belong to the
                // consumer that owns its partition.
                return {
                    outcome: 'redirect_offsite',
                    redirects,
                    status: hop.status,
                    redirectTarget: { url: next.toString(), host: next.hostname },
                }
            }
            // After the offsite test and before authorization, so a hop this lane refuses spends no
            // token from the budget of the site it would have landed on.
            if (redirects >= options.maxRedirects) {
                return { outcome: 'too_many_redirects', redirects, status: hop.status }
            }
            let decision: RedirectDecision
            try {
                decision = await options.authorizeRedirect(next, deadlineMs - Date.now())
            } catch (error) {
                return { outcome: classifyError(error), redirects }
            }
            if (decision !== 'allow') {
                const outcome = decision === 'defer' ? 'redirect_deferred' : 'bad_redirect'
                return { outcome, redirects, status: hop.status }
            }
            target = next.toString()
        }
    }

    private async hop(url: string, timeoutMs: number, maxBytes: number): Promise<HopResult> {
        const headers = { ...REQUEST_HEADERS, ...this.webBotAuthSigner.headersForGet(url) }
        const response = await fetchStreamed(url, { headers, timeoutMs })
        const status = response.status

        if (REDIRECT_STATUSES.has(status)) {
            response.discard()
            const location = response.headers['location']
            return location
                ? { kind: 'redirect', status, location }
                : { kind: 'done', result: { outcome: 'bad_redirect', status } }
        }
        if (status !== 200) {
            response.discard()
            return { kind: 'done', result: statusResult(status, response.headers['retry-after']) }
        }

        const contentType = normalizeContentType(response.headers['content-type'])
        if (!contentType) {
            response.discard()
            return { kind: 'done', result: { outcome: 'not_image', status } }
        }
        // An origin that compresses anyway makes the byte limit count compressed bytes, and the
        // payload behind them can be far larger. This is a refusal by this lane rather than a fact
        // about the image, so it gets its own outcome and does not write the URL off.
        const encoding = response.headers['content-encoding']?.trim().toLowerCase()
        if (encoding && encoding !== 'identity') {
            response.discard()
            return { kind: 'done', result: { outcome: 'unsupported_encoding', status } }
        }
        // Before the body, so a declared size over the limit costs one header exchange.
        const declaredBytes = Number(response.headers['content-length'])
        if (Number.isFinite(declaredBytes) && declaredBytes > maxBytes) {
            response.discard()
            return { kind: 'done', result: { outcome: 'too_large', status } }
        }

        const { bytes, overLimit } = await response.read(maxBytes)
        if (overLimit) {
            return { kind: 'done', result: { outcome: 'too_large', status } }
        }
        // A payload that disagrees with its declared type would reach the scrub lane as an image no
        // model can read, and by then the URL that produced it is gone.
        if (!magicBytesMatch(bytes, contentType)) {
            return { kind: 'done', result: { outcome: 'not_image', status } }
        }
        return { kind: 'done', result: { outcome: 'ok', status, bytes, contentType } }
    }
}

type HopResult =
    | { kind: 'redirect'; status: number; location: string }
    | { kind: 'done'; result: Omit<ImageFetchResult, 'redirects'> }

function statusResult(status: number, retryAfter: string | undefined): Omit<ImageFetchResult, 'redirects'> {
    if (status === 404 || status === 410) {
        return { outcome: 'not_found', status }
    }
    if (status === 401 || status === 403) {
        return { outcome: 'forbidden', status }
    }
    if (status === 429) {
        return { outcome: 'rate_limited', status, retryAfterMs: parseRetryAfterMs(retryAfter) }
    }
    if (status === 503) {
        return { outcome: 'server_error', status, retryAfterMs: parseRetryAfterMs(retryAfter) }
    }
    if (status >= 500) {
        return { outcome: 'server_error', status }
    }
    return { outcome: 'unexpected_status', status }
}

/** RFC 9110 allows a count of seconds or an HTTP date. Real responses use both. */
export function parseRetryAfterMs(value: string | undefined): number | undefined {
    if (!value) {
        return undefined
    }
    // An absent, zero, or past period returns undefined, so the caller applies its own default
    // rather than reading zero as a site that wants no pause.
    const trimmed = value.trim()
    const seconds = trimmed === '' ? NaN : Number(trimmed)
    if (Number.isFinite(seconds)) {
        return seconds > 0 ? seconds * 1000 : undefined
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
    const target = next.toString()
    if (target.length > policy.maxUrlLength) {
        return null
    }
    if (!policy.isPublicHost(next.hostname)) {
        return null
    }
    return next
}

function normalizeContentType(header: string | undefined): ImageContentType | undefined {
    if (!header) {
        return undefined
    }
    const type = header.split(';')[0].trim().toLowerCase()
    return ALLOWED_CONTENT_TYPES.find((allowed) => allowed === type)
}

function startsWith(bytes: Buffer, signature: number[], offset = 0): boolean {
    if (bytes.length < offset + signature.length) {
        return false
    }
    return signature.every((byte, index) => bytes[offset + index] === byte)
}

function asciiAt(bytes: Buffer, offset: number, text: string): boolean {
    return startsWith(
        bytes,
        [...text].map((char) => char.charCodeAt(0)),
        offset
    )
}

/**
 * This checks agreement rather than format. Anything that passes still reaches an image decoder
 * later, so this only has to catch a payload that is not the format it claims.
 */
export function magicBytesMatch(bytes: Buffer, contentType: ImageContentType): boolean {
    switch (contentType) {
        case 'image/png':
            return startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
        case 'image/jpeg':
            return startsWith(bytes, [0xff, 0xd8, 0xff])
        case 'image/gif':
            return asciiAt(bytes, 0, 'GIF87a') || asciiAt(bytes, 0, 'GIF89a')
        case 'image/webp':
            return asciiAt(bytes, 0, 'RIFF') && asciiAt(bytes, 8, 'WEBP')
        case 'image/bmp':
            return asciiAt(bytes, 0, 'BM')
        case 'image/avif':
            // An ISO base media file names its brand after the `ftyp` box header, and AVIF still
            // ships under the `mif1` and `msf1` brands that came before the AVIF ones.
            return (
                asciiAt(bytes, 4, 'ftyp') &&
                (asciiAt(bytes, 8, 'avif') ||
                    asciiAt(bytes, 8, 'avis') ||
                    asciiAt(bytes, 8, 'mif1') ||
                    asciiAt(bytes, 8, 'msf1'))
            )
    }
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
