import { Counter } from 'prom-client'

import { Hub } from '../../types'
import { buildGlobalsWithInputs } from '../services/hog-executor.service'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogFunctionInvocationGlobalsWithInputs, HogFunctionTypeType } from '../types'
import { createInvocation } from '../utils'
import { CdpConsumerBase } from './cdp-base.consumer'

export const counterParseError = new Counter({
    name: 'cdp_function_parse_error',
    help: 'A function invocation was parsed with an error',
    labelNames: ['error'],
})

export class CdpSourceWebhooksConsumer extends CdpConsumerBase {
    protected name = 'CdpSourceWebhooksConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['source_webhook']
    private cyclotronJobQueue: CyclotronJobQueue

    constructor(hub: Hub) {
        super(hub)
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, 'hog', this.hogFunctionManager)
    }

    public async processWebhook(webhookId: string, body: Record<string, any>) {
        // Find the relevant webhook source

        const hogFunction = await this.hogFunctionManager.getHogFunction(webhookId)

        if (!hogFunction) {
            // TODO: Maybe better error types?
            throw new Error('Not found')
        }

        const globals: HogFunctionInvocationGlobalsWithInputs = {
            body,
        }

        const globalsWithInputs = buildGlobalsWithInputs(globals, {
            ...(hogFunction.inputs ?? {}),
            ...(hogFunction.encrypted_inputs ?? {}),
        })

        // TODO: Do we want to use hogwatcher here as well?
        const invocation = createInvocation(globalsWithInputs, hogFunction)
        // Run the initial step - this allows functions not using fetches to respond immediately
        const result = this.hogExecutor.execute(invocation)

        // TODO: Improve all this to be backgrounded
        await this.hogFunctionMonitoringService.processInvocationResults([result])
        await this.hogFunctionMonitoringService.produceQueuedMessages()
        await this.hogWatcher.observeResults([result])

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
    }

    public isHealthy() {
        // TODO: What should we consider healthy / unhealthy here? kafka?
        return true
    }
}
