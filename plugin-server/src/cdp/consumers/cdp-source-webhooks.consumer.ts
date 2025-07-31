import { DateTime } from 'luxon'
import express from 'ultimate-express'

import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { UUID, UUIDT } from '../../utils/utils'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '../types'
import { createAddLogFunction } from '../utils'
import { createInvocation, createInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBase } from './cdp-base.consumer'

const getFirstHeaderValue = (value: string | string[] | undefined): string | undefined => {
    return Array.isArray(value) ? value[0] : value
}

export const getCustomHttpResponse = (
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
): {
    status: number
    body: Record<string, any> | string
} | null => {
    if (typeof result.execResult === 'object' && result.execResult && 'httpResponse' in result.execResult) {
        const httpResponse = result.execResult.httpResponse as Record<string, any>
        return {
            status: 'status' in httpResponse && typeof httpResponse.status === 'number' ? httpResponse.status : 500,
            body: 'body' in httpResponse ? httpResponse.body : '',
        }
    }

    return null
}

const DISALLOWED_HEADERS = ['x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto', 'x-forwarded-port', 'cookie']

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

    public async getWebhook(webhookId: string): Promise<HogFunctionType | null> {
        if (!UUID.validateString(webhookId, false)) {
            return null
        }

        const hogFunction = await this.hogFunctionManager.getHogFunction(webhookId)

        if (hogFunction?.type !== 'source_webhook' || !hogFunction.enabled) {
            return null
        }

        return hogFunction
    }

    public async processWebhook(
        webhookId: string,
        req: express.Request
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const hogFunction = await this.getWebhook(webhookId)

        if (!hogFunction) {
            throw new SourceWebhookError(404, 'Not found')
        }

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

        const globals: HogFunctionInvocationGlobals = {
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
                headers,
                ip,
                body,
            },
        }

        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>

        try {
            // TODO: Add error handling and logging
            const globalsWithInputs = await this.hogExecutor.buildInputsWithGlobals(hogFunction, globals)

            // TODO: Do we want to use hogwatcher here as well?
            const invocation = createInvocation(globalsWithInputs, hogFunction)
            // Run the initial step - this allows functions not using fetches to respond immediately
            result = await this.hogExecutor.execute(invocation)

            const addLog = createAddLogFunction(result.logs)

            // Queue any queued work here. This allows us to enable delayed work like fetching eventually without blocking the API.
            if (!result.finished) {
                await this.cyclotronJobQueue.queueInvocationResults([result])
            }

            const customHttpResponse = getCustomHttpResponse(result)
            if (customHttpResponse) {
                const level = customHttpResponse.status >= 400 ? 'warn' : 'info'
                addLog(level, `Responded with response status - ${customHttpResponse.status}`)
            }

            void this.promiseScheduler.schedule(
                Promise.all([
                    this.hogFunctionMonitoringService.queueInvocationResults([result]).then(() => {
                        return this.hogFunctionMonitoringService.produceQueuedMessages()
                    }),
                    this.hogWatcher.observeResults([result]),
                ])
            )
        } catch (error) {
            // TODO: Make this more robust
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
            void this.promiseScheduler.schedule(
                Promise.all([
                    this.hogFunctionMonitoringService.queueInvocationResults([result]).then(() => {
                        return this.hogFunctionMonitoringService.produceQueuedMessages()
                    }),
                    this.hogWatcher.observeResults([result]),
                ])
            )
        }

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

    public isHealthy() {
        // TODO: What should we consider healthy / unhealthy here? kafka?
        return true
    }
}
