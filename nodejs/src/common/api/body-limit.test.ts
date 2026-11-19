import { randomBytes } from 'crypto'
import supertest from 'supertest'
import express from 'ultimate-express'
import type { Application, Request, Response } from 'ultimate-express'
import { brotliCompressSync, deflateSync, gzipSync } from 'zlib'

import { createTextBodyParser } from '~/common/api/middleware/compressed-body'
import { ModifiedRequest, setupExpressApp } from '~/common/api/router'

const compressors = {
    gzip: gzipSync,
    deflate: deflateSync,
    br: brotliCompressSync,
}
const encodings = Object.keys(compressors) as (keyof typeof compressors)[]

const echoText = (req: Request, res: Response) => {
    res.status(200).json({ body: req.body })
}

describe('setupExpressApp request body handling', () => {
    let app: Application
    let server: ReturnType<Application['listen']>

    beforeAll(() => {
        app = setupExpressApp({ bodyLimitBytes: 1024, readOnlyPathPrefixes: ['/read-only/'] })
        app.set('body methods', ['DELETE'])
        const echo = (req: Request, res: Response) => {
            res.status(200).json({ body: req.body, rawBody: (req as ModifiedRequest).rawBody })
        }
        app.post('/echo', echo)
        app.delete('/echo', echo)
        app.post('/echo-text', createTextBodyParser(), echoText)
        app.post('/echo-stock-text', express.text(), echoText)
        server = app.listen(0, () => {})
    })

    afterAll(() => {
        // Fire-and-forget close, matching ServerLifecycle.stop — ultimate-express
        // never invokes the close callback, so awaiting it would hang.
        server.close()
    })

    const postBytes = (path: string, headers: Record<string, string>, chunks: Buffer[]) => {
        const req = supertest(app).post(path).set(headers)
        chunks.forEach((chunk) => req.write(chunk))
        return req
    }

    const postEncoded = (path: string, encoding: string, body: Buffer, contentType = 'application/json') =>
        postBytes(
            path,
            { 'Content-Type': contentType, 'Content-Encoding': encoding, 'Content-Length': String(body.length) },
            [body]
        )

    // ultimate-express rejects an oversized body with a plain Error, which the
    // default handler renders as a 500. The Rust ingestion consumer treats 500
    // as retriable, so an oversized batch would retry forever — the 413 tells
    // it to split the payload instead.
    it.each([undefined, 'compress'])(
        'rejects an oversized JSON body with content encoding %p with 413, not 500',
        async (encoding) => {
            const req = supertest(app).post('/echo')
            const res = await (encoding ? req.set('Content-Encoding', encoding) : req).send({ data: 'x'.repeat(2048) })

            expect(res.status).toEqual(413)
            expect(res.body).toEqual({ status: 'error', error: 'Request entity too large' })
        }
    )

    it.each(encodings)('rejects a %s body that decodes past the limit with 413', async (encoding) => {
        const res = await postEncoded(
            '/echo',
            encoding,
            compressors[encoding](JSON.stringify({ data: 'x'.repeat(64 * 1024) }))
        )

        expect(res.status).toEqual(413)
        expect(res.body).toEqual({ status: 'error', error: 'Request entity too large' })
    })

    it.each([
        ['a decoded size of', 100 * 1024, 'with a length', 200, gzipSync('x'.repeat(100 * 1024))],
        ['a decoded size of', 100 * 1024 + 1, 'with a length', 413, gzipSync('x'.repeat(100 * 1024 + 1))],
        ['a sent size over', 100 * 1024, 'with a length', 413, gzipSync(randomBytes(100 * 1024))],
        ['a sent size over', 100 * 1024, 'chunked', 200, gzipSync(randomBytes(100 * 1024))],
        [
            'a sent size over',
            200 * 1024,
            'chunked',
            200,
            Buffer.concat(Array.from({ length: 12 * 1024 }, () => gzipSync(''))),
        ],
    ])(
        'caps compressed text like the default text parser: %s %d bytes sent %s gets %d',
        async (_, __, framing, status, compressed) => {
            const res = await postBytes(
                '/echo-text',
                {
                    'Content-Type': 'text/plain',
                    'Content-Encoding': 'gzip',
                    ...(framing === 'chunked' ? {} : { 'Content-Length': String(compressed.length) }),
                },
                [compressed]
            )

            expect(res.status).toEqual(status)
        }
    )

    it('rejects streamed compressed bytes past the limit with 413 and keeps serving', async () => {
        const res = await postBytes(
            '/echo',
            { 'Content-Type': 'application/json', 'Content-Encoding': 'gzip' },
            Array.from({ length: 4 }, () => randomBytes(1024))
        )

        expect(res.status).toEqual(413)
        expect(res.body).toEqual({ status: 'error', error: 'Request entity too large' })
        const after = await supertest(app).post('/echo').send({ data: 'x' })
        expect(after.status).toEqual(200)
    })

    it('refuses a write to a read-only prefix before parsing its body', async () => {
        const res = await supertest(app)
            .post('/read-only/anything')
            .send({ data: 'x'.repeat(2048) })

        expect(res.status).toEqual(405)
    })

    it.each([
        ['JSON', 'a zero length', '/echo', 'application/json', { 'Content-Length': '0' }, [], { body: {} }],
        ['JSON', 'chunked transfer', '/echo', 'application/json', {}, [], { body: {}, rawBody: '' }],
        ['JSON', 'a length', '/echo', 'application/json', {}, [gzipSync('')], { body: {}, rawBody: '' }],
        ['text', 'a zero length', '/echo-text', 'text/plain', { 'Content-Length': '0' }, [], { body: {} }],
        ['text', 'chunked transfer', '/echo-text', 'text/plain', {}, [], { body: '' }],
        ['text', 'a length', '/echo-text', 'text/plain', {}, [gzipSync('')], { body: '' }],
    ])(
        'passes an empty compressed %s body sent with %s to the route as the base parser did',
        async (_, framing, path, contentType, headers, chunks, expected) => {
            const lengthHeader =
                framing === 'a length' ? { 'Content-Length': String(Buffer.concat(chunks).length) } : {}
            const res = await postBytes(
                path,
                {
                    'Content-Type': contentType,
                    'Content-Encoding': 'gzip',
                    ...(framing === 'chunked transfer' ? { 'Transfer-Encoding': 'chunked' } : {}),
                    ...lengthHeader,
                    ...headers,
                },
                chunks
            )

            expect(res.status).toEqual(200)
            expect(res.body).toEqual(expected)
        }
    )

    it.each([undefined, '', 'identity'])('accepts a JSON body with content encoding %p', async (encoding) => {
        const req = supertest(app).post('/echo')
        const res = await (encoding === undefined ? req : req.set('Content-Encoding', encoding)).send({ data: 'x' })

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: { data: 'x' }, rawBody: '{"data":"x"}' })
    })

    it.each([
        ...encodings.map((encoding) => [encoding, 'application/json'] as const),
        ['gzip', 'application/json; charset=utf-8'] as const,
    ])('decodes a %s body sent as %s and keeps its raw text', async (encoding, contentType) => {
        const res = await postEncoded('/echo', encoding, compressors[encoding]('{"data":"x"}'), contentType)

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: { data: 'x' }, rawBody: '{"data":"x"}' })
    })

    it.each([
        ['gzip', 'text/plain', gzipSync('héllo')],
        ['br', 'text/plain; charset=utf-16le', brotliCompressSync(Buffer.from('héllo', 'utf16le'))],
        ['deflate', 'text/plain; charset=latin1', deflateSync(Buffer.from('héllo', 'latin1'))],
        ['gzip', 'text/plain; note="; CHARSET=utf-32"; charset=utf-8', gzipSync('héllo')],
    ])('decodes a %s body sent as %s for a text route', async (encoding, contentType, body) => {
        const res = await postEncoded('/echo-text', encoding, body, contentType)

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: 'héllo' })
    })

    it('decodes a compressed body on a method the app adds to its body methods', async () => {
        const body = gzipSync('{"data":"x"}')
        const req = supertest(app)
            .delete('/echo')
            .set({
                'Content-Type': 'application/json',
                'Content-Encoding': 'gzip',
                'Content-Length': String(body.length),
            })
        req.write(body)
        const res = await req

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: { data: 'x' }, rawBody: '{"data":"x"}' })
    })

    it.each([
        ...encodings.map((encoding) => [encoding, 'application/json', '/echo'] as const),
        ['gzip', 'text/plain', '/echo-text'] as const,
    ])('answers a malformed %s body sent as %s with 400 and keeps serving', async (encoding, contentType, path) => {
        const res = await postEncoded(path, encoding, Buffer.from('this is not compressed data'), contentType)

        expect(res.status).toEqual(400)
        expect(res.body).toEqual({ status: 'error', error: 'Malformed compressed body' })
        const after = await supertest(app).post('/echo').send({ data: 'x' })
        expect(after.status).toEqual(200)
    })

    it.each([
        ['compress', 'text/plain', '/echo-text', 'Unsupported content encoding'],
        ['constructor', 'text/plain', '/echo-text', 'Unsupported content encoding'],
        ['__proto__', 'text/plain', '/echo-text', 'Unsupported content encoding'],
        ['gzip', 'text/plain; charset=utf-32', '/echo-text', 'Unsupported charset'],
        ['gzip', 'text/plain; charset=utf-32', '/echo-text', 'Unsupported charset', gzipSync('')],
    ])(
        'answers content encoding %s on a %s body with 415 and keeps serving',
        async (encoding, contentType, path, error, body = gzipSync('{"data":"x"}')) => {
            const res = await postEncoded(path, encoding, body, contentType)

            expect(res.status).toEqual(415)
            expect(res.body).toEqual({ status: 'error', error })
            const after = await supertest(app).post('/echo').send({ data: 'x' })
            expect(after.status).toEqual(200)
        }
    )

    it.each([
        ['text/plain', '/echo', 'gzip', gzipSync('héllo')],
        ['application/x-www-form-urlencoded', '/echo', 'gzip', gzipSync('data=x')],
        ['Application/JSON', '/echo', 'gzip', gzipSync('{"data":"x"}')],
        ['application/json ; charset=utf-8', '/echo', 'gzip', gzipSync('{"data":"x"}')],
        ['application/xml', '/echo', 'compress', gzipSync('<data/>')],
        ['application/json', '/echo', 'compress', gzipSync('{"data":"x"}')],
        ['application/json', '/echo', 'constructor', gzipSync('{"data":"x"}')],
        ['application/json', '/echo', '__proto__', gzipSync('{"data":"x"}')],
        ['text/plain', '/echo-stock-text', 'gzip', Buffer.from('this is not compressed data')],
        ['application/octet-stream', '/echo-text', 'gzip', randomBytes(4096)],
    ])(
        'passes a body of type %s sent to %s with content encoding %s as {}, as the base parser did',
        async (contentType, path, encoding, body) => {
            const res = await postEncoded(path, encoding, body, contentType)

            expect(res.status).toEqual(200)
            expect(res.body).toEqual({ body: {} })
            const after = await supertest(app).post('/echo').send({ data: 'x' })
            expect(after.status).toEqual(200)
        }
    )

    it.each([
        ['a length', { 'Content-Length': String(gzipSync('{"data":"x"}').length) }, [gzipSync('{"data":"x"}')]],
        ['chunked transfer', {}, [gzipSync('{"data":"x"}')]],
    ])(
        'passes a compressed body without a content type sent with %s to the route as {}',
        async (_, headers, chunks) => {
            const res = await postBytes('/echo', { 'Content-Encoding': 'gzip', ...headers }, chunks)

            expect(res.status).toEqual(200)
            expect(res.body).toEqual({ body: {} })
        }
    )
})
