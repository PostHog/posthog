import { BatchExport, BatchExportData, BatchExportsResponse, BatchExportRun, BackfillRequest } from './api'

export const createExportServiceHandlers = (
    exports: { [id: number]: BatchExport } = {},
    runs: BatchExportRun[] = []
): { exports: { [id: number]: BatchExport }; runs: BatchExportRun[]; handlers: any } => {
    const handlers = {
        get: {
            '/api/projects/:team_id/batch_exports/': (_req: any, res: any, ctx: any) => {
                return res(
                    ctx.delay(1000),
                    ctx.json({
                        results: Object.values(exports),
                    } as BatchExportsResponse)
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
                        results: runs.filter((run) => run.batch_export_id === id),
                    })
                )
            },
        },
        post: {
            '/api/projects/:team_id/batch_exports/': (req: any, res: any, ctx: any) => {
                const body = req.body as BatchExportData
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
            '/api/projects/:team_id/batch_exports/:export_id/backfill': (req: any, res: any, ctx: any) => {
                // Create a run for the export with the specified ID, the
                // start_date and end_date are in the request body.
                const id = req.params.export_id as string

                const { start_at, end_at } = req.body as BackfillRequest

                const run_id = (Object.keys(runs).length + 1).toString()

                const run: BatchExportRun = {
                    id: run_id,
                    team_id: 1,
                    batch_export_id: id,
                    data_interval_start: start_at,
                    data_interval_end: end_at,
                    status: 'Running',
                    opened_at: new Date().toISOString(),
                    closed_at: null,
                    created_at: new Date().toISOString(),
                    last_updated_at: new Date().toISOString(),
                }

                runs.push(run)

                return res(ctx.delay(1000), ctx.json(run))
            },
        },
        delete: {
            '/api/projects/:team_id/batch_exports/:export_id/': (req: any, res: any, ctx: any) => {
                const id = req.params.export_id as string
                delete exports[id]
                return res(ctx.delay(1000))
            },
        },
    }

    return { exports, runs, handlers }
}
