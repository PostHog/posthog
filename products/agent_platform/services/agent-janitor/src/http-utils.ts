/**
 * Defensive HTTP middleware shared by every janitor route.
 *
 * `asyncHandler(fn)` — Express 4 doesn't catch rejections returned from
 * async route handlers; they become `unhandledRejection` instead of being
 * funneled through the global error middleware. Every async route should
 * be wrapped so its rejection lands in `next(err)`.
 *
 * `errorHandler(log)` — Final express middleware. Maps known error shapes
 * to structured responses, logs with context, and ALWAYS returns JSON
 * (never an express HTML stack trace). Add new mappings here as new
 * typed errors get thrown from the storage / persistence layers.
 *
 * Modeled on the ingress error handler at
 * `services/agent-ingress/src/routing/server.ts`. Kept local to janitor
 * (rather than promoted to agent-shared) because agent-shared deliberately
 * doesn't depend on express.
 */

import type { NextFunction, Request, RequestHandler, Response } from 'express'
import { ZodError } from 'zod'

import type { Logger } from '@posthog/agent-shared'

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
