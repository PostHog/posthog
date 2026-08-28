import { ResolutionError, SecureRequestError, StreamedResponse, fetchStreamed } from '~/common/utils/request'

import { HttpImageFetcher, ImageFetchOptions, RedirectPolicy } from './image-fetcher'
import { ImageFetchRequestMetrics } from './metrics'
import { WebBotAuthRequestSigner } from './web-bot-auth'

jest.mock('~/common/utils/request', () => ({
    ...jest.requireActual('~/common/utils/request'),
    fetchStreamed: jest.fn(),
}))

const fetchStreamedMock = fetchStreamed as jest.MockedFunction<typeof fetchStreamed>

const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00])
const GIF = Buffer.from('GIF89a-and-then-some')

const OPTIONS: ImageFetchOptions = {
    maxBytes: 1000,
    timeoutMs: 5000,
    maxRedirects: 3,
    isDifferentOrigin: () => false,
    scheduleRequest: async (_url, _deadlineMs, request) => ({ ran: true as const, value: await request() }),
    checkRedirectPolicy: () => Promise.resolve({ allowed: true as const, tdmrepReservation: false }),
    tdmrepReservation: false,
}

function respond(
    status: number,
    headers: Record<string, string>,
    body: { bytes: Buffer; overLimit: boolean } = { bytes: Buffer.alloc(0), overLimit: false }
): StreamedResponse {
    return {
        status,
        headers,
        headerLines: Object.entries(headers).map(([name, value]) => ({ name, value })),
        read: jest.fn().mockResolvedValue(body),
        discard: jest.fn(),
    }
}

function image(bytes: Buffer, contentType: string, extraHeaders: Record<string, string> = {}): StreamedResponse {
    return respond(200, { 'content-type': contentType, ...extraHeaders }, { bytes, overLimit: false })
}

const NOOP_SIGNER: WebBotAuthRequestSigner = { headersForGet: () => ({}) }
/** Everything public by default, so a test that cares about the policy says so. */
const fetcher = (
    policy: Partial<RedirectPolicy> = {},
    webBotAuthSigner: WebBotAuthRequestSigner = NOOP_SIGNER
): HttpImageFetcher =>
    new HttpImageFetcher({ maxUrlLength: 2048, isPublicHost: () => true, ...policy }, webBotAuthSigner)

