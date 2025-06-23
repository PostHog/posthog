import { PluginEvent } from '@posthog/plugin-scaffold'
import express from 'express'
import { DateTime } from 'luxon'

import { Hub, PluginServerService } from '../types'
import { logger } from '../utils/logger'
import { delay, UUID, UUIDT } from '../utils/utils'
import { CdpSourceWebhooksConsumer } from './consumers/cdp-source-webhooks.consumer'
import { HogTransformerService } from './hog-transformations/hog-transformer.service'
import { createCdpRedisPool } from './redis'
import { FetchExecutorService } from './services/fetch-executor.service'
import { HogExecutorService, MAX_ASYNC_STEPS } from './services/hog-executor.service'
import { HogFunctionManagerService } from './services/hog-function-manager.service'
import { HogFunctionMonitoringService } from './services/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from './services/hog-watcher.service'
import { MessagingMailjetManagerService } from './services/messaging/mailjet-manager.service'
import { HOG_FUNCTION_TEMPLATES } from './templates'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionQueueParametersFetchRequest,
    HogFunctionType,
    MinimalLogEntry,
} from './types'
import { convertToHogFunctionInvocationGlobals } from './utils'
import { createInvocationResult } from './utils/invocation-utils'

export class CdpApi {
    private hogExecutor: HogExecutorService
    private hogFunctionManager: HogFunctionManagerService
    private fetchExecutor: FetchExecutorService
    private hogWatcher: HogWatcherService
    private hogTransformer: HogTransformerService
    private hogFunctionMonitoringService: HogFunctionMonitoringService
    private cdpSourceWebhooksConsumer: CdpSourceWebhooksConsumer
    private messagingMailjetManagerService: MessagingMailjetManagerService

    constructor(private hub: Hub) {
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogExecutor = new HogExecutorService(hub)
        this.fetchExecutor = new FetchExecutorService(hub)
        this.hogWatcher = new HogWatcherService(hub, createCdpRedisPool(hub))
        this.hogTransformer = new HogTransformerService(hub)
        this.hogFunctionMonitoringService = new HogFunctionMonitoringService(hub)
        this.cdpSourceWebhooksConsumer = new CdpSourceWebhooksConsumer(hub)
        this.messagingMailjetManagerService = new MessagingMailjetManagerService(hub)
    }

