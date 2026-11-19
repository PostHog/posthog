import { randomBytes } from 'crypto'
import supertest from 'supertest'
import express from 'ultimate-express'
import type { Application, Request, Response } from 'ultimate-express'
import { brotliCompressSync, deflateSync, gzipSync } from 'zlib'

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
        app.post('/echo-text', express.text(), echoText)
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
    it('rejects an oversized JSON body with 413, not 500', async () => {
        const res = await supertest(app)
            .post('/echo')
            .send({ data: 'x'.repeat(2048) })

        expect(res.status).toEqual(413)
        expect(res.body).toEqual({ status: 'error', error: 'Request entity too large' })
    })

    it.each(encodings)('rejects a %s body that decodes past the limit with 413', async (encoding) => {
        const res = await postEncoded(
            '/echo',
            encoding,
            compressors[encoding](JSON.stringify({ data: 'x'.repeat(64 * 1024) }))
        )

        expect(res.status).toEqual(413)
        expect(res.body).toEqual({ status: 'error', error: 'Request entity too large' })
    })

    it('rejects a compressed text body that decodes past the limit with 413', async () => {
        const res = await postEncoded('/echo-text', 'gzip', gzipSync('x'.repeat(4096)), 'text/plain')

        expect(res.status).toEqual(413)
        expect(res.body).toEqual({ status: 'error', error: 'Request entity too large' })
    })

    it.each([
        ['decoded', 100 * 1024, 200, gzipSync('x'.repeat(100 * 1024))],
        ['decoded', 100 * 1024 + 1, 413, gzipSync('x'.repeat(100 * 1024 + 1))],
        ['sent', 100 * 1024 + 1, 413, gzipSync(randomBytes(100 * 1024))],
    ])(
        'caps compressed text at the default text parser limit: %s size %d gets %d',
        async (_, __, status, compressed) => {
            const wideApp = setupExpressApp({ bodyLimitBytes: 1024 * 1024 })
            wideApp.post('/echo-text', express.text(), echoText)
            const wideServer = wideApp.listen(0, () => {})
            try {
                const req = supertest(wideApp)
                    .post('/echo-text')
                    .set({
                        'Content-Type': 'text/plain',
                        'Content-Encoding': 'gzip',
                        'Content-Length': String(compressed.length),
                    })
                req.write(compressed)
                const res = await req

                expect(res.status).toEqual(status)
            } finally {
                wideServer.close()
            }
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
        ['a zero length', { 'Content-Length': '0' }],
        ['chunked transfer', { 'Transfer-Encoding': 'chunked' }],
    ])('passes an empty compressed JSON body sent with %s to the route as {}', async (_, headers) => {
        const res = await postBytes(
            '/echo',
            { 'Content-Type': 'application/json', 'Content-Encoding': 'gzip', ...headers },
            []
        )

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: {} })
    })

    it.each([undefined, '', 'identity'])('accepts a JSON body with content encoding %p', async (encoding) => {
        const req = supertest(app).post('/echo')
        const res = await (encoding === undefined ? req : req.set('Content-Encoding', encoding)).send({ data: 'x' })

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: { data: 'x' }, rawBody: '{"data":"x"}' })
    })

    it.each([
        ...encodings.map((encoding) => [encoding, 'application/json'] as const),
        ['gzip', 'Application/JSON'] as const,
        ['gzip', 'application/json ; charset=utf-8'] as const,
    ])('decodes a %s body sent as %s and keeps its raw text', async (encoding, contentType) => {
        const res = await postEncoded('/echo', encoding, compressors[encoding]('{"data":"x"}'), contentType)

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: { data: 'x' }, rawBody: '{"data":"x"}' })
    })

    it.each([
        ['gzip', 'text/plain', gzipSync('héllo')],
        ['br', 'Text/Plain; charset=utf-16le', brotliCompressSync(Buffer.from('héllo', 'utf16le'))],
        ['deflate', 'text/plain; charset=latin1', deflateSync(Buffer.from('héllo', 'latin1'))],
        ['gzip', 'text/plain; note="; CHARSET=utf-32"; charset=utf-8', gzipSync('héllo')],
    ])('decodes a %s body sent as %s for a text route', async (encoding, contentType, body) => {
        const res = await postEncoded('/echo-text', encoding, body, contentType)

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: 'héllo' })
    })

    it('answers an empty chunked compressed text body with 400', async () => {
        const res = await postBytes(
            '/echo-text',
            { 'Content-Type': 'text/plain', 'Content-Encoding': 'gzip', 'Transfer-Encoding': 'chunked' },
            []
        )

        expect(res.status).toEqual(400)
        expect(res.body).toEqual({ status: 'error', error: 'Malformed compressed body' })
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
        ['compress', 'application/json', gzipSync('{"data":"x"}'), 'Unsupported content encoding'],
        ['constructor', 'application/json', gzipSync('{"data":"x"}'), 'Unsupported content encoding'],
        ['__proto__', 'application/json', gzipSync('{"data":"x"}'), 'Unsupported content encoding'],
        ['gzip', 'application/octet-stream', gzipSync('{"data":"x"}'), 'Unsupported content encoding'],
        ['gzip', 'application/octet-stream', randomBytes(4096), 'Unsupported content encoding'],
        ['gzip', 'text/plain; charset=utf-32', gzipSync('hello'), 'Unsupported charset'],
    ])(
        'answers content encoding %s on a %s body with 415 and keeps serving',
        async (encoding, contentType, body, error) => {
            const res = await postEncoded('/echo-text', encoding, body, contentType)

            expect(res.status).toEqual(415)
            expect(res.body).toEqual({ status: 'error', error })
            const after = await supertest(app).post('/echo').send({ data: 'x' })
            expect(after.status).toEqual(200)
        }
    )

    it.each([
        ['a length', { 'Content-Length': String(gzipSync('{"data":"x"}').length) }, [gzipSync('{"data":"x"}')]],
        ['chunked transfer', {}, [gzipSync('{"data":"x"}')]],
        ['a zero length', { 'Content-Length': '0' }, []],
        ['empty chunked transfer', { 'Transfer-Encoding': 'chunked' }, []],
    ])('answers a compressed body without a content type sent with %s with 415', async (_, headers, chunks) => {
        const res = await postBytes('/echo', { 'Content-Encoding': 'gzip', ...headers }, chunks)

        expect(res.status).toEqual(415)
        expect(res.body).toEqual({ status: 'error', error: 'Unsupported content encoding' })
    })
})
