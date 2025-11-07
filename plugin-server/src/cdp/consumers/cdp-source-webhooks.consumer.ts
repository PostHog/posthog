import { DateTime } from 'luxon'

import { ModifiedRequest } from '~/api/router'
import { instrumented } from '~/common/tracing/tracing-utils'
import { HogFlow } from '~/schema/hogflow'

import { HealthCheckResult, HealthCheckResultOk, Hub } from '../../types'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { UUID, UUIDT } from '../../utils/utils'
import { createHogFlowInvocation } from '../services/hogflows/hogflow-executor.service'
import { actionIdForLogging } from '../services/hogflows/hogflow-utils'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogWatcherFunctionState, HogWatcherState } from '../services/monitoring/hog-watcher.service'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    LogEntryLevel,
    MinimalAppMetric,
} from '../types'
import { logEntry } from '../utils'
import { createInvocation, createInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBase } from './cdp-base.consumer'

const DISALLOWED_HEADERS = [
    'x-forwarded-for',
    'x-forwarded-host',
    'x-forwarded-proto',
    'x-forwarded-port',
    'cookie',
    'x-csrftoken',
    'proxy-authorization',
    'referer',
    'forwarded',
    'x-real-ip',
    'true-client-ip',
]

const getFirstHeaderValue = (value: string | string[] | undefined): string | undefined => {
    return Array.isArray(value) ? value[0] : value
}

export type HogFunctionWebhookResult = {
    status: number
    body: Record<string, any> | string
    contentType?: string
}

export const getCustomHttpResponse = (
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
): HogFunctionWebhookResult | null => {
    if (typeof result.execResult === 'object' && result.execResult && 'httpResponse' in result.execResult) {
        const httpResponse = result.execResult.httpResponse as Record<string, any>
        return {
            status: 'status' in httpResponse && typeof httpResponse.status === 'number' ? httpResponse.status : 500,
            body: 'body' in httpResponse ? httpResponse.body : '',
        }
    }

    return null
}

export class SourceWebhookError extends Error {
    status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = 'SourceWebhookError'
        this.status = status
    }
}

export class CdpSourceWebhooksConsumer extends CdpConsumerBase {
    protected name = 'CdpSourceWebhooksConsumer'
    private cyclotronJobQueue: CyclotronJobQueue
    private promiseScheduler: PromiseScheduler

