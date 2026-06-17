/**
 * Read-only HTTP surface for the agent's tabular reference (the JSONL tables
 * the `@posthog/table-*` tools write). Lets the console's memory tab show
 * structured state (seen-sets, archive logs) alongside the markdown memory
 * files. Same S3-backed `TabularStore` the runner tools use.
 *
 * Routes scoped at `/tables/team/:team_id/agent/:application_id/...` — the
 * caller maps slug → application_id before forwarding, same as memory.
 *   GET  /tables/team/:t/agent/:a/            list table names + sizes
 *   GET  /tables/team/:t/agent/:a/:name       rows (capped via ?limit, default 500)
 */

import { Express, Request, Response } from 'express'
import { z } from 'zod'

import { Logger, TableNameError, TabularStore } from '@posthog/agent-shared'

import { asyncHandler } from '../http-utils'

// application_id is interpolated into the S3 key (the tenancy boundary), so
// require the UUID shape Django forwards — a non-empty string isn't enough.
const ScopeParams = z.object({
    team_id: z.coerce.number().int().positive('missing_team_id'),
    application_id: z.string().uuid('application_id must be a UUID'),
})

const RowsQuery = z.object({ limit: z.coerce.number().int().min(1).max(5000).default(500) })

export interface MountTableRoutesOpts {
    /** When omitted, every /tables/* route returns 503. */
    tabularStore?: TabularStore
    log: Logger
}

export function mountTableRoutes(app: Express, opts: MountTableRoutesOpts): void {
    function scope(req: Request): { teamId: number; applicationId: string } {
        const { team_id, application_id } = ScopeParams.parse(req.params)
        return { teamId: team_id, applicationId: application_id }
    }
    function need(res: Response): TabularStore | null {
        if (!opts.tabularStore) {
            res.status(503).json({ error: 'tabular_store_not_configured' })
            return null
        }
        return opts.tabularStore
    }
    function onError(res: Response, err: unknown): void {
        const message = (err as Error).message ?? 'tabular_error'
        // Bad table name (typed) or a Zod params/query failure → 400.
        if (err instanceof TableNameError || (err as { name?: string })?.name === 'ZodError') {
            res.status(400).json({ error: 'invalid_request', message })
            return
        }
        opts.log.error({ err: message, stack: (err as Error).stack }, 'tables.unhandled')
        res.status(500).json({ error: 'tabular_error', message })
    }

    app.get(
        '/tables/team/:team_id/agent/:application_id',
        asyncHandler(async (req: Request, res: Response) => {
            const store = need(res)
            if (!store) {
                return
            }
            try {
                const tables = await store.listTables(scope(req))
                res.json({ count: tables.length, tables })
            } catch (err) {
                onError(res, err)
            }
        })
    )

    app.get(
        '/tables/team/:team_id/agent/:application_id/:name',
        asyncHandler(async (req: Request, res: Response) => {
            const store = need(res)
            if (!store) {
                return
            }
            try {
                const { limit } = RowsQuery.parse(req.query)
                const name = z.string().min(1).parse(req.params.name)
                // queryPage = rows + total from a single object read.
                const { rows, total } = await store.queryPage(scope(req), name, { limit })
                res.json({ name, total, returned: rows.length, limit, rows })
            } catch (err) {
                onError(res, err)
            }
        })
    )
}
