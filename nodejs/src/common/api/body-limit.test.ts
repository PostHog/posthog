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

    // superagent JSON-encodes a Buffer sent as application/json, so the identity serializer keeps the bytes as given.
    const postEncoded = (path: string, encoding: string, body: Buffer, contentType = 'application/json') =>
        supertest(app)
            .post(path)
            .set('Content-Type', contentType)
            .set('Content-Encoding', encoding)
            .serialize((data) => data)
            .send(body)

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

    it('refuses a write to a read-only prefix before parsing its body', async () => {
        const res = await supertest(app)
            .post('/read-only/anything')
            .send({ data: 'x'.repeat(2048) })

        expect(res.status).toEqual(405)
    })

    it('accepts a JSON body under the limit', async () => {
        const res = await supertest(app).post('/echo').send({ data: 'x' })

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: { data: 'x' }, rawBody: '{"data":"x"}' })
    })

    it.each(encodings)('decodes a %s JSON body and keeps its raw text', async (encoding) => {
        const res = await postEncoded('/echo', encoding, compressors[encoding]('{"data":"x"}'))

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: { data: 'x' }, rawBody: '{"data":"x"}' })
    })

    it.each(encodings)('decodes a %s text body for a route that reads text', async (encoding) => {
        const res = await postEncoded('/echo-text', encoding, compressors[encoding]('hello'), 'text/plain')

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ body: 'hello' })
    })

    it.each(encodings)('answers a malformed %s body with 400 and keeps serving', async (encoding) => {
        const res = await postEncoded('/echo', encoding, Buffer.from('this is not compressed data'))

        expect(res.status).toEqual(400)
        expect(res.body).toEqual({ status: 'error', error: 'Malformed compressed body' })
        const after = await supertest(app).post('/echo').send({ data: 'x' })
        expect(after.status).toEqual(200)
    })

    it('answers an unsupported content encoding with 415', async () => {
        const res = await postEncoded('/echo', 'compress', Buffer.from('{"data":"x"}'))

        expect(res.status).toEqual(415)
        expect(res.body).toEqual({ status: 'error', error: 'Unsupported content encoding' })
    })
})
