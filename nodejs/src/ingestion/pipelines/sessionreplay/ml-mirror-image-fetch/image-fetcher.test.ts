import { ResolutionError, SecureRequestError, StreamedResponse, fetchStreamed } from '~/common/utils/request'

import { HttpImageFetcher, ImageFetchOptions, RedirectPolicy } from './image-fetcher'
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
    isOffsite: () => false,
    authorizeRedirect: () => Promise.resolve('allow' as const),
}

function respond(
    status: number,
    headers: Record<string, string>,
    body: { bytes: Buffer; overLimit: boolean } = { bytes: Buffer.alloc(0), overLimit: false }
): StreamedResponse {
    return {
        status,
        headers,
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

    it('returns the bytes of an image whose payload matches its declared type', async () => {
        fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png; charset=binary'))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toEqual({ outcome: 'ok', status: 200, bytes: PNG, contentType: 'image/png', redirects: 0 })
    })

    it.each([
        ['a type that is not an image', 'text/html', PNG],
        ['a type outside the raster set', 'image/svg+xml', PNG],
        ['a payload that is not the declared format', 'image/gif', PNG],
        ['a payload of the wrong raster format', 'image/png', GIF],
    ])('refuses %s', async (_name, contentType, bytes) => {
        fetchStreamedMock.mockResolvedValue(image(bytes, contentType))

        const result = await fetcher().fetch('https://cdn.example.com/a', OPTIONS)

        expect(result).toMatchObject({ outcome: 'not_image' })
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

    it('follows a redirect and reports how many hops it took', async () => {
        fetchStreamedMock
            .mockResolvedValueOnce(respond(302, { location: '/moved.png' }))
            .mockResolvedValueOnce(image(PNG, 'image/png'))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'ok', redirects: 1 })
        expect(fetchStreamedMock.mock.calls[1][0]).toBe('https://cdn.example.com/moved.png')
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
        ['the target is one this lane never follows', 'https://other.example/a.png', 'refuse' as const],
        ['it leaves HTTP for another scheme', 'javascript:alert(1)', 'allow' as const],
        ['it carries credentials for the next hop', 'https://user:pw@other.example/a.png', 'allow' as const],
        ['it downgrades from HTTPS to plain HTTP', 'http://other.example/a.png', 'allow' as const],
    ])('refuses a redirect when %s', async (_name, location, decision) => {
        fetchStreamedMock.mockResolvedValue(respond(302, { location }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            authorizeRedirect: () => Promise.resolve(decision),
        })

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
            isOffsite: () => true,
        })

        expect(result).toMatchObject({
            outcome: 'redirect_offsite',
            redirectTarget: { url: 'https://img.other.net/a.png', host: 'img.other.net' },
        })
    })

    it('stops at the redirect limit for a target on the same domain', async () => {
        fetchStreamedMock.mockResolvedValue(respond(302, { location: 'https://cdn.example.com/b.png' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', { ...OPTIONS, maxRedirects: 0 })

        expect(result).toMatchObject({ outcome: 'too_many_redirects' })
    })

    it('defers a redirect whose target has no budget left, so nothing is written to the crawl history for it', async () => {
        // `bad_redirect` is terminal. A CDN in cooldown would otherwise suppress every image behind
        // it for the crawl history TTL, because the lane read a momentary budget as a property of
        // the URL.
        fetchStreamedMock.mockResolvedValue(respond(302, { location: 'https://cdn.example.net/a.png' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            authorizeRedirect: () => Promise.resolve('defer' as const),
        })

        expect(result).toMatchObject({ outcome: 'redirect_deferred' })
    })

    it('refuses a response that arrives compressed, under its own outcome', async () => {
        // The byte limit counts bytes on the wire, and a compressed body expands past it. The image
        // may be perfectly good, so the lane must not report it, or record it, as "not an image".
        fetchStreamedMock.mockResolvedValue(image(PNG, 'image/png', { 'content-encoding': 'gzip' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', OPTIONS)

        expect(result).toMatchObject({ outcome: 'unsupported_encoding' })
    })

    it('defers a redirect whose politeness wait would outlive the request', async () => {
        // The wait comes out of this request's clock. A wait that cannot land would report the site
        // as slow when our own budget ran out.
        fetchStreamedMock.mockResolvedValue(respond(302, { location: '/moved.png' }))
        const authorizeRedirect = jest.fn().mockResolvedValue('allow')

        await fetcher().fetch('https://cdn.example.com/a.png', { ...OPTIONS, authorizeRedirect })

        const remainingMs = authorizeRedirect.mock.calls[0][1]
        expect(remainingMs).toBeGreaterThan(0)
        expect(remainingMs).toBeLessThanOrEqual(OPTIONS.timeoutMs)
    })

    it('gives up on a redirect chain longer than the limit', async () => {
        fetchStreamedMock.mockResolvedValue(respond(302, { location: '/again.png' }))
        const authorizeRedirect = jest.fn().mockResolvedValue('allow')

        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            maxRedirects: 2,
            authorizeRedirect,
        })

        expect(result).toEqual({ outcome: 'too_many_redirects', redirects: 2, status: 302 })
        // Three requests carry two redirects. The third response is read and refused, and the
        // budget of whatever it points at is never asked for a token.
        expect(fetchStreamedMock).toHaveBeenCalledTimes(3)
        expect(authorizeRedirect).toHaveBeenCalledTimes(2)
    })

    it('reports a redirect authorizer that threw rather than letting it escape', async () => {
        // The authorizer reaches into the host budget, which the fetcher does not own. A throw there
        // would leave the sibling domains of the batch running while the partition replayed them.
        fetchStreamedMock.mockResolvedValue(respond(302, { location: '/moved.png' }))

        const result = await fetcher().fetch('https://cdn.example.com/a.png', {
            ...OPTIONS,
            authorizeRedirect: () => Promise.reject(new Error('budget exploded')),
        })

        expect(result).toEqual({ outcome: 'error', redirects: 0 })
    })

    it.each([
        ['a period of zero', '0'],
        ['a negative period', '-5'],
        ['whitespace', '   '],
        ['a date already past', new Date(Date.now() - 60_000).toUTCString()],
    ])('reports no Retry-After period for %s, so the caller applies its own default', async (_name, header) => {
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

        expect(result).toEqual({ outcome, redirects: 0 })
    })
})
