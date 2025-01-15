import express from 'express'
import { DateTime } from 'luxon'

import { Hub } from '../types'
import { status } from '../utils/status'
import { delay } from '../utils/utils'
import { FetchExecutor } from './fetch-executor'
import { HogExecutor, MAX_ASYNC_STEPS } from './hog-executor'
import { HogFunctionManager } from './hog-function-manager'
import { HogWatcher, HogWatcherState } from './hog-watcher'
import { HogFunctionInvocationResult, HogFunctionType, LogEntry } from './types'

export class CdpApi {
    private hogExecutor: HogExecutor
    private hogFunctionManager: HogFunctionManager
    private fetchExecutor: FetchExecutor
    private hogWatcher: HogWatcher

    constructor(
        private hub: Hub,
        dependencies: {
            hogExecutor: HogExecutor
            hogFunctionManager: HogFunctionManager
            fetchExecutor: FetchExecutor
            hogWatcher: HogWatcher
        }
    ) {
        this.hogExecutor = dependencies.hogExecutor
        this.hogFunctionManager = dependencies.hogFunctionManager
        this.fetchExecutor = dependencies.fetchExecutor
        this.hogWatcher = dependencies.hogWatcher
    }

    router(): express.Router {
        const router = express.Router()

        const asyncHandler =
            (fn: (req: express.Request, res: express.Response) => Promise<void>) =>
            (req: express.Request, res: express.Response, next: express.NextFunction): Promise<void> =>
                fn(req, res).catch(next)

        router.post('/api/projects/:team_id/hog_functions/:id/invocations', asyncHandler(this.postFunctionInvocation))
        router.get('/api/projects/:team_id/hog_functions/:id/status', asyncHandler(this.getFunctionStatus()))
        router.patch('/api/projects/:team_id/hog_functions/:id/status', asyncHandler(this.patchFunctionStatus()))

        return router
    }

    private getFunctionStatus =
        () =>
        async (req: express.Request, res: express.Response): Promise<void> => {
            const { id } = req.params
            const summary = await this.hogWatcher.getState(id)

            res.json(summary)
        }

    private patchFunctionStatus =
        () =>
        async (req: express.Request, res: express.Response): Promise<void> => {
            const { id } = req.params
            const { state } = req.body

            // Check that state is valid
            if (!Object.values(HogWatcherState).includes(state)) {
                res.status(400).json({ error: 'Invalid state' })
                return
            }

            const summary = await this.hogWatcher.getState(id)

            // Only allow patching the status if it is different from the current status

            if (summary.state !== state) {
                await this.hogWatcher.forceStateChange(id, state)
            }

            // Hacky - wait for a little to give a chance for the state to change
            await delay(100)

            res.json(await this.hogWatcher.getState(id))
        }

    private postFunctionInvocation = async (req: express.Request, res: express.Response): Promise<void> => {
        try {
            const { id, team_id } = req.params
            const { globals, mock_async_functions, configuration } = req.body

            status.info('⚡️', 'Received invocation', { id, team_id, body: req.body })

            if (!globals) {
                res.status(400).json({ error: 'Missing event' })
                return
            }

            const [hogFunction, team] = await Promise.all([
                this.hogFunctionManager.fetchHogFunction(req.params.id),
                this.hub.teamManager.fetchTeam(parseInt(team_id)),
            ]).catch(() => {
                return [null, null]
            })
            if (!hogFunction || !team || hogFunction.team_id !== team.id) {
                res.status(404).json({ error: 'Hog function not found' })
                return
            }

            // We use the provided config if given, otherwise the function's config
            // We use the provided config if given, otherwise the function's config
            const compoundConfiguration: HogFunctionType = {
                ...hogFunction,
                ...(configuration ?? {}),
            }

            await this.hogFunctionManager.enrichWithIntegrations([compoundConfiguration])

            let lastResponse: HogFunctionInvocationResult | null = null
            let logs: LogEntry[] = []
            const errors: any[] = []

            const triggerGlobals = {
                ...globals,
                project: {
                    id: team.id,
                    name: team.name,
                    url: `${this.hub.SITE_URL ?? 'http://localhost:8000'}/project/${team.id}`,
                    ...globals.project,
                },
            }

            const {
                invocations,
                logs: filterLogs,
                metrics: filterMetrics,
            } = this.hogExecutor.buildHogFunctionInvocations([compoundConfiguration], triggerGlobals)

            // Add metrics to the logs
            filterMetrics.forEach((metric) => {
                if (metric.metric_name === 'filtered') {
                    logs.push({
                        level: 'info',
                        timestamp: DateTime.now(),
                        message: `Mapping trigger not matching filters was ignored.`,
                    })
                }
            })

            filterLogs.forEach((log) => {
                logs.push(log)
            })

            for (const _invocation of invocations) {
                let count = 0
                let invocation = _invocation

                while (!lastResponse || !lastResponse.finished) {
                    if (count > MAX_ASYNC_STEPS * 2) {
                        throw new Error('Too many iterations')
                    }
                    count += 1

                    let response: HogFunctionInvocationResult

                    if (invocation.queue === 'fetch') {
                        if (mock_async_functions) {
                            // Add the state, simulating what executeAsyncResponse would do

                            // Re-parse the fetch args for the logging
                            const fetchArgs = {
                                ...invocation.queueParameters,
                            }

                            response = {
                                invocation: {
                                    ...invocation,
                                    queue: 'hog',
                                    queueParameters: { response: { status: 200, headers: {} }, body: '{}' },
                                },
                                finished: false,
                                logs: [
                                    {
                                        level: 'info',
                                        timestamp: DateTime.now(),
                                        message: `Async function 'fetch' was mocked with arguments:`,
                                    },
                                    {
                                        level: 'info',
                                        timestamp: DateTime.now(),
                                        message: `fetch(${JSON.stringify(fetchArgs, null, 2)})`,
                                    },
                                ],
                            }
                        } else {
                            response = await this.fetchExecutor!.executeLocally(invocation)
                        }
                    } else {
                        response = this.hogExecutor.execute(invocation)
                    }

                    logs = logs.concat(response.logs)
                    lastResponse = response
                    invocation = response.invocation
                    if (response.error) {
                        errors.push(response.error)
                    }
                }
            }

            res.json({
                errors: errors.map((e) => String(e)),
                logs: logs,
            })
        } catch (e) {
            console.error(e)
            res.status(500).json({ errors: [e.message] })
        }
    }
}
