import { execFileSync } from 'child_process'
import { closeSync, mkdtempSync, openSync, rmSync } from 'fs'
import { open } from 'fs/promises'
import http from 'http'
import { tmpdir } from 'os'
import path from 'path'
import supertest from 'supertest'
import type { Application, Request, Response } from 'ultimate-express'
import { gzipSync } from 'zlib'

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

    const holdThreadpool = () => {
        const directory = mkdtempSync(path.join(tmpdir(), 'held-threadpool-'))
        const fifo = path.join(directory, 'fifo')
        execFileSync('mkfifo', [fifo])
        const heldOpens = Array.from({ length: Number(process.env.UV_THREADPOOL_SIZE ?? 4) }, () => open(fifo, 'r'))
        return async () => {
            closeSync(openSync(fifo, 'w'))
            await Promise.all(heldOpens.map(async (heldOpen) => (await heldOpen).close()))
            rmSync(directory, { recursive: true })
        }
    }

    const openGzipUpload = () =>
        http.request({
            host: '127.0.0.1',
            port: (app as Application & { port: number }).port,
            path: '/echo',
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Content-Encoding': 'gzip', 'Transfer-Encoding': 'chunked' },
        })

    const roundTrip = () => supertest(app).post('/echo').send({ data: 'round trip' })

    it('stops reading a compressed upload while decoding is held up', async () => {
        const emptyMember = gzipSync('')
        const chunk = Buffer.concat(Array(Math.floor((64 * 1024) / emptyMember.length)).fill(emptyMember))
        const chunkCount = 1024
        const releaseThreadpool = holdThreadpool()
        const req = openGzipUpload()
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

    it('drops a compressed body whose client disconnects while it is decoding', async () => {
        const releaseThreadpool = holdThreadpool()
        try {
            const req = openGzipUpload()
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
