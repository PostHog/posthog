import { Readable } from 'node:stream'
// eslint-disable-next-line no-restricted-imports
import { request } from 'undici'

import { InvalidRequestError, fetchStreamed } from './request'

jest.mock('undici', () => ({
    ...jest.requireActual('undici'),
    request: jest.fn(),
}))

const requestMock = request as jest.MockedFunction<typeof request>

function respond(chunks: Buffer[], headers: Record<string, string> | string[] = {}): void {
    requestMock.mockResolvedValue({
        statusCode: 200,
        headers,
        body: Readable.from(chunks),
    } as unknown as Awaited<ReturnType<typeof request>>)
}

describe('fetchStreamed', () => {
    beforeEach(() => {
        requestMock.mockReset()
    })

    it('returns a body that fits the limit', async () => {
        respond([Buffer.from('abc'), Buffer.from('de')])

        const response = await fetchStreamed('https://example.com/a.png', { timeoutMs: 1000 })
        const { bytes, overLimit } = await response.read(10)

        expect(overLimit).toBe(false)
        expect(bytes.toString()).toBe('abcde')
    })

    it.each([
        ['one chunk already past it', [Buffer.alloc(20)]],
        ['several chunks that cross it together', [Buffer.alloc(4), Buffer.alloc(4), Buffer.alloc(4)]],
    ])('abandons a body that passes the limit as %s', async (_name, chunks) => {
        // The limit has to bind on what has arrived rather than on a declared size, because an
        // origin can declare nothing and send gigabytes.
        respond(chunks)

        const response = await fetchStreamed('https://example.com/a.png', { timeoutMs: 1000 })
        const { bytes, overLimit } = await response.read(10)

        expect(overLimit).toBe(true)
        expect(bytes).toHaveLength(10)
    })

    it('can discard a capped prefix that its caller will not parse', async () => {
        respond([Buffer.alloc(8), Buffer.alloc(8)])

        const response = await fetchStreamed('https://example.com/a.png', { timeoutMs: 1000 })
        const { bytes, overLimit } = await response.read(10, false)

        expect(overLimit).toBe(true)
        expect(bytes).toHaveLength(0)
    })

    it.each([
        ['exactly its declared length', 5],
        ['less than it declared', 10],
        ['more than it declared', 3],
    ])('ignores a Content-Length that is %s', async (_name, declared) => {
        // Content-Length is a claim, not a fact. Only the caller's limit binds, and it binds on the
        // bytes that arrive.
        respond([Buffer.from('abcde')], { 'content-length': String(declared) })

        const response = await fetchStreamed('https://example.com/a.png', { timeoutMs: 1000 })
        const { bytes, overLimit } = await response.read(100)

        expect(overLimit).toBe(false)
        expect(bytes.toString()).toBe('abcde')
    })

    it('reads no body after the response was discarded', async () => {
        respond([Buffer.from('abc')])

        const response = await fetchStreamed('https://example.com/a.png', { timeoutMs: 1000 })
        response.discard()
        const { bytes } = await response.read(10)

        expect(bytes).toHaveLength(0)
    })

    it('does not let a header named __proto__ reach the prototype', async () => {
        // The remote server chooses every key here. The key is computed, because a plain `__proto__:`
        // in a literal is the setter this test is about rather than an own property.
        respond([], { ['__proto__']: 'polluted', 'content-type': 'image/png' })

        const response = await fetchStreamed('https://example.com/a.png', { timeoutMs: 1000 })
        response.discard()

        expect(response.headers['__proto__']).toBe('polluted')
        expect(({} as Record<string, unknown>)['polluted']).toBeUndefined()
        expect(Object.getPrototypeOf(response.headers)).toBeNull()
    })

    it('preserves repeated response field lines in their received order', async () => {
        respond([], ['X-Robots-Tag', 'index', 'Content-Type', 'image/png', 'X-Robots-Tag', 'noai'])

        const response = await fetchStreamed('https://example.com/a.png', { timeoutMs: 1000 })
        response.discard()

        expect(response.headerLines).toEqual([
            { name: 'x-robots-tag', value: 'index' },
            { name: 'content-type', value: 'image/png' },
            { name: 'x-robots-tag', value: 'noai' },
        ])
        expect(requestMock).toHaveBeenCalledWith(
            'https://example.com/a.png',
            expect.objectContaining({ responseHeaders: 'raw' })
        )
    })

    it.each([['ftp://example.com/a.png'], ['not a url']])('refuses %s before opening a socket', async (url) => {
        await expect(fetchStreamed(url, { timeoutMs: 1000 })).rejects.toThrow(InvalidRequestError)

        expect(requestMock).not.toHaveBeenCalled()
    })
})
