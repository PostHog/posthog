import express from 'express'

import { Hub } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { buildGlobalsWithInputs } from '../services/hog-executor.service'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogFunctionInvocationGlobalsWithInputs, HogFunctionType, HogFunctionTypeType } from '../types'
import { createInvocation } from '../utils'
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

        const globals: HogFunctionInvocationGlobalsWithInputs = {
            body: req.body,
        }

        const globalsWithInputs = buildGlobalsWithInputs(globals, {
            ...(hogFunction.inputs ?? {}),
            ...(hogFunction.encrypted_inputs ?? {}),
        })

        // TODO: Do we want to use hogwatcher here as well?
        const invocation = createInvocation(globalsWithInputs, hogFunction)
        // Run the initial step - this allows functions not using fetches to respond immediately
        const result = this.hogExecutor.execute(invocation)

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
