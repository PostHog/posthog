import supertest from 'supertest'
import type { Application, Request, Response } from 'ultimate-express'

import { setupExpressApp } from '~/common/api/router'

describe('setupExpressApp JSON body limit', () => {
    let app: Application
    let server: ReturnType<Application['listen']>

    beforeAll(() => {
        app = setupExpressApp({ jsonBodyLimit: '1kb' })
        app.post('/echo', (req: Request, res: Response) => {
            res.status(200).json({ ok: true })
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

    it('accepts a JSON body under the limit', async () => {
        const res = await supertest(app).post('/echo').send({ data: 'x' })

        expect(res.status).toEqual(200)
        expect(res.body).toEqual({ ok: true })
    })
})
