/**
 * Unit tests for the janitor's `requestLogger` access-log middleware — the
 * per-request trace the janitor previously lacked (a route's own
 * `res.status(400)` left nothing to grep). Mirrors the ingress test.
 */

import express, { type Request, type Response } from 'express'
import request from 'supertest'
import { describe, expect, it } from 'vitest'

import type { Logger } from '@posthog/agent-shared'

import { requestLogger } from './http-utils'

interface LogRecord {
    level: 'debug' | 'info' | 'warn' | 'error'
    obj: Record<string, unknown>
    msg: string
}

function fakeLogger(): { records: LogRecord[]; log: Logger } {
    const records: LogRecord[] = []
    const mk =
        (level: LogRecord['level']) =>
        (obj: Record<string, unknown>, msg: string): void => {
            records.push({ level, obj, msg })
        }
    const log = { debug: mk('debug'), info: mk('info'), warn: mk('warn'), error: mk('error') } as unknown as Logger
    return { records, log }
}

const tick = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

function appWith(log: Logger): express.Express {
    const app = express()
    app.use(requestLogger(log))
    app.get('/ok', (_req: Request, res: Response) => {
        res.json({ ok: true })
    })
    app.get('/bad', (_req: Request, res: Response) => {
        res.status(400).json({ error: 'invalid_request' })
    })
    app.get('/boom', (_req: Request, res: Response) => {
        res.status(500).json({ error: 'internal_error' })
    })
    app.get('/healthz', (_req: Request, res: Response) => {
        res.json({ ok: true })
    })
    return app
}

const lastRequestLine = (records: LogRecord[]): LogRecord | undefined =>
    records.filter((r) => r.msg === 'request').at(-1)

describe('janitor requestLogger', () => {
    it('logs one info line per 2xx with method, url, status, duration', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/ok')
        await tick()
        const line = lastRequestLine(records)!
        expect(line.level).toBe('info')
        expect(line.obj).toMatchObject({ method: 'GET', url: '/ok', status: 200 })
        expect(typeof line.obj.duration_ms).toBe('number')
    })

    it('logs a 400 at warn — the case that was previously invisible', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/bad')
        await tick()
        expect(lastRequestLine(records)).toMatchObject({ level: 'warn', obj: { status: 400 } })
    })

    it('logs a 500 at error', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/boom')
        await tick()
        expect(lastRequestLine(records)).toMatchObject({ level: 'error', obj: { status: 500 } })
    })

    it('demotes /healthz probe spam to debug', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/healthz')
        await tick()
        expect(lastRequestLine(records)).toMatchObject({ level: 'debug' })
    })
})
