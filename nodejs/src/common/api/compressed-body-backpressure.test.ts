import { once } from 'events'
import http from 'http'
import type { Application, Request, Response } from 'ultimate-express'
import { setFlagsFromString } from 'v8'
import { runInNewContext } from 'vm'
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

    it('holds a fast compressed upload back while decoding catches up', async () => {
        setFlagsFromString('--expose-gc')
        const gc = runInNewContext('gc') as () => void
        const emptyMember = gzipSync('')
        const emptyMembers = Buffer.concat(Array(Math.floor((4 * 1024 * 1024) / emptyMember.length)).fill(emptyMember))
        const req = http.request({
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
        gc()
        const baseline = process.memoryUsage().arrayBuffers
        let peakGrowth = 0
        const sampler = setInterval(() => {
            gc()
            peakGrowth = Math.max(peakGrowth, process.memoryUsage().arrayBuffers - baseline)
        }, 20)

        for (let sent = 0; sent < 64 * 1024 * 1024; sent += emptyMembers.length) {
            if (!req.write(emptyMembers)) {
                await once(req, 'drain')
            }
        }
        req.end()
        const statusCode = await status
        clearInterval(sampler)

        expect(statusCode).toEqual(200)
        expect(peakGrowth).toBeLessThan(32 * 1024 * 1024)
    })
})
