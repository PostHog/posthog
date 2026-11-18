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

describe('setupExpressApp request body handling', () => {
    let app: Application
    let server: ReturnType<Application['listen']>

    beforeAll(() => {
        app = setupExpressApp({ bodyLimitBytes: 1024, readOnlyPathPrefixes: ['/read-only/'] })
        app.post('/echo', (req: Request, res: Response) => {
            res.status(200).json({ body: req.body, rawBody: (req as ModifiedRequest).rawBody })
        })
        app.post('/echo-text', express.text(), (req: Request, res: Response) => {
            res.status(200).json({ body: req.body })
        })
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

    it.each([undefined, '', 'identity'])('accepts a JSON body with content encoding %p', async (encoding) => {
        const req = supertest(app).post('/echo')
        const res = await (encoding === undefined ? req : req.set('Content-Encoding', encoding)).send({ data: 'x' })

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: { data: 'x' }, rawBody: '{"data":"x"}' })
    })

    it.each(encodings)('decodes a %s JSON body and keeps its raw text', async (encoding) => {
        const res = await postEncoded('/echo', encoding, compressors[encoding]('{"data":"x"}'))

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: { data: 'x' }, rawBody: '{"data":"x"}' })
    })

    it.each(encodings)('answers a malformed %s body with 400 and keeps serving', async (encoding) => {
        const res = await postEncoded('/echo', encoding, Buffer.from('this is not compressed data'))

        expect(res.status).toEqual(400)
        expect(res.body).toEqual({ status: 'error', error: 'Malformed compressed body' })
        const after = await supertest(app).post('/echo').send({ data: 'x' })
        expect(after.status).toEqual(200)
    })

    it.each([
        ['compress', 'application/json', '/echo'],
        ['constructor', 'application/json', '/echo'],
        ['__proto__', 'application/json', '/echo'],
        ['gzip', 'text/plain', '/echo-text'],
    ])('answers content encoding %s on a %s body with 415 and keeps serving', async (encoding, contentType, path) => {
        const res = await postEncoded(path, encoding, gzipSync('{"data":"x"}'), contentType)

        expect(res.status).toEqual(415)
        expect(res.body).toEqual({ status: 'error', error: 'Unsupported content encoding' })
        const after = await supertest(app).post('/echo').send({ data: 'x' })
        expect(after.status).toEqual(200)
    })
})
