/* eslint-disable no-console -- sidecar logs to stdout */
import express, { type NextFunction, type Request, type Response } from 'express'
import { type Server } from 'node:http'

import { UndecodableImageError, blurOnly } from './blur.ts'
import { ScrubMetrics, register } from './metrics.ts'

class ConsumerHungUpError extends Error {}

async function scrub(input: Buffer, signal: AbortSignal): Promise<Buffer> {
    if (signal.aborted) {
        throw new ConsumerHungUpError()
    }
    return blurOnly(input)
}

export interface SidecarServers {
    // /scrub, bound to loopback — the pod IP must never expose it.
    scrub: Server
    // /metrics + health, bound to all interfaces so Prometheus and the kubelet can reach the pod IP.
    metrics: Server
}

export function startServer(
    port: number,
    metricsPort: number,
    maxConcurrency: number,
    maxBodyBytes: number
): SidecarServers {
    let inFlight = 0
    const app = express()
    app.disable('x-powered-by')
    app.disable('etag')

    const shedIfBusy = (_req: Request, res: Response, next: NextFunction): void => {
        if (inFlight >= maxConcurrency) {
            ScrubMetrics.incRejected()
            res.status(503).send('busy')
            return
        }
        inFlight += 1
        let released = false
        const release = (): void => {
            if (!released) {
                released = true
                inFlight -= 1
            }
        }
        res.locals.release = release
        // Release when the scrub work settles (in the handler below), not merely when the connection closes:
        // an aborted request whose sharp op is still running must keep its slot so it counts against the
        // ceiling. Exits that never start scrub (413 too-large, bodyless 422) release here on close.
        res.once('close', () => {
            if (!res.locals.scrubStarted) {
                release()
            }
        })
        next()
    }

    app.post('/scrub', shedIfBusy, express.raw({ type: () => true, limit: maxBodyBytes }), (req, res, next) => {
        const body = req.body
        if (!Buffer.isBuffer(body)) {
            next(new UndecodableImageError('request body is not image bytes'))
            return
        }
        res.locals.scrubStarted = true
        const stopTimer = ScrubMetrics.startTimer()
        const controller = new AbortController()
        res.on('close', () => {
            if (!res.writableEnded) {
                controller.abort()
            }
        })
        res.on('error', () => {})
        scrub(body, controller.signal)
            .then((out) => {
                if (controller.signal.aborted) {
                    ScrubMetrics.incAborted()
                    return
                }
                ScrubMetrics.incScrubbed()
                ScrubMetrics.observeOutputBytes(out.length)
                res.set('Content-Type', 'application/octet-stream').send(out)
            })
            .catch(next)
            .finally(() => {
                stopTimer()
                ;(res.locals.release as () => void)()
            })
    })

    app.use((err: Error & { status?: number; type?: string }, _req: Request, res: Response, _next: NextFunction) => {
        if (err instanceof ConsumerHungUpError) {
            ScrubMetrics.incAborted()
            return
        }
        // Already responded, or the socket died after a partial success write: don't double-count as failed.
        if (res.writableEnded || !res.writable) {
            return
        }
        // express.raw over-limit lands here as 413: permanent, the consumer skips it.
        if (err.status === 413 || err.type === 'entity.too.large') {
            ScrubMetrics.incTooLarge()
            res.status(413).send('body too large')
            return
        }
        if (err instanceof UndecodableImageError) {
            ScrubMetrics.incUndecodable()
            res.status(422).send('undecodable image')
            return
        }
        ScrubMetrics.incFailed()
        console.error(`scrub failed: ${String(err)}`)
        res.status(500).send('scrub failed')
    })

    // Loopback only: the consumer shares the pod netns; the pod IP must not expose /scrub.
    const scrubServer = app.listen(port, '127.0.0.1', () =>
        console.log(`image-scrub sidecar listening on 127.0.0.1:${port} (maxConcurrency ${maxConcurrency})`)
    )

    // Observability lives on its own listener bound to all interfaces: Prometheus scrapes the pod IP, which the
    // loopback /scrub listener above deliberately can't answer. It exposes no image bytes, only counters + probes.
    const obs = express()
    obs.disable('x-powered-by')
    obs.disable('etag')
    obs.get(['/_health', '/_ready'], (_req, res) => {
        res.status(200).send('ok')
    })
    obs.get('/metrics', (_req, res, next) => {
        register
            .metrics()
            .then((body) => res.set('Content-Type', register.contentType).send(body))
            .catch(next)
    })
    const metricsServer = obs.listen(metricsPort, '0.0.0.0', () =>
        console.log(`image-scrub sidecar metrics listening on 0.0.0.0:${metricsPort}`)
    )

    for (const server of [scrubServer, metricsServer]) {
        server.on('error', (err) => {
            console.error(`image-scrub sidecar server error: ${String(err)}`)
            process.exit(1)
        })
    }
    return { scrub: scrubServer, metrics: metricsServer }
}
