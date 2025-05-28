import express from 'express'
import { DateTime } from 'luxon'

import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { UUIDT } from '../../utils/utils'
import { buildGlobalsWithInputs } from '../services/hog-executor.service'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import {
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionType,
    HogFunctionTypeType,
} from '../types'
import { createInvocation, createInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBase } from './cdp-base.consumer'

export class CdpSourceWebhooksConsumer extends CdpConsumerBase {
    protected name = 'CdpSourceWebhooksConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['source_webhook']
    private cyclotronJobQueue: CyclotronJobQueue
    private promiseScheduler: PromiseScheduler

    constructor(hub: Hub) {
        super(hub)
        this.promiseScheduler = new PromiseScheduler()
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, 'hog', this.hogFunctionManager)
    }

    public async getWebhook(webhookId: string): Promise<HogFunctionType | null> {
        const hogFunction = await this.hogFunctionManager.getHogFunction(webhookId)

        return hogFunction
    }

    public async processWebhook(webhookId: string, req: express.Request) {
        const hogFunction = await this.hogFunctionManager.getHogFunction(webhookId)

        if (!hogFunction) {
            // TODO: Maybe better error types?
            throw new Error('Not found')
        }

        const headers: Record<string, string> = {}

        for (const [key, value] of Object.entries(req.headers)) {
            // TODO: WE should filter the headers to only include ones we know are safe to expose
            if (value) {
                headers[key.toLowerCase()] = Array.isArray(value) ? value[0] : value
            }
        }

        const body: Record<string, any> = req.body
        // TODO: Should this be filled via other headers?
        const ip = req.ip

        const globals: HogFunctionInvocationGlobals = {
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

        let result: HogFunctionInvocationResult

        try {
            // TODO: Add error handling and logging
            const globalsWithInputs = buildGlobalsWithInputs(globals, {
                ...(hogFunction.inputs ?? {}),
                ...(hogFunction.encrypted_inputs ?? {}),
            })

            // TODO: Do we want to use hogwatcher here as well?
            const invocation = createInvocation(globalsWithInputs, hogFunction)
            // Run the initial step - this allows functions not using fetches to respond immediately
            result = this.hogExecutor.execute(invocation)

            void this.promiseScheduler.schedule(
                Promise.all([
                    this.hogFunctionMonitoringService.queueInvocationResults([result]).then(() => {
                        return this.hogFunctionMonitoringService.produceQueuedMessages()
                    }),
                    this.hogWatcher.observeResults([result]),
                ])
            )

            // Queue any queued work here. This allows us to enable delayed work like fetching eventually without blocking the API.
            await this.cyclotronJobQueue.queueInvocationResults([result])
        } catch (error) {
            // TODO: Make this more robust
            logger.error('Error executing hog function', { error })
            result = createInvocationResult(
                createInvocation({} as any, hogFunction),
                { queue: 'hog' },
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
        await super.stop()
        await this.cyclotronJobQueue.stop()
        await this.promiseScheduler.waitForAllSettled()
    }

    public isHealthy() {
        // TODO: What should we consider healthy / unhealthy here? kafka?
        return true
    }
}