describe('HttpImageFetcher', () => {
    beforeEach(() => {
        fetchStreamedMock.mockReset()
    })
    afterEach(() => jest.restoreAllMocks())

    it('identifies every request as PostHogImageFetcherBot', async () => {
        fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png'))

        await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(fetchStreamedMock).toHaveBeenCalledWith(
            'https://cdn.example.com/a.png',
            expect.objectContaining({
                headers: expect.objectContaining({
                    'user-agent':
                        'PostHogImageFetcherBot/1.0 (+https://posthog.com/docs/ai-research/image-fetcher-bot)',
                }),
            })
        )
    })

    it('attributes image requests to the source partition', async () => {
        const observeRequest = jest.spyOn(ImageFetchRequestMetrics, 'observeRequest')
        fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png'))

        await fetcher().fetch('https://cdn.example.com/a.png', { ...OPTIONS, sourcePartitions: [7, 42] })

        expect(observeRequest).toHaveBeenCalledWith('2xx', expect.any(Number), [7, 42])
    })

    it('returns the bytes of an image whose payload matches its declared type', async () => {
        fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png; charset=binary'))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({
            outcome: 'ok',
            status: 200,
            bytes: PNG,
            contentType: 'image/png',
            redirects: 0,
            currentUrl: 'https://cdn.example.com/a.png',
        })
    })

    it('uses an ETag validator and accepts the resulting 304', async () => {
        fetchStreamedMock.mockResolvedValue(respond(304, { etag: '"v1"' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            cache: {
                requestTimeMs: Date.now() - 1_000,
                responseTimeMs: Date.now() - 500,
                etag: '"v1"',
                lastModified: 'yesterday',
            },
        })

        expect(fetchStreamedMock.mock.calls[0][1].headers).toMatchObject({ 'if-none-match': '"v1"' })
        expect(fetchStreamedMock.mock.calls[0][1].headers).not.toHaveProperty('if-modified-since')
        expect(result).toMatchObject({ outcome: 'not_modified', status: 304 })
    })

    it('does not accept an unsolicited 304', async () => {
        fetchStreamedMock.mockResolvedValue(respond(304, {}))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'unexpected_status', status: 304 })
    })

    it('does not send an original URL validator to a redirect target', async () => {
        fetchStreamedMock
            .mockResolvedValueOnce(respond(302, { location: '/moved.png' }))
            .mockResolvedValueOnce(image(PNG, 'image/png'))

        await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            cache: { requestTimeMs: Date.now() - 1_000, responseTimeMs: Date.now() - 500, etag: '"v1"' },
        })

        expect(fetchStreamedMock.mock.calls[0][1].headers).toMatchObject({ 'if-none-match': '"v1"' })
        expect(fetchStreamedMock.mock.calls[1][1].headers).not.toHaveProperty('if-none-match')
    })

    it.each([
        ['a type that is not an image', 'text/html', PNG, 'not_image'],
        ['a type outside the raster set', 'image/svg+xml', PNG, 'not_image'],
        ['the BMP format', 'image/bmp', Buffer.from('BM'), 'not_image'],
        ['a payload that is not the declared format', 'image/gif', PNG, 'ok'],
        ['a payload of the wrong raster format', 'image/png', GIF, 'ok'],
    ])('handles %s', async (_name, contentType, bytes, outcome) => {
        fetchStreamedMock.mockResolvedValue(image(bytes, contentType))

        const result = await fetcher().fetch('https://cdn.example.com/a', OPTIONS)

        expect(result).toMatchObject({ outcome })
    })

    it('refuses a declared size over the limit without reading the body', async () => {
        const response = image(PNG, 'image/png', { 'content-length': '99999' })
        fetchStreamedMock.mockResolvedValue(response)

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'too_large' })
        expect(response.read).not.toHaveBeenCalled()
        expect(response.discard).toHaveBeenCalled()
    })

    it('refuses a body that passes the limit while it is being read', async () => {
        // The case an origin reaches when it declares no length. No check before the body catches it.
        fetchStreamedMock.mockResolvedValue(
            respond(200, { 'content-type': 'image/png' }, { bytes: Buffer.alloc(0), overLimit: true })
        )

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'too_large' })
    })

    it.each([
        [404, 'not_found'],
        [410, 'not_found'],
        [403, 'forbidden'],
        [429, 'rate_limited'],
        [503, 'server_error'],
        [500, 'server_error'],
        [418, 'unexpected_status'],
    ])('maps status %s to %s', async (status, outcome) => {
        fetchStreamedMock.mockResolvedValue(respond(status, {}))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome, status })
    })

    it.each([
        ['a count of seconds', '120', 120_000],
        ['an HTTP date', new Date(Date.now() + 90_000).toUTCString(), 90_000],
    ])('reads a Retry-After header given as %s', async (_name, header, expectedMs) => {
        fetchStreamedMock.mockResolvedValue(respond(429, { 'retry-after': header }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        // The parser resolves a date against the clock, so the range allows for the test's own runtime.
        expect(result.retryAfterMs).toBeGreaterThan(expectedMs - 2000)
        expect(result.retryAfterMs).toBeLessThanOrEqual(expectedMs)
    })

    it('uses the longest valid value from repeated Retry-After field lines', async () => {
        const response = respond(429, {})
        response.headerLines = [
            { name: 'retry-after', value: '10' },
            { name: 'retry-after', value: 'invalid' },
            { name: 'retry-after', value: '30' },
        ]
        fetchStreamedMock.mockResolvedValue(response)

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result.retryAfterMs).toBe(30_000)
    })

    it.each([408, 425])('ignores Retry-After on status %s', async (status) => {
        fetchStreamedMock.mockResolvedValue(respond(status, { 'retry-after': '120' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'rate_limited', status })
        expect(result.retryAfterMs).toBeUndefined()
    })

    it('follows a redirect and reports how many hops it took', async () => {
        fetchStreamedMock
            .mockResolvedValueOnce(respond(302, { location: '/moved.png' }))
            .mockResolvedValueOnce(image(PNG, 'image/png'))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'ok', redirects: 1 })
        expect(fetchStreamedMock.mock.calls[1][0]).toBe('https://cdn.example.com/moved.png')
    })

    it('refuses a redirect with repeated Location field lines', async () => {
        const response = respond(302, {})
        response.headerLines = [
            { name: 'location', value: '/first.png' },
            { name: 'location', value: '/second.png' },
        ]
        fetchStreamedMock.mockResolvedValue(response)

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'bad_redirect' })
        expect(fetchStreamedMock).toHaveBeenCalledTimes(1)
    })

    it('signs each redirect hop for its target URL', async () => {
        fetchStreamedMock
            .mockResolvedValueOnce(respond(302, { location: 'https://images.example.net/moved.png' }))
            .mockResolvedValueOnce(image(PNG, 'image/png'))
        const headersForGet = jest
            .fn()
            .mockReturnValueOnce({ signature: 'first-hop-signature' })
            .mockReturnValueOnce({ signature: 'second-hop-signature' })

        await fetcher({}, { headersForGet }).fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(headersForGet.mock.calls).toEqual([
            ['https://cdn.example.com/a.png'],
            ['https://images.example.net/moved.png'],
        ])
        expect(fetchStreamedMock.mock.calls[0][1].headers).toMatchObject({ signature: 'first-hop-signature' })
        expect(fetchStreamedMock.mock.calls[1][1].headers).toMatchObject({ signature: 'second-hop-signature' })
    })

    it.each([
        ['it leaves HTTP for another scheme', 'javascript:alert(1)'],
        ['it carries credentials for the next hop', 'https://user:pw@other.example/a.png'],
        ['it downgrades from HTTPS to plain HTTP', 'http://other.example/a.png'],
    ])('refuses a redirect when %s', async (_name, location) => {
        fetchStreamedMock.mockResolvedValue(respond(302, { location }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'bad_redirect' })
        expect(fetchStreamedMock).toHaveBeenCalledTimes(1)
    })

    it('refuses a downgrade when the first hop named its scheme in capitals (requirement 9)', async () => {
        // A record can carry `HTTPS://`, because the parser validates a parsed copy and stores the
        // string it was given. A guard that reads the raw string misses the capitals and follows
        // the hop in clear text. `URL.protocol` is lower case whatever the URL used.
        fetchStreamedMock.mockResolvedValue(respond(302, { location: 'http://cdn.example.com/b.png' }))

        const result = await fetcher().fetch('HTTPS://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'bad_redirect' })
        expect(fetchStreamedMock).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['a host the collector would have refused', 'https://internal.corp/a.png', { isPublicHost: () => false }],
        ['a target past the length limit', `https://cdn.example.com/${'a'.repeat(300)}.png`, { maxUrlLength: 100 }],
        ['a port the scheme does not own', 'https://cdn.example.com:11211/a.png', {}],
    ])('refuses a redirect to %s (requirement 8)', async (_name, location, policy) => {
        // The collector applied these checks to the first candidate. A redirect target has passed
        // none of them, so a hop could otherwise reach a name that resolves only inside a network.
        fetchStreamedMock.mockResolvedValue(respond(302, { location }))

        const result = await fetcher(policy).fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'bad_redirect' })
        expect(fetchStreamedMock).toHaveBeenCalledTimes(1)
    })

    it('hands off an offsite target that arrives at the redirect limit (requirement 7)', async () => {
        // The limit bounds the hops this request follows itself. Nobody here follows a target for
        // another operator, so it goes back to Kafka and costs one hop rather than being written off
        // with hops left.
        fetchStreamedMock.mockResolvedValue(respond(302, { location: 'https://img.other.net/a.png' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            maxRedirects: 0,
            isDifferentOrigin: () => true,
        })

        expect(result).toMatchObject({
            outcome: 'redirect_offsite',
            redirectTarget: { url: 'https://img.other.net/a.png', host: 'img.other.net' },
        })
    })

    it('stops at the redirect limit for a target on the same origin', async () => {
        fetchStreamedMock.mockResolvedValue(respond(302, { location: 'https://cdn.example.com/b.png' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', { ...OPTIONS, maxRedirects: 0 })

        expect(result).toMatchObject({
            outcome: 'redirect_continuation',
            redirectTarget: { url: 'https://cdn.example.com/b.png', host: 'cdn.example.com' },
        })
    })

    it('defers a redirect whose target has no budget left, so nothing is written to the crawl history for it', async () => {
        // `bad_redirect` is terminal. A CDN in cooldown would otherwise suppress every image behind
        // it for the crawl history TTL, because the lane read a momentary budget as a property of
        // the URL.
        fetchStreamedMock.mockResolvedValue(respond(302, { location: 'https://cdn.example.net/a.png' }))

        let requestNumber = 0
        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            scheduleRequest: async (_url, _deadlineMs, request) => {
                requestNumber += 1
                return requestNumber === 1
                    ? { ran: true as const, value: await request() }
                    : { ran: false as const, reason: 'backoff' as const, waitMs: 90_000 }
            },
        })

        expect(result).toMatchObject({
            outcome: 'request_deferred',
            redirects: 1,
            currentUrl: 'https://cdn.example.net/a.png',
            schedulingReason: 'backoff',
            schedulingWaitMs: 90_000,
        })
        expect(fetchStreamedMock).toHaveBeenCalledTimes(1)
    })

    it('keeps an accepted response coding for the scrubber', async () => {
        fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png', { 'content-encoding': 'gzip' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'ok', contentEncoding: 'gzip' })
    })

    it('keeps repeated content codings in received order', async () => {
        const response = image(PNG, 'image/png')
        response.headerLines = [
            { name: 'content-type', value: 'image/png' },
            { name: 'content-encoding', value: 'gzip' },
            { name: 'content-encoding', value: 'br, zstd' },
        ]
        fetchStreamedMock.mockResolvedValue(response)

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'ok', contentEncoding: 'gzip, br, zstd' })
    })

    it('refuses conflicting repeated Content-Type field lines', async () => {
        const response = image(PNG, 'image/png')
        response.headerLines = [
            { name: 'content-type', value: 'image/png' },
            { name: 'content-type', value: 'image/jpeg' },
        ]
        fetchStreamedMock.mockResolvedValue(response)

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'not_image' })
    })

    it('combines repeated Cache-Control field lines in received order', async () => {
        const response = image(PNG, 'image/png')
        response.headerLines.push(
            { name: 'cache-control', value: 'public, max-age=86400' },
            { name: 'cache-control', value: 'no-store' }
        )
        fetchStreamedMock.mockResolvedValue(response)

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result.cache?.cacheControl).toBe('public, max-age=86400, no-store')
    })

    it('refuses an unsupported response coding', async () => {
        fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png', { 'content-encoding': 'compress' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'unsupported_encoding' })
    })

    it.each(['gzip,', 'gzip, br, deflate, zstd, identity'])(
        'refuses a malformed or excessive response coding list: %s',
        async (contentEncoding) => {
            fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png', { 'content-encoding': contentEncoding }))

            const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

            expect(result).toMatchObject({ outcome: 'unsupported_encoding' })
        }
    )

    it('applies a refusal from any repeated opt-out field line', async () => {
        const response = image(PNG, 'image/png')
        response.headerLines = [
            { name: 'content-type', value: 'image/png' },
            { name: 'x-robots-tag', value: 'all' },
            { name: 'x-robots-tag', value: 'PostHogImageFetcherBot: noimageai' },
        ]
        fetchStreamedMock.mockResolvedValue(response)

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'opt_out', refusalReason: 'x_robots_tag' })
    })

    it('lets a response header override a TDMRep reservation', async () => {
        fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png', { 'tdm-reservation': '0' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            tdmrepReservation: true,
        })

        expect(result).toMatchObject({ outcome: 'ok' })
    })

    it('applies a TDMRep reservation when the response does not override it', async () => {
        fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png'))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            tdmrepReservation: true,
        })

        expect(result).toMatchObject({ outcome: 'opt_out', refusalReason: 'tdm_reservation' })
    })

    it('checks path policy again before a same-origin redirect target is requested', async () => {
        fetchStreamedMock.mockResolvedValue(respond(302, { location: '/private/image.png' }))

        const result = await fetcher().fetch('https://cdn.example.com/public/image.png', {
            ...OPTIONS,
            checkRedirectPolicy: () =>
                Promise.resolve({ allowed: false as const, transient: false, reason: 'robots_disallow' }),
        })

        expect(result).toMatchObject({
            outcome: 'redirect_policy_refused',
            redirects: 1,
            currentUrl: 'https://cdn.example.com/private/image.png',
            refusalReason: 'robots_disallow',
            policyTransient: false,
        })
        expect(fetchStreamedMock).toHaveBeenCalledTimes(1)
    })

    it('applies the redirected path TDM policy to the next response', async () => {
        fetchStreamedMock
            .mockResolvedValueOnce(respond(302, { location: '/reserved/image.png' }))
            .mockResolvedValueOnce(image(PNG, 'image/png'))

        const result = await fetcher().fetch('https://cdn.example.com/public/image.png', {
            ...OPTIONS,
            checkRedirectPolicy: () => Promise.resolve({ allowed: true as const, tdmrepReservation: true }),
        })

        expect(result).toMatchObject({ outcome: 'opt_out', refusalReason: 'tdm_reservation', redirects: 1 })
    })

    it('uses one request deadline for every redirect hop', async () => {
        fetchStreamedMock
            .mockResolvedValueOnce(respond(302, { location: '/moved.png' }))
            .mockResolvedValueOnce(image(PNG, 'image/png'))
        const deadlines: number[] = []

        await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            scheduleRequest: async (_url, deadlineMs, request) => {
                deadlines.push(deadlineMs)
                return { ran: true as const, value: await request() }
            },
        })

        expect(deadlines).toHaveLength(2)
        expect(new Set(deadlines).size).toBe(1)
        expect(deadlines[0] - Date.now()).toBeGreaterThan(0)
        expect(deadlines[0] - Date.now()).toBeLessThanOrEqual(OPTIONS.timeoutMs)
    })

    it('gives up on a redirect chain longer than the limit', async () => {
        fetchStreamedMock.mockResolvedValue(respond(302, { location: '/again.png' }))
        let scheduledRequests = 0

        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            maxRedirects: 2,
            scheduleRequest: async (_url, _deadlineMs, request) => {
                scheduledRequests += 1
                return { ran: true as const, value: await request() }
            },
        })

        expect(result).toMatchObject({
            outcome: 'redirect_continuation',
            redirects: 2,
            status: 302,
            redirectTarget: { url: 'https://cdn.example.com/again.png' },
        })
        // Three requests carry two redirects. The third response is read and refused, and the
        // budget of whatever it points at is never asked for a token.
        expect(fetchStreamedMock).toHaveBeenCalledTimes(3)
        expect(scheduledRequests).toBe(3)
    })

    it('reports a request scheduler that threw rather than letting it escape', async () => {
        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            scheduleRequest: () => Promise.reject(new Error('budget exploded')),
        })

        expect(result).toEqual({
            outcome: 'error',
            redirects: 0,
            currentUrl: 'https://cdn.example.com/a.png',
        })
    })

    it('accepts a Retry-After period of zero as a non-negative integer', async () => {
        fetchStreamedMock.mockResolvedValue(respond(429, { 'retry-after': '0' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result.retryAfterMs).toBe(0)
    })

    it.each([
        ['a negative period', '-5'],
        ['a decimal period', '1.5'],
        ['an exponent', '1e3'],
        ['a signed period', '+5'],
        ['an unsafe period', '9007199254740991'],
        ['whitespace', '   '],
        ['a date already past', new Date(Date.now() - 60_000).toUTCString()],
    ])('reports no Retry-After period for %s, so exponential backoff has no minimum', async (_name, header) => {
        fetchStreamedMock.mockResolvedValue(respond(429, { 'retry-after': header }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result.retryAfterMs).toBeUndefined()
    })

    it.each([
        ['an address the SSRF check refuses', new SecureRequestError('Hostname is not allowed'), 'blocked'],
        ['a name that did not resolve', new ResolutionError('Invalid hostname'), 'error'],
        ['a request that timed out', Object.assign(new Error('timeout'), { name: 'TimeoutError' }), 'timeout'],
        ['a connection that failed', new Error('socket hang up'), 'error'],
    ])('reports %s as an outcome rather than throwing', async (_name, error, outcome) => {
        fetchStreamedMock.mockRejectedValue(error)

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome, redirects: 0, currentUrl: 'https://cdn.example.com/a.png' })
    })
})
