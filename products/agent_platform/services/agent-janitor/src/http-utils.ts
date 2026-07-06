/**
 * Defensive HTTP middleware shared by every janitor route. Mirrors the
 * ingress's `src/routing/http-utils.ts` so both services log + error the same.
 *
 * `requestLogger(log)` — first middleware. One structured line per request on
 * completion, so every call (incl. a 400 from a route's own `res.status(400)`)
 * leaves a trace — there was previously no janitor access log at all.
 *
 * `asyncHandler(fn)` — Express 4 doesn't catch rejections returned from
 * async route handlers; they become `unhandledRejection`. Every async route
 * should be wrapped so its rejection lands in `next(err)`.
 *
 * `errorHandler(log)` — Final express middleware. Maps known error shapes
 * to structured JSON responses (never an express HTML stack trace).
 *
 * Kept local to janitor (rather than promoted to agent-shared) because
 * agent-shared deliberately doesn't depend on express.
 */

import type { NextFunction, Request, RequestHandler, Response } from 'express'
import { ZodError } from 'zod'

import type { Logger } from '@posthog/agent-shared'
import { isMetricsExcludedPath, recordHttpRequest } from '@posthog/agent-shared'

/**
 * One structured log line per request, emitted on completion so it carries the
 * final status + total duration. Level tracks the outcome (5xx → error, 4xx →
 * warn, else info); `/metrics` + `/healthz` probes demote to debug. Listens on
 * both `finish` and `close` so a client that aborts mid-response is logged with
 * `aborted: true`.
 */
export function requestLogger(log: Logger): RequestHandler {
    return (req, res, next) => {
        const start = process.hrtime.bigint()
        log.debug({ method: req.method, url: req.originalUrl }, 'request_start')
        let logged = false
        const emit = (): void => {
            if (logged) {
                return
            }
            logged = true
            const fields = {
                method: req.method,
                url: req.originalUrl,
                status: res.statusCode,
                duration_ms: Math.round((Number(process.hrtime.bigint() - start) / 1e6) * 10) / 10,
                ip: req.ip,
                length: res.getHeader('content-length'),
                ...(res.writableFinished ? {} : { aborted: true }),
            }
            if (isMetricsExcludedPath(req.path)) {
                log.debug(fields, 'request')
            } else if (res.statusCode >= 500) {
                log.error(fields, 'request')
            } else if (res.statusCode >= 400) {
                log.warn(fields, 'request')
            } else {
                log.info(fields, 'request')
            }
        }
        res.on('finish', emit)
        res.on('close', emit)
        next()
    }
}

/**
 * Records `agent_http_request_duration_seconds` per request. Mounted right
 * after `requestLogger` so it sees 404s + body-parse rejections too. The
 * `route` label is the express route PATTERN — never the resolved path — so
 * per-revision ids can't blow up cardinality.
 */
export function httpMetricsMiddleware(): RequestHandler {
    return (req, res, next) => {
        if (isMetricsExcludedPath(req.path)) {
            next()
            return
        }
        const start = process.hrtime.bigint()
        let recorded = false
        const record = (): void => {
            if (recorded) {
                return
            }
            recorded = true
            const route = req.route?.path ?? (res.statusCode === 404 ? 'unmatched' : 'unrouted')
            recordHttpRequest(
                { method: req.method, route: String(route), statusCode: res.statusCode },
                Number(process.hrtime.bigint() - start) / 1e9
            )
        }
        res.on('finish', record)
        res.on('close', record)
        next()
    }
}

export type AsyncRouteHandler = (req: Request, res: Response, next: NextFunction) => Promise<unknown> | unknown

export function asyncHandler(fn: AsyncRouteHandler): RequestHandler {
    return (req, res, next) => {
        Promise.resolve(fn(req, res, next)).catch(next)
    }
}

export function errorHandler(log: Logger) {
    // Express identifies error middleware by arity — must declare 4 params.
    return (err: unknown, req: Request, res: Response, _next: NextFunction): void => {
        if (res.headersSent) {
            // Response already started — can't send JSON now. Log + bail; the
            // socket will be killed by express. Better than crashing the
            // process.
            log.error(
                { err: errMessage(err), stack: errStack(err), path: req.path, method: req.method },
                'error_after_response_started'
            )
            return
        }
        if (err instanceof ZodError) {
            res.status(400).json({
                error: 'invalid_request',
                issues: err.issues.map((i) => ({ path: i.path, message: i.message, code: i.code })),
            })
            return
        }
        if (err instanceof SyntaxError && 'body' in (err as object)) {
            // express.json() threw on a malformed JSON body.
            res.status(400).json({ error: 'invalid_json' })
            return
        }
        log.error(
            { err: errMessage(err), stack: errStack(err), path: req.path, method: req.method },
            'unhandled_route_error'
        )
        res.status(500).json({ error: 'internal_error' })
    }
}

function errMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err)
}

function errStack(err: unknown): string | undefined {
    return err instanceof Error ? err.stack : undefined
}