    constructor(hub: Hub) {
        super(hub)
        this.promiseScheduler = new PromiseScheduler()
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, 'hog')
    }

    public async getWebhook(webhookId: string): Promise<{ hogFlow?: HogFlow; hogFunction: HogFunctionType } | null> {
        if (!UUID.validateString(webhookId, false)) {
            return null
        }

        // Check for hog functions
        const hogFunction = await this.hogFunctionManager.getHogFunction(webhookId)
        if (hogFunction?.type === 'source_webhook' && hogFunction?.enabled) {
            return { hogFunction }
        }

        // Otherwise check for hog flows
        const hogFlow = await this.hogFlowManager.getHogFlow(webhookId)
        if (
            hogFlow &&
            hogFlow.status === 'active' &&
            (hogFlow.trigger?.type === 'webhook' ||
                hogFlow.trigger?.type === 'tracking_pixel' ||
                hogFlow.trigger?.type === 'manual')
        ) {
            const hogFunction = await this.hogFlowFunctionsService.buildHogFunction(hogFlow, hogFlow.trigger)

            return { hogFlow, hogFunction }
        }

        return null
    }

    private buildRequestGlobals(hogFunction: HogFunctionType, req: ModifiedRequest): HogFunctionInvocationGlobals {
        const body: Record<string, any> = req.body

        const ipValue = getFirstHeaderValue(req.headers['x-forwarded-for']) || req.socket.remoteAddress || req.ip
        // IP could be comma delimited list of IPs
        const ips = ipValue?.split(',').map((ip) => ip.trim()) || []
        const ip = ips[0]

        const projectUrl = `${this.hub.SITE_URL}/project/${hogFunction.team_id}`
        const headers: Record<string, string> = {}

        for (const [key, value] of Object.entries(req.headers)) {
            const firstValue = getFirstHeaderValue(value)
            if (firstValue && !DISALLOWED_HEADERS.includes(key.toLowerCase())) {
                headers[key.toLowerCase()] = firstValue
            }
        }

        const query: Record<string, string> = {}
        for (const [key, value] of Object.entries(req.query)) {
            const firstValue = Array.isArray(value) ? value.join(',') : value
            query[key] = String(firstValue)
        }

        return {
            source: {
                name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                url: `${projectUrl}/functions/${hogFunction.id}`,
            },
            project: {
                id: hogFunction.team_id,
                name: '',
                url: '',
            },
            event: {
                event: '$incoming_webhook',
                properties: {},
                uuid: new UUIDT().toString(),
                distinct_id: req.body.distinct_id,
                elements_chain: '',
                timestamp: DateTime.now().toISO(),
                url: '',
            },
            request: {
                method: req.method,
                headers,
                ip,
                body,
                query,
                stringBody: req.rawBody ?? '',
            },
            variables: req.body.$variables || {},
        }
    }

    private async executeHogFlow(
        req: ModifiedRequest,
        hogFlow: HogFlow,
        hogFunction: HogFunctionType
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        logger.info('Executing hog flow trigger', {
            id: hogFlow.id,
            template_id: hogFunction.template_id,
            team_id: hogFlow.team_id,
        })
        const invocationId = new UUIDT().toString()
        const triggerActionId = hogFlow.actions.find((action) => action.type === 'trigger')?.id ?? 'trigger_node'

        const addLog = (level: LogEntryLevel, message: string) => {
            this.hogFunctionMonitoringService.queueLogs(
                [
                    {
                        team_id: hogFlow.team_id,
                        log_source: 'hog_flow',
                        log_source_id: hogFlow.id,
                        instance_id: invocationId,
                        ...logEntry(level, `${actionIdForLogging({ id: triggerActionId })} ${message}`),
                    },
                ],
                'hog_flow'
            )
        }

        const addMetric = (metric: Pick<MinimalAppMetric, 'metric_kind' | 'metric_name' | 'count'>) => {
            this.hogFunctionMonitoringService.queueAppMetric(
                {
                    team_id: hogFlow.team_id,
                    app_source_id: hogFlow.id,
                    ...metric,
                },
                'hog_flow'
            )
        }

        try {
            const globals: HogFunctionInvocationGlobals = this.buildRequestGlobals(hogFunction, req)

            // Normal execution path (no $scheduled_at)
            const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(hogFunction, globals)
            const invocation = createInvocation(globalsWithInputs, hogFunction)

            // Slightly different handling for hog flows
            // Run the initial step - this allows functions not using fetches to respond immediately
            const functionResult = await this.hogFlowFunctionsService.execute(invocation)
            functionResult.logs.forEach((log) => addLog(log.level, log.message))
            functionResult.logs = []

            // Queue any queued work here. This allows us to enable delayed work like fetching eventually without blocking the API.
            if (!functionResult.finished) {
                throw new SourceWebhookError(500, 'Delayed processing not supported')
            }

            const customHttpResponse = getCustomHttpResponse(functionResult)
            if (customHttpResponse) {
                const level = customHttpResponse.status >= 400 ? 'warn' : 'info'
                addLog(level, `Responded with response status - ${customHttpResponse.status}`)
            }

            const capturedPostHogEvent = functionResult.capturedPostHogEvents[0]
            // Add all logs to the result

            if (capturedPostHogEvent) {
                // Invoke the hogflow
                const triggerGlobals: HogFunctionInvocationGlobals = {
                    ...invocation.state.globals,
                    event: {
                        ...capturedPostHogEvent,
                        uuid: new UUIDT().toString(),
                        elements_chain: '',
                        url: '',
                    },
                }
                const hogFlowInvocation = createHogFlowInvocation(
                    triggerGlobals,
                    hogFlow,
                    {} as HogFunctionFilterGlobals
                )

                const scheduledAt = req.body?.$scheduled_at
                if (scheduledAt) {
                    hogFlowInvocation.queueScheduledAt = DateTime.fromISO(scheduledAt)
                    addLog('info', `Workflow run scheduled for ${scheduledAt}`)
                }

                hogFlowInvocation.id = invocationId // Keep the IDs consistent

                addMetric({
                    metric_kind: 'other',
                    metric_name: 'triggered',
                    count: 1,
                })

                addMetric({
                    metric_kind: 'billing',
                    metric_name: 'billable_invocation',
                    count: 1,
                })

                await this.cyclotronJobQueue.queueInvocations([hogFlowInvocation])
            } else {
                addMetric({
                    metric_kind: 'failure',
                    metric_name: 'trigger_failed',
                    count: 1,
                })
            }
            // Always set to false for hog flows as this triggers the flow to continue so we dont want metrics for this
            functionResult.finished = false

            return functionResult
        } catch (error) {
            logger.error('Error triggering hog flow', { error })
            addMetric({
                metric_kind: 'failure',
                metric_name: 'trigger_failed',
                count: 1,
            })

            addLog('error', `Error triggering flow: ${error.message}`)

            // NOTE: We only return a hog function result. We track out own logs and errors here
            return createInvocationResult(
                createInvocation({} as any, hogFunction),
                {},
                {
                    finished: false,
                    error: error.message,
                }
            )
        }
    }

    private async executeHogFunction(
        req: ModifiedRequest,
        hogFunction: HogFunctionType,
        hogFunctionState: HogWatcherFunctionState | null
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>

        try {
            const globals: HogFunctionInvocationGlobals = this.buildRequestGlobals(hogFunction, req)
            const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(hogFunction, globals)
            const invocation = createInvocation(globalsWithInputs, hogFunction)

            if (hogFunctionState?.state === HogWatcherState.degraded) {
                // Degraded functions are not executed immediately
                invocation.queue = 'hogoverflow'
                await this.cyclotronJobQueue.queueInvocations([invocation])

                result = createInvocationResult<CyclotronJobInvocationHogFunction>(
                    invocation,
                    {},
                    {
                        finished: false,
                        logs: [
                            {
                                level: 'warn',
                                message: 'Function scheduled for future execution due to degraded state',
                                timestamp: DateTime.now(),
                            },
                        ],
                    }
                )

                result.execResult = {
                    // TODO: Add support for a default response as an input
                    httpResponse: {
                        status: 200,
                        body: '',
                    },
                }
            } else {
                // Run the initial step - this allows functions not using fetches to respond immediately
                result = await this.hogExecutor.execute(invocation)

                // Queue any queued work here. This allows us to enable delayed work like fetching eventually without blocking the API.
                if (!result.finished) {
                    await this.cyclotronJobQueue.queueInvocationResults([result])
                }

                const customHttpResponse = getCustomHttpResponse(result)
                if (customHttpResponse) {
                    const level = customHttpResponse.status >= 400 ? 'warn' : 'info'
                    result.logs.push(logEntry(level, `Responded with response status - ${customHttpResponse.status}`))
                }
            }
        } catch (error) {
            logger.error('Error executing hog function', { error })
            result = createInvocationResult(
                createInvocation({} as any, hogFunction),
                {},
                {
                    finished: true,
                    error: error.message,
                    logs: [{ level: 'error', message: error.message, timestamp: DateTime.now() }],
                }
            )
        }

        await this.hogFunctionMonitoringService.queueInvocationResults([result])
        return result
    }

    @instrumented('cdpSourceWebhooksConsumer.processWebhook')
    public async processWebhook(
        identifier: string,
        req: ModifiedRequest
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        // NOTE: To simplify usage we allow setting a range of extensions for webhooks
        // Currently we just ignore it
        const [webhookId, _extension] = identifier.split('.')

        const [webhook, hogFunctionState] = await Promise.all([
            this.getWebhook(webhookId),
            this.hogWatcher.getCachedEffectiveState(webhookId),
        ])

        if (!webhook) {
            throw new SourceWebhookError(404, 'Not found')
        }

        const { hogFunction, hogFlow } = webhook

        if (hogFunctionState?.state === HogWatcherState.disabled) {
            this.hogFunctionMonitoringService.queueAppMetric(
                {
                    team_id: hogFunction.team_id,
                    app_source_id: hogFunction.id,
                    metric_kind: 'failure',
                    metric_name: 'disabled_permanently',
                    count: 1,
                },
                hogFlow ? 'hog_flow' : 'hog_function'
            )
            throw new SourceWebhookError(429, 'Disabled')
        }

        const result = hogFlow
            ? await this.executeHogFlow(req, hogFlow, hogFunction)
            : await this.executeHogFunction(req, hogFunction, hogFunctionState)

        void this.promiseScheduler.schedule(
            Promise.all([this.hogFunctionMonitoringService.flush(), this.hogWatcher.observeResultsBuffered(result)])
        )

        return result
    }

    public async start(): Promise<void> {
        await super.start()
        // Make sure we are ready to produce to cyclotron first
        await this.cyclotronJobQueue.startAsProducer()
    }

    public async stop(): Promise<void> {
        await this.cyclotronJobQueue.stop()
        await this.promiseScheduler.waitForAllSettled()
        // IMPORTANT: super always comes last
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        // TODO: What should we consider healthy / unhealthy here? kafka?
        return new HealthCheckResultOk()
    }
}
