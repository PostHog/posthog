/**
 * `handleMetricsRequest` — the shared scrape handler backing both the dedicated
 * prod server and the dev same-port mount. It must serve only the metrics paths
 * (GET /metrics + /_metrics) and otherwise report "not handled" so the caller
 * falls through to its own routing.
 */

import type { IncomingMessage, ServerResponse } from 'node:http'
import { describe, expect, it } from 'vitest'

import type { Logger } from './logger'
import { handleMetricsRequest } from './metrics'

const log = { error: () => {} } as unknown as Logger

function fakeReqRes(
    method: string,
    url: string
): {
    req: IncomingMessage
    res: ServerResponse & { statusCode: number; headers: Record<string, unknown>; body?: unknown }
    ended: Promise<void>
} {
    let resolveEnd!: () => void
    const ended = new Promise<void>((r) => {
        resolveEnd = r
    })
    const res = {
        statusCode: 0,
        headers: {} as Record<string, unknown>,
        body: undefined as unknown,
        writeHead(status: number, headers?: Record<string, unknown>) {
            this.statusCode = status
            this.headers = headers ?? {}
            return this
        },
        end(body?: unknown) {
            this.body = body
            resolveEnd()
        },
    }
    return { req: { method, url } as IncomingMessage, res: res as never, ended }
}

describe('handleMetricsRequest', () => {
    it.each(['/metrics', '/_metrics', '/metrics?foo=bar'])('serves GET %s', async (url) => {
        const { req, res, ended } = fakeReqRes('GET', url)
        expect(handleMetricsRequest(req, res, log)).toBe(true)
        await ended
        expect(res.statusCode).toBe(200)
        expect(String(res.headers['content-type'])).toContain('text/plain')
        expect(typeof res.body).toBe('string')
    })

    it.each([
        ['GET', '/healthz'],
        ['GET', '/'],
        ['POST', '/metrics'],
    ])('does not handle %s %s (returns false, leaves res untouched)', (method, url) => {
        const { req, res } = fakeReqRes(method, url)
        expect(handleMetricsRequest(req, res, log)).toBe(false)
        expect(res.statusCode).toBe(0)
        expect(res.body).toBeUndefined()
    })
})
