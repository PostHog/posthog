import { CountedPaginatedResponse } from 'lib/api'

import { BatchExportConfiguration } from '~/types'

export const createExportServiceHandlers = (
    exports: { [id: number]: BatchExportConfiguration } = {}
): { exports: { [id: number]: BatchExportConfiguration }; handlers: any } => {
    const handlers = {
        get: {
            '/api/projects/:team_id/groups_types/': [],
            '/api/projects/:team_id/batch_exports/': (_req: any, res: any, ctx: any) => {
                return res(
                    ctx.delay(1000),
                    ctx.json({
                        results: Object.values(exports),
                    } as CountedPaginatedResponse<BatchExportConfiguration>)
                )
            },
            '/api/projects/:team_id/batch_exports/:export_id': (req: any, res: any, ctx: any) => {
                const id = req.params.export_id as string
                return res(ctx.delay(1000), ctx.json(exports[id]))
            },
            '/api/projects/:team_id/batch_exports/:export_id/runs': (req: any, res: any, ctx: any) => {
                const id = req.params.export_id as string
                return res(
                    ctx.delay(1000),
                    ctx.json({
                        results: exports[id]?.latest_runs ?? [],
                    })
                )
            },
        },
        post: {
            '/api/projects/:team_id/batch_exports/': (req: any, res: any, ctx: any) => {
                const body = req.body as BatchExportConfiguration
                const id = (Object.keys(exports).length + 1).toString()
                exports[id] = {
                    ...body,
                    id: id,
                    team_id: 1,
                    status: 'RUNNING',
                    paused: false,
                    created_at: new Date().toISOString(),
                    last_updated_at: new Date().toISOString(),
                }
                return res(ctx.delay(1000), ctx.json(exports[id]))
            },
            '/api/projects/:team_id/batch_exports/:export_id/pause/': (req: any, res: any, ctx: any) => {
                const id = req.params.export_id as string
                exports[id].paused = true
                return res(ctx.delay(1000), ctx.json(exports[id]))
            },
            '/api/projects/:team_id/batch_exports/:export_id/unpause/': (req: any, res: any, ctx: any) => {
                const id = req.params.export_id as string
                exports[id].paused = false
                return res(ctx.delay(1000), ctx.json(exports[id]))
            },
        },
        delete: {
            '/api/projects/:team_id/batch_exports/:export_id': (req: any, res: any, ctx: any) => {
                const id = req.params.export_id as string
                delete exports[id]
                return res(ctx.delay(1000))
            },
        },
    }

    return { exports, handlers }
}
