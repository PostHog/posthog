import { PluginEvent } from '@posthog/plugin-scaffold'
import express from 'express'
import { DateTime } from 'luxon'

import { Hub, PluginServerService } from '../types'
import { status } from '../utils/status'
import { delay, UUID, UUIDT } from '../utils/utils'
import { HogTransformerService } from './hog-transformations/hog-transformer.service'
import { createCdpRedisPool } from './redis'
import { FetchExecutorService } from './services/fetch-executor.service'
import { HogExecutorService, MAX_ASYNC_STEPS } from './services/hog-executor.service'
import { HogFunctionManagerService } from './services/hog-function-manager.service'
import { HogFunctionMonitoringService } from './services/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from './services/hog-watcher.service'
import { HOG_FUNCTION_TEMPLATES } from './templates'
import {
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionQueueParametersFetchRequest,
    HogFunctionType,
    LogEntry,
} from './types'

export class CdpApi {
    private hogExecutor: HogExecutorService
    private hogFunctionManager: HogFunctionManagerService
    private fetchExecutor: FetchExecutorService
    private hogWatcher: HogWatcherService
    private hogTransformer: HogTransformerService
    private hogFunctionMonitoringService: HogFunctionMonitoringService

    constructor(private hub: Hub) {
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogExecutor = new HogExecutorService(hub, this.hogFunctionManager)
        this.fetchExecutor = new FetchExecutorService(hub)
        this.hogWatcher = new HogWatcherService(hub, createCdpRedisPool(hub))
        this.hogTransformer = new HogTransformerService(hub)
        this.hogFunctionMonitoringService = new HogFunctionMonitoringService(hub)
    }

    public get service(): PluginServerService {
        return {
            id: 'cdp-api',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    async start() {
        await this.hogFunctionManager.start(['transformation', 'destination', 'internal_destination'])
    }

    async stop() {
        await Promise.all([this.hogFunctionManager.stop()])
    }

    isHealthy() {
        // NOTE: There isn't really anything to check for here so we are just always healthy
        return true
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
        router.get('/api/hog_function_templates', this.getHogFunctionTemplates)

        return router
    }

    private getHogFunctionTemplates = (req: express.Request, res: express.Response): void => {
        res.json(HOG_FUNCTION_TEMPLATES)
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

    private postFunctionInvocation = async (req: express.Request, res: express.Response): Promise<any> => {
        try {
            const { id, team_id } = req.params
            const { globals, mock_async_functions, configuration, invocation_id } = req.body

            status.info('⚡️', 'Received invocation', { id, team_id, body: req.body })

            if (!globals || !globals.event) {
                res.status(400).json({ error: 'Missing event' })
                return
            }

            const invocationID = invocation_id ?? new UUIDT().toString()

            // Check the invocationId is a valid UUID
            if (!UUID.validateString(invocationID)) {
                res.status(400).json({ error: 'Invalid invocation ID' })
                return
            }

            const isNewFunction = req.params.id === 'new'

            const hogFunction = isNewFunction
                ? null
                : await this.hogFunctionManager.fetchHogFunction(req.params.id).catch(() => null)
            const team = await this.hub.teamManager.fetchTeam(parseInt(team_id)).catch(() => null)

            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            // NOTE: We allow the hog function to be null if it is a "new" hog function
            // The real security happens at the django layer so this is more of a sanity check
            if (!isNewFunction && (!hogFunction || hogFunction.team_id !== team.id)) {
                return res.status(404).json({ error: 'Hog function not found' })
            }

            // We use the provided config if given, otherwise the function's config
            const compoundConfiguration: HogFunctionType = {
                ...(hogFunction ?? {}),
                ...(configuration ?? {}),
                team_id: team.id,
            }

            await this.hogFunctionManager.enrichWithIntegrations([compoundConfiguration])

            let lastResponse: HogFunctionInvocationResult | null = null
            let logs: LogEntry[] = []
            let result: any = null
            const errors: any[] = []

            const triggerGlobals: HogFunctionInvocationGlobals = {
                ...globals,
                project: {
                    id: team.id,
                    name: team.name,
                    url: `${this.hub.SITE_URL ?? 'http://localhost:8000'}/project/${team.id}`,
                    ...globals.project,
                },
            }

            if (['destination', 'internal_destination'].includes(compoundConfiguration.type)) {
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
                    invocation.id = invocationID

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
                                const { url: fetchUrl, ...fetchArgs }: HogFunctionQueueParametersFetchRequest =
                                    this.hogExecutor.redactFetchRequest(
                                        invocation.queueParameters as HogFunctionQueueParametersFetchRequest
                                    )

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
                                            message: `fetch('${fetchUrl}', ${JSON.stringify(fetchArgs, null, 2)})`,
                                        },
                                    ],
                                }
                            } else {
                                response = await this.fetchExecutor.executeLocally(invocation)
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

                        await this.hogFunctionMonitoringService.processInvocationResults([response])
                    }
                }
            } else if (compoundConfiguration.type === 'transformation') {
                // NOTE: We override the ID so that the transformer doesn't cache the result
                // TODO: We could do this with a "special" ID to indicate no caching...
                compoundConfiguration.id = new UUIDT().toString()
                const pluginEvent: PluginEvent = {
                    ...triggerGlobals.event,
                    ip: triggerGlobals.event.properties.$ip,
                    site_url: triggerGlobals.project.url,
                    team_id: triggerGlobals.project.id,
                    now: '',
                }
                const response = await this.hogTransformer.transformEvent(pluginEvent, [compoundConfiguration])

                result = response.event

                for (const invocationResult of response.invocationResults) {
                    logs = logs.concat(invocationResult.logs)
                    if (invocationResult.error) {
                        errors.push(invocationResult.error)
                    }
                }
            } else {
                return res.status(400).json({ error: 'Invalid function type' })
            }

            res.json({
                result: result,
                status: errors.length > 0 ? 'error' : 'success',
                errors: errors.map((e) => String(e)),
                logs: logs,
            })
        } catch (e) {
            console.error(e)
            res.status(500).json({ errors: [e.message] })
        } finally {
            await this.hogFunctionMonitoringService.produceQueuedMessages()
        }
    }
}
