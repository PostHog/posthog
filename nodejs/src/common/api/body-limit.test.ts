import supertest from 'supertest'
import type { Application, Request, Response } from 'ultimate-express'
import { brotliCompressSync, deflateSync, gzipSync } from 'zlib'

import { setupExpressApp } from '~/common/api/router'

describe('setupExpressApp JSON body limit', () => {
    let app: Application
    let server: ReturnType<Application['listen']>

    beforeAll(() => {
        app = setupExpressApp({ jsonBodyLimit: '1kb', readOnlyPathPrefixes: ['/read-only/'] })
        app.post('/echo', (req: Request, res: Response) => {
            res.status(200).json({ ok: true })
        })
        app.post('/body', (req: Request, res: Response) => {
            res.status(200).json(req.body)
        })
        server = app.listen(0, () => {})
    })

    afterAll(() => {
        // Fire-and-forget close, matching ServerLifecycle.stop — ultimate-express
        // never invokes the close callback, so awaiting it would hang.
        server.close()
    })

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

    it('refuses a write to a read-only prefix before parsing its body', async () => {
        const res = await supertest(app)
            .post('/read-only/anything')
            .send({ data: 'x'.repeat(2048) })

        expect(res.status).toEqual(405)
    })

    it('accepts a JSON body under the limit', async () => {
        const res = await supertest(app).post('/echo').send({ data: 'x' })

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ ok: true })
    })

    it.each([
        ['gzip', gzipSync],
        ['deflate', deflateSync],
        ['br', brotliCompressSync],
    ] as const)('parses a %s JSON body and answers a malformed one with 400', async (encoding, compress) => {
        const post = (body: Buffer) => {
            const req = supertest(app)
                .post('/body')
                .set({ 'Content-Type': 'application/json', 'Content-Encoding': encoding })
            req.write(body)
            return req
        }

        const valid = await post(compress(JSON.stringify({ data: 'x' })))
        const malformed = await post(Buffer.from('this is not compressed data'))
        const next = await supertest(app).post('/echo').send({ data: 'x' })

        expect({ valid: [valid.status, valid.body], malformed: malformed.status, next: next.status }).toEqual({
            valid: [200, { data: 'x' }],
            malformed: 400,
            next: 200,
        })
    })
})
