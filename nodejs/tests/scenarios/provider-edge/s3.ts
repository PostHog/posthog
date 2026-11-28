import http from 'http'
import { AddressInfo } from 'net'
import { Readable, Transform, Writable, pipeline } from 'stream'

import { Hit, S3Answer, S3Op } from './faults'

const PACE_SLICES_PER_SECOND = 10

export type S3Faults = {
    takeS3(op: S3Op, hit: Hit): { id: string; answer: S3Answer } | undefined
    s3Answered(id: string): void
    s3Abandoned(id: string): void
}

export type S3Proxy = { url: string; close(): Promise<void> }

function opOf(req: http.IncomingMessage): S3Op | undefined {
    switch (req.method) {
        case 'GET':
            return 'get'
        case 'HEAD':
            return 'head'
        case 'PUT':
            return req.headers['x-amz-copy-source'] ? 'copy' : 'put'
        default:
            return undefined
    }
}

export function paced(bytesPerSecond: number, onDelay: () => void): Transform {
    const sliceBytes = Math.max(1, Math.floor(bytesPerSecond / PACE_SLICES_PER_SECOND))
    let pending: NodeJS.Timeout | undefined
    return new Transform({
        transform(chunk: Buffer, _encoding, done) {
            const slices: Buffer[] = []
            for (let at = 0; at < chunk.length; at += sliceBytes) {
                slices.push(chunk.subarray(at, at + sliceBytes))
            }
            const next = (): void => {
                const slice = slices.shift()
                if (slice === undefined) {
                    pending = undefined
                    done()
                    return
                }
                onDelay()
                pending = setTimeout(
                    () => {
                        this.push(slice)
                        next()
                    },
                    (slice.length / bytesPerSecond) * 1000
                )
            }
            next()
        },
        destroy(error, done) {
            clearTimeout(pending)
            done(error)
        },
    })
}

type Pace = { bytesPerSecond: number; onDelay: () => void }

const carry = (from: Readable, to: Writable, pace: Pace | undefined): void => {
    // pipeline throws, outside any handler, into a stream that closed already, which would take the whole edge down.
    if (to.destroyed) {
        from.destroy()
        return
    }
    if (pace === undefined) {
        pipeline(from, to, () => undefined)
    } else {
        pipeline(from, paced(pace.bytesPerSecond, pace.onDelay), to, () => undefined)
    }
}

function serverError(res: http.ServerResponse, status: number, method: string | undefined): void {
    const code = status === 503 ? 'SlowDown' : 'InternalError'
    res.writeHead(status, { 'content-type': 'application/xml' })
    res.end(
        method === 'HEAD'
            ? undefined
            : `<?xml version="1.0" encoding="UTF-8"?><Error><Code>${code}</Code><Message>The edge answered ${status}</Message></Error>`
    )
}

function forward(upstream: URL, req: http.IncomingMessage, res: http.ServerResponse, pace: Pace | undefined): void {
    const outbound = http.request(
        { hostname: upstream.hostname, port: upstream.port, method: req.method, path: req.url, headers: req.headers },
        (answer) => {
            res.writeHead(answer.statusCode ?? 502, answer.headers)
            carry(answer, res, pace)
        }
    )
    outbound.on('error', () => res.destroy())
    res.once('close', () => {
        if (!res.writableFinished) {
            outbound.destroy()
        }
    })
    carry(req, outbound, pace)
}

export async function startS3Proxy(upstream: string, faults: S3Faults): Promise<S3Proxy> {
    const target = new URL(upstream)
    // The proxy forwards each signed request as it came, Host and path included, so it reaches only a plain HTTP store
    // that serves buckets from its root, as the dev stack's does.
    if (target.protocol !== 'http:' || target.pathname !== '/') {
        throw new Error(
            `the S3 edge forwards only to a plain HTTP store at its root, not to ${target.origin}${target.pathname}`
        )
    }
    const server = http.createServer((req, res) => {
        const op = opOf(req)
        const taken = op && faults.takeS3(op, { pickKey: (req.url ?? '/').split('?')[0] })
        const answered = (): void => {
            if (taken) {
                faults.s3Answered(taken.id)
            }
        }
        const answer = taken?.answer
        if (taken && (answer?.kind === 's3-status' || answer?.kind === 's3-stall')) {
            req.once('close', () => {
                if (!req.complete) {
                    faults.s3Abandoned(taken.id)
                }
            })
        }
        if (answer?.kind === 's3-status') {
            req.resume().once('end', () => {
                answered()
                serverError(res, answer.status, req.method)
            })
        } else if (answer?.kind === 's3-stall') {
            req.resume().once('end', answered)
        } else {
            forward(
                target,
                req,
                res,
                answer?.kind === 's3-slow' ? { bytesPerSecond: answer.bytesPerSecond, onDelay: answered } : undefined
            )
        }
    })
    await new Promise<void>((resolve, reject) => {
        server.once('error', reject)
        server.listen(0, '127.0.0.1', () => {
            server.off('error', reject)
            resolve()
        })
    })
    const { port } = server.address() as AddressInfo
    return {
        url: `http://127.0.0.1:${port}`,
        close: async () => {
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        },
    }
}
