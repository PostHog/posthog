import { execFileSync } from 'child_process'
import { closeSync, mkdtempSync, openSync, rmSync } from 'fs'
import { open } from 'fs/promises'
import http from 'http'
import { tmpdir } from 'os'
import path from 'path'
import type { Application, Request, Response } from 'ultimate-express'
import { gzipSync } from 'zlib'

import { setupExpressApp } from '~/common/api/router'

describe('setupExpressApp compressed upload backpressure', () => {
    let app: Application
    let server: ReturnType<Application['listen']>

    beforeAll(() => {
        app = setupExpressApp({ jsonBodyLimitBytes: 1024 })
        app.post('/echo', (req: Request, res: Response) => {
            res.status(200).json({ body: req.body })
        })
        server = app.listen(0, () => {})
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

    it('stops reading a compressed upload while decoding is held up', async () => {
        const emptyMember = gzipSync('')
        const upload = Buffer.concat(Array(Math.floor((64 * 1024 * 1024) / emptyMember.length)).fill(emptyMember))
        const releaseThreadpool = holdThreadpool()
        const req = http.request({
            host: '127.0.0.1',
            port: (app as Application & { port: number }).port,
            path: '/echo',
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Content-Encoding': 'gzip', 'Transfer-Encoding': 'chunked' },
        })
        const status = new Promise<number | undefined>((resolve) => {
            req.on('response', (res) => {
                res.resume()
                resolve(res.statusCode)
            })
        })

        let flushedWhileHeld: boolean
        try {
            const flushed = new Promise<boolean>((resolve) => req.write(upload, () => resolve(true)))
            const stillHeld = new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 2000))
            flushedWhileHeld = await Promise.race([flushed, stillHeld])
        } finally {
            await releaseThreadpool()
        }
        req.end()

        expect(await status).toEqual(200)
        expect(flushedWhileHeld).toBe(false)
    })
})
