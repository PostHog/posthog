/**
 * Unit tests for the ingress error-handling middleware. The per-route tests
 * in `server.test.ts` cover the integration; these tests exercise the
 * typed-branch translations of `errorHandler` directly so future routes that
 * reach for `.parse()` (or throw the typed errors directly) are guaranteed
 * to get the structured response.
 */

import express, { Request, Response, Router } from 'express'
import request from 'supertest'
import { z } from 'zod'

import { createLogger } from '@posthog/agent-shared'
import type { Logger } from '@posthog/agent-shared'

import { asyncHandler, errorHandler, redactUrl, requestLogger } from './http-utils'
import { AmbiguousRevisionError } from './resolver'

function buildHarness(routes: (r: Router) => void): express.Express {
    const app = express()
    app.use(express.json())
    const r = Router()
    routes(r)
    app.use(r)
    app.use(errorHandler(createLogger('test')))
    return app
}

describe('errorHandler', () => {
    it('translates a ZodError thrown inside an async route into a structured 400', async () => {
        // A future route reaching for `.parse()` instead of `.safeParse()`
        // throws ZodError; the global middleware should still respond cleanly.
        const Schema = z.object({ name: z.string().min(1) })
        const app = buildHarness((r) => {
            r.post(
                '/parse',
                asyncHandler(async (req: Request, res: Response) => {
                    const parsed = Schema.parse(req.body)
                    res.json(parsed)
                })
            )
        })
        const res = await request(app).post('/parse').send({ name: '' })
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_request')
        expect(res.body.issues[0].path).toEqual(['name'])
        expect(res.body.issues[0].message).toMatch(/too small|at least 1/i)
    })

    it('translates AmbiguousRevisionError into a 400 with candidate ids', async () => {
        const app = buildHarness((r) => {
            r.get(
                '/ambiguous',
                asyncHandler(async (_req: Request, _res: Response) => {
                    throw new AmbiguousRevisionError('app-uuid', 'abcd', ['rev-1', 'rev-2'])
                })
            )
        })
        const res = await request(app).get('/ambiguous')
        expect(res.status).toBe(400)
        expect(res.body).toMatchObject({
            error: 'ambiguous_revision',
            prefix: 'abcd',
            application_id: 'app-uuid',
            candidates: ['rev-1', 'rev-2'],
        })
    })

    it('translates a malformed JSON body into a 400 invalid_json', async () => {
        const app = buildHarness((r) => {
            r.post('/anything', (_req: Request, res: Response) => res.json({ ok: true }))
        })
        const res = await request(app).post('/anything').set('Content-Type', 'application/json').send('{not valid json')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('invalid_json')
    })

    it('falls back to a JSON 500 for unknown errors', async () => {
        const app = buildHarness((r) => {
            r.get(
                '/boom',
                asyncHandler(async () => {
                    throw new Error('unexpected')
                })
            )
        })
        const res = await request(app).get('/boom')
        expect(res.status).toBe(500)
        expect(res.body).toEqual({ error: 'internal_error' })
    })
})

describe('asyncHandler', () => {
    it('forwards synchronous thrown errors into the global error middleware', async () => {
        // Synchronous throw inside an async function still becomes a rejected
        // promise — asyncHandler should funnel it.
        const app = buildHarness((r) => {
            r.get(
                '/sync-throw',
                asyncHandler(() => {
                    throw new AmbiguousRevisionError('app', 'ab', ['r1', 'r2'])
                })
            )
        })
        const res = await request(app).get('/sync-throw')
        expect(res.status).toBe(400)
        expect(res.body.error).toBe('ambiguous_revision')
    })
})

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

// supertest resolves once the response is received; the server's `finish`
// event fires a microtask later, so let the loop turn before asserting.
function tick(): Promise<void> {
    return new Promise((resolve) => setImmediate(resolve))
}

describe('requestLogger', () => {
    function appWith(log: Logger): express.Express {
        const app = express()
        app.use(requestLogger(log))
        app.get('/healthz', (_req: Request, res: Response) => {
            res.json({ ok: true })
        })
        app.get('/ok', (_req: Request, res: Response) => {
            res.json({ ok: true })
        })
        app.get('/boom', (_req: Request, res: Response) => {
            res.status(500).json({ error: 'x' })
        })
        return app
    }

    function lastRequestLine(records: LogRecord[]): LogRecord | undefined {
        return records.filter((r) => r.msg === 'request').at(-1)
    }

    it('logs one info line per successful request with method, url, status, duration', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/ok')
        await tick()
        const line = lastRequestLine(records)!
        expect(line.level).toBe('info')
        expect(line.obj).toMatchObject({ method: 'GET', url: '/ok', status: 200 })
        expect(typeof line.obj.duration_ms).toBe('number')
        expect(line.obj.duration_ms as number).toBeGreaterThanOrEqual(0)
    })

    it('logs a request_start line at debug', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/ok')
        await tick()
        expect(records.some((r) => r.msg === 'request_start' && r.level === 'debug')).toBe(true)
    })

    it('escalates a 5xx to error', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/boom')
        await tick()
        expect(lastRequestLine(records)!.level).toBe('error')
    })

    it('escalates a 4xx to warn', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/missing') // no route → express 404
        await tick()
        const line = lastRequestLine(records)!
        expect(line.level).toBe('warn')
        expect(line.obj.status).toBe(404)
    })

    it('demotes /healthz probe spam to debug', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/healthz')
        await tick()
        expect(lastRequestLine(records)!.level).toBe('debug')
    })

    it('redacts token / preview_token query params from the logged url', async () => {
        const { records, log } = fakeLogger()
        await request(appWith(log)).get('/ok?session_id=s1&token=phx_secret&preview_token=jwt.secret.val')
        await tick()
        const line = lastRequestLine(records)!
        const url = line.obj.url as string
        expect(url).not.toContain('phx_secret')
        expect(url).not.toContain('jwt.secret.val')
        expect(url).toContain('token=REDACTED')
        expect(url).toContain('preview_token=REDACTED')
        // Non-sensitive params are preserved.
        expect(url).toContain('session_id=s1')
        // request_start (debug) is redacted too.
        const startLine = records.find((r) => r.msg === 'request_start')!
        expect(startLine.obj.url as string).not.toContain('phx_secret')
    })
})

describe('redactUrl', () => {
    it.each([
        ['no query string', '/listen', '/listen'],
        ['no sensitive params', '/listen?session_id=s1', '/listen?session_id=s1'],
    ])('returns the url unchanged when %s', (_label, input, expected) => {
        expect(redactUrl(input)).toBe(expected)
    })

    it('masks token and preview_token values, preserving other params', () => {
        const out = redactUrl('/listen?token=abc&session_id=s1&preview_token=xyz')
        expect(out).toContain('token=REDACTED')
        expect(out).toContain('preview_token=REDACTED')
        expect(out).toContain('session_id=s1')
        expect(out).not.toContain('abc')
        expect(out).not.toContain('xyz')
    })
})
