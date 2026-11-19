import { randomBytes, randomUUID } from 'crypto'
import supertest from 'supertest'
import type { Application, Request, Response } from 'ultimate-express'
import { brotliCompressSync, deflateSync, gzipSync } from 'zlib'

import { setupExpressApp } from '~/common/api/router'
import { defaultConfig } from '~/common/config/config'
import { ServerCommands } from '~/common/utils/commands'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { parseJSON } from '~/common/utils/json-parse'
import { PubSub } from '~/common/utils/pubsub'
import { waitForExpect } from '~/tests/helpers/expectations'
import { RedisPool } from '~/types'

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

        expect({
            valid: [valid.status, valid.body],
            malformed: [malformed.status, malformed.body],
            next: next.status,
        }).toEqual({
            valid: [200, { data: 'x' }],
            malformed: [400, { status: 'error', error: 'Malformed compressed body' }],
            next: 200,
        })
    })

    describe('on the command route', () => {
        let redisPool: RedisPool
        let pubSub: PubSub
        let commandsApp: Application
        let commandsServer: ReturnType<Application['listen']>

        beforeAll(async () => {
            redisPool = createRedisPoolFromConfig({
                connection: { url: defaultConfig.REDIS_URL },
                poolMinSize: 1,
                poolMaxSize: 3,
            })
            pubSub = new PubSub(redisPool)
            await pubSub.start()
            commandsApp = setupExpressApp({})
            commandsApp.use(new ServerCommands(pubSub).router())
            commandsServer = commandsApp.listen(0, () => {})
        })

        afterAll(async () => {
            commandsServer.close()
            await pubSub.stop()
            await redisPool.drain()
            await redisPool.clear()
        })

        it.each([
            ['gzip', gzipSync],
            ['deflate', deflateSync],
        ] as const)(
            'publishes nothing for a %s command that fails its check after earlier chunks decoded',
            async (encoding, compress) => {
                const channel = `compressed-command-${encoding}-${randomUUID()}`
                const subscriber = await redisPool.acquire()
                const published: string[] = []
                subscriber.on('message', (_channel: string, message: string) => published.push(message))
                await subscriber.subscribe(channel)
                const pad = randomBytes(512 * 1024).toString('base64')
                const trailingWhitespace = Buffer.from(
                    randomBytes(2 * 1024 * 1024).map((byte) => ' \t\n\r'.charCodeAt(byte & 3))
                )
                const commandBody = (attempt: string): Buffer =>
                    compress(
                        Buffer.concat([
                            Buffer.from(JSON.stringify({ command: channel, message: { attempt, pad } })),
                            trailingWhitespace,
                        ])
                    )
                const checkFailed = commandBody('check failed')
                checkFailed[checkFailed.length - 1] ^= 0xff
                const post = (body: Buffer) => {
                    const req = supertest(commandsApp)
                        .post('/api/commands')
                        .set({ 'Content-Type': 'application/json', 'Content-Encoding': encoding })
                    req.write(body)
                    return req
                }

                try {
                    const failed = await post(checkFailed)
                    const passed = await post(commandBody('valid'))
                    await waitForExpect(() => expect(published.length).toBeGreaterThan(0))

                    expect({
                        failed: [failed.status, failed.body],
                        passed: [passed.status, passed.body],
                        published: published.map((message) => parseJSON(message).attempt),
                    }).toEqual({
                        failed: [400, { status: 'error', error: 'Malformed compressed body' }],
                        passed: [200, { success: true }],
                        published: ['valid'],
                    })
                } finally {
                    await subscriber.unsubscribe(channel)
                    subscriber.removeAllListeners('message')
                    await redisPool.release(subscriber)
                }
            }
        )
    })
})
