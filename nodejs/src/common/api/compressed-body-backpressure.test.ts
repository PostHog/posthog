import { execFileSync } from 'child_process'
import { closeSync, mkdtempSync, openSync, rmSync } from 'fs'
import { open } from 'fs/promises'
import http from 'http'
import { tmpdir } from 'os'
import path from 'path'
import supertest from 'supertest'
import type { Application, Request, Response } from 'ultimate-express'
import { brotliCompressSync, deflateSync, gzipSync } from 'zlib'

import { setupExpressApp } from '~/common/api/router'

describe('setupExpressApp compressed uploads while decoding is held up', () => {
    let app: Application
    let server: ReturnType<Application['listen']>
    const routedBodies: unknown[] = []

    beforeAll(() => {
        app = setupExpressApp({ jsonBodyLimitBytes: 1024 })
        app.post('/echo', (req: Request, res: Response) => {
            routedBodies.push(req.body)
            res.status(200).json({ body: req.body })
        })
        server = app.listen(0, () => {})
    })

    beforeEach(() => {
        routedBodies.length = 0
    })

    afterAll(() => {
        server.close()
    })

    const threadpoolSize = Number(process.env.UV_THREADPOOL_SIZE ?? 4)

    const holdThreadpool = (threads = threadpoolSize) => {
        const directory = mkdtempSync(path.join(tmpdir(), 'held-threadpool-'))
        const fifo = path.join(directory, 'fifo')
        execFileSync('mkfifo', [fifo])
        const heldOpens = Array.from({ length: threads }, () => open(fifo, 'r'))
        return async () => {
            const writer = openSync(fifo, 'w')
            await Promise.all(heldOpens.map(async (heldOpen) => (await heldOpen).close()))
            closeSync(writer)
            rmSync(directory, { recursive: true })
        }
    }

    const openUpload = (encoding = 'gzip') =>
        http.request({
            host: '127.0.0.1',
            port: (app as Application & { port: number }).port,
            path: '/echo',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Encoding': encoding,
                'Transfer-Encoding': 'chunked',
            },
        })

    const responseOf = (req: http.ClientRequest) =>
        new Promise<{ status: number | undefined; body: string }>((resolve) => {
            req.on('response', (res) => {
                const chunks: Buffer[] = []
                res.on('data', (chunk: Buffer) => chunks.push(chunk))
                res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString() }))
            })
        })

    const roundTrip = () => supertest(app).post('/echo').send({ data: 'round trip' })

    it('stops reading a compressed upload while decoding is held up', async () => {
        const emptyMember = gzipSync('')
        const chunk = Buffer.concat(Array(Math.floor((64 * 1024) / emptyMember.length)).fill(emptyMember))
        const chunkCount = 1024
        const releaseThreadpool = holdThreadpool()
        const req = openUpload()
        const status = new Promise<number | undefined>((resolve) => {
            req.on('response', (res) => {
                res.resume()
                resolve(res.statusCode)
            })
        })

        let flushedChunks = 0
        let writing = true
        const writeNextChunk = (): void => {
            if (writing && flushedChunks < chunkCount) {
                req.write(chunk, () => {
                    flushedChunks++
                    writeNextChunk()
                })
            }
        }
        let outcome: 'stalled' | 'flushed' | 'undecided'
        try {
            outcome = await new Promise((resolve) => {
                writeNextChunk()
                let polls = 0
                let lastFlushed = -1
                let pollsWithoutProgress = 0
                const poll = setInterval(() => {
                    polls++
                    pollsWithoutProgress = flushedChunks === lastFlushed ? pollsWithoutProgress + 1 : 0
                    lastFlushed = flushedChunks
                    const decided =
                        flushedChunks === chunkCount ? 'flushed' : pollsWithoutProgress >= 25 ? 'stalled' : undefined
                    if (decided || polls >= 500) {
                        clearInterval(poll)
                        writing = false
                        resolve(decided ?? 'undecided')
                    }
                }, 20)
            })
        } finally {
            await releaseThreadpool()
        }
        req.end()

        expect(await status).toEqual(200)
        expect(outcome).toEqual('stalled')
    }, 30000)

    it.each([
        ['deflate', deflateSync],
        ['br', brotliCompressSync],
    ] as const)('passes a decoded %s body to the route only once the upload ends', async (encoding, compress) => {
        const releaseThreadpool = holdThreadpool(threadpoolSize - 1)
        try {
            const upload = openUpload(encoding)
            const response = responseOf(upload)
            let responded = false
            void response.then(() => (responded = true))
            upload.write(Buffer.concat([compress(JSON.stringify({ data: 'x' })), Buffer.from('x')]))
            await roundTrip()
            const later = openUpload()
            const laterResponse = responseOf(later)
            later.end(gzipSync(JSON.stringify({ data: 'later' })))
            expect((await laterResponse).status).toEqual(200)
            await roundTrip()

            expect(responded).toBe(false)
            upload.end()
            expect(await response).toEqual({ status: 200, body: JSON.stringify({ body: { data: 'x' } }) })
        } finally {
            await releaseThreadpool()
        }
    })

    it('drops a compressed body whose client disconnects while it is decoding', async () => {
        const releaseThreadpool = holdThreadpool()
        try {
            const req = openUpload()
            req.on('error', () => {})
            req.end(gzipSync(JSON.stringify({ data: 'x' })))
            await roundTrip()
            req.destroy()
            await roundTrip()
        } finally {
            await releaseThreadpool()
        }
        for (let index = 0; index < 5; index++) {
            await roundTrip()
        }

        expect(routedBodies).not.toContainEqual({ data: 'x' })
    })
})