    public get service(): PluginServerService {
        return {
            id: 'cdp-api',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    async start() {
        await this.hogFunctionManager.start()
        await this.cdpSourceWebhooksConsumer.start()
    }

    async stop() {
        await Promise.all([this.hogFunctionManager.stop(), this.cdpSourceWebhooksConsumer.stop()])
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
        router.post('/public/messaging/mailjet_webhook', asyncHandler(this.postMailjetWebhook()))
        router.post('/public/webhooks/:webhook_id', asyncHandler(this.postWebhook()))
        router.get('/public/webhooks/:webhook_id', asyncHandler(this.getWebhook()))

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
            const { clickhouse_event, mock_async_functions, configuration, invocation_id } = req.body
            let { globals } = req.body

            logger.info('⚡️', 'Received invocation', { id, team_id, body: req.body })

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
            const team = await this.hub.teamManager.getTeam(parseInt(team_id)).catch(() => null)

            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            globals = clickhouse_event
                ? convertToHogFunctionInvocationGlobals(
                      clickhouse_event,
                      team,
                      this.hub.SITE_URL ?? 'http://localhost:8000'
                  )
                : globals

            if (!globals || !globals.event) {
                res.status(400).json({ error: 'Missing event' })
                return
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

            let lastResponse: CyclotronJobInvocationResult | null = null
            let logs: MinimalLogEntry[] = []
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
                    let invocation: CyclotronJobInvocation = _invocation
                    invocation.id = invocationID

                    while (!lastResponse || !lastResponse.finished) {
                        if (count > MAX_ASYNC_STEPS * 2) {
                            throw new Error('Too many iterations')
                        }
                        count += 1

                        let response: CyclotronJobInvocationResult

                        if (invocation.queue === 'fetch') {
                            if (mock_async_functions) {
                                // Add the state, simulating what executeAsyncResponse would do
                                // Re-parse the fetch args for the logging
                                const { url: fetchUrl, ...fetchArgs }: HogFunctionQueueParametersFetchRequest =
                                    this.hogExecutor.redactFetchRequest(
                                        invocation.queueParameters as HogFunctionQueueParametersFetchRequest
                                    )

                                response = createInvocationResult(
                                    invocation,
                                    {
                                        queue: 'hog',
                                        queueParameters: { response: { status: 200, headers: {} }, body: '{}' },
                                    },
                                    {
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
                                )
                            } else {
                                response = await this.fetchExecutor.execute(invocation)
                            }
                        } else {
                            response = this.hogExecutor.execute(invocation as CyclotronJobInvocationHogFunction)
                        }

                        logs = logs.concat(response.logs)
                        lastResponse = response
                        invocation = response.invocation
                        if (response.error) {
                            errors.push(response.error)
                        }

                        await this.hogFunctionMonitoringService.queueInvocationResults([response])
                    }
                }

                const wasSkipped = filterMetrics.some((m) => m.metric_name === 'filtered')

                res.json({
                    result: result,
                    status: errors.length > 0 ? 'error' : wasSkipped ? 'skipped' : 'success',
                    errors: errors.map((e) => String(e)),
                    logs: logs,
                })
            } else if (compoundConfiguration.type === 'transformation') {
                // NOTE: We override the ID so that the transformer doesn't cache the result
                // TODO: We could do this with a "special" ID to indicate no caching...
                compoundConfiguration.id = new UUIDT().toString()
                const pluginEvent: PluginEvent = {
                    ...triggerGlobals.event,
                    ip:
                        typeof triggerGlobals.event.properties.$ip === 'string'
                            ? triggerGlobals.event.properties.$ip
                            : null,
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

                const wasSkipped = response.invocationResults.some((r) =>
                    r.metrics.some((m) => m.metric_name === 'filtered')
                )

                res.json({
                    result: result,
                    status: errors.length > 0 ? 'error' : wasSkipped ? 'skipped' : 'success',
                    errors: errors.map((e) => String(e)),
                    logs: logs,
                })
            } else {
                return res.status(400).json({ error: 'Invalid function type' })
            }
        } catch (e) {
            console.error(e)
            res.status(500).json({ errors: [e.message] })
        } finally {
            await this.hogFunctionMonitoringService.produceQueuedMessages()
        }
    }

    private postWebhook =
        () =>
        async (req: express.Request, res: express.Response): Promise<any> => {
            // TODO: Source handler service that takes care of finding the relevant function,
            // running it (maybe) and scheduling the job if it gets suspended

            const { webhook_id } = req.params

            try {
                const result = await this.cdpSourceWebhooksConsumer.processWebhook(webhook_id, req)

                if (typeof result.execResult === 'object' && result.execResult && 'httpResponse' in result.execResult) {
                    // TODO: Better validation here before we directly use the result
                    const httpResponse = result.execResult.httpResponse as { status: number; body: any }
                    if (typeof httpResponse.body === 'string') {
                        return res.status(httpResponse.status).send(httpResponse.body)
                    } else if (typeof httpResponse.body === 'object') {
                        return res.status(httpResponse.status).json(httpResponse.body)
                    } else {
                        return res.status(httpResponse.status).send('')
                    }
                }

                if (result.error) {
                    return res.status(500).json({
                        status: 'Unhandled error',
                    })
                }
                if (!result.finished) {
                    return res.status(201).json({
                        status: 'queued',
                    })
                }
                return res.status(200).json({
                    status: 'ok',
                })
            } catch (error) {
                return res.status(500).json({ error: 'Internal error' })
            }
        }

    private getWebhook =
        () =>
        async (req: express.Request, res: express.Response): Promise<any> => {
            const { webhook_id } = req.params

            const webhook = await this.cdpSourceWebhooksConsumer.getWebhook(webhook_id)

            if (!webhook) {
                return res.status(404).json({ error: 'Not found' })
            }

            return res.set('Allow', 'POST').status(405).json({
                error: 'Method not allowed',
            })
        }

    private postMailjetWebhook =
        () =>
        async (req: express.Request & { rawBody?: Buffer }, res: express.Response): Promise<any> => {
            try {
                const { status, message } = await this.messagingMailjetManagerService.handleWebhook(req)

                return res.status(status).send(message)
            } catch (error) {
                return res.status(500).json({ error: 'Internal error' })
            }
        }
}
