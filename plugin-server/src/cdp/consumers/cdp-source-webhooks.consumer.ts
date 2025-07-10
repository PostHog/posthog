import express from 'express'
import { DateTime } from 'luxon'

import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { UUIDT } from '../../utils/utils'
import { buildGlobalsWithInputs } from '../services/hog-executor.service'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '../types'
import { createInvocation, createInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBase } from './cdp-base.consumer'

const getFirstHeaderValue = (value: string | string[] | undefined): string | undefined => {
    return Array.isArray(value) ? value[0] : value
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
        const hogFunction = await this.hogFunctionManager.getHogFunction(webhookId)

        if (hogFunction?.type !== 'source_webhook') {
            return null
        }

        return hogFunction
    }

    public async processWebhook(webhookId: string, req: express.Request) {
        const hogFunction = await this.getWebhook(webhookId)

        if (!hogFunction) {
            // TODO: Maybe better error types?
            throw new Error('Not found')
        }

        const headers: Record<string, string> = {}

        for (const [key, value] of Object.entries(req.headers)) {
            // TODO: WE should filter the headers to only include ones we know are safe to expose
            const firstValue = getFirstHeaderValue(value)
            if (firstValue) {
                headers[key.toLowerCase()] = firstValue
            }
        }

        const body: Record<string, any> = req.body
        // TODO: Should this be filled via other headers?
        const ip = getFirstHeaderValue(req.headers['x-forwarded-for']) || req.socket.remoteAddress || req.ip

        const projectUrl = `${this.hub.SITE_URL ?? ''}/project/${hogFunction.team_id}`

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
            const globalsWithInputs = await buildGlobalsWithInputs(globals, hogFunction.inputs)

            // TODO: Do we want to use hogwatcher here as well?
            const invocation = createInvocation(globalsWithInputs, hogFunction)
            // Run the initial step - this allows functions not using fetches to respond immediately
            result = await this.hogExecutor.execute(invocation)

            // Queue any queued work here. This allows us to enable delayed work like fetching eventually without blocking the API.
            if (!result.finished) {
                await this.cyclotronJobQueue.queueInvocationResults([result])
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
