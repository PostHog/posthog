import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { FetchExecutorService } from '../services/fetch-executor.service'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import {
    HogFunctionAppMetric,
    HogFunctionInvocation,
    HogFunctionInvocationJobQueue,
    HogFunctionInvocationResult,
    HogFunctionTypeType,
    LogEntry,
} from '../types'
import { CdpConsumerBase } from './cdp-base.consumer'

/**
 * The future of the CDP consumer. This will be the main consumer that will handle all hog jobs from Cyclotron
 */
export class CdpCyclotronWorker extends CdpConsumerBase {
    protected name = 'CdpCyclotronWorker'
    protected cyclotronJobQueue: CyclotronJobQueue
    protected fetchExecutor: FetchExecutorService

    protected hogTypes: HogFunctionTypeType[] = ['destination', 'internal_destination']
    private queue: HogFunctionInvocationJobQueue

    constructor(hub: Hub, queue: HogFunctionInvocationJobQueue = 'hog') {
        super(hub)
        this.queue = queue
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, this.queue, this.hogFunctionManager, (batch) =>
            this.processBatch(batch)
        )
        this.fetchExecutor = new FetchExecutorService(this.hub)
    }

    /**
     * Processes a single invocation. This is the core of the worker and is responsible for executing the hog code and any fetch requests.
     */
    private async processInvocation(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult> {
        let performedAsyncRequest = false
        let result: HogFunctionInvocationResult | null = null
        const metrics: HogFunctionAppMetric[] = []
        const logs: LogEntry[] = []

        while (!result || !result.finished) {
            const nextInvocation = result?.invocation ?? invocation

            if (nextInvocation.queue === 'hog') {
                result = this.hogExecutor.execute(nextInvocation)
                // Heartbeat and free the event loop to handle health checks
                this.heartbeat()
                await new Promise((resolve) => process.nextTick(resolve))
            } else if (nextInvocation.queue === 'fetch') {
                // Fetch requests we only perform if we haven't already performed one
                if (result && performedAsyncRequest) {
                    // if we have performed an async request already then we break the loop and return the result
                    break
                }
                result = await this.fetchExecutor.execute(nextInvocation)
                performedAsyncRequest = true
            } else {
                throw new Error(`Unhandled queue: ${nextInvocation.queue}`)
            }

            result?.logs?.forEach((log) => {
                logs.push(log)
            })
            result?.metrics?.forEach((metric) => {
                metrics.push(metric)
            })

            if (!result?.finished && result?.invocation.queueScheduledAt) {
                // If the invocation is scheduled to run later then we break the loop and return the result for it to be queued
                break
            }
        }

        // Override the result with the metrics and logs we have gathered to ensure we have all the data
        result.metrics = metrics
        result.logs = logs

        return result
    }

    public async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        return await Promise.all(invocations.map((item) => this.processInvocation(item)))
    }

    public async processBatch(
        invocations: HogFunctionInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: HogFunctionInvocationResult[] }> {
        if (!invocations.length) {
            return { backgroundTask: Promise.resolve(), invocationResults: [] }
        }

        const invocationResults = await this.runInstrumented(
            'handleEachBatch.executeInvocations',
            async () => await this.processInvocations(invocations)
        )

        // NOTE: We can queue and publish all metrics in the background whilst processing the next batch of invocations
        const backgroundTask = this.queueInvocationResults(invocationResults).then(() => {
            // NOTE: After this point we parallelize and any issues are logged rather than thrown as retrying now would end up in duplicate messages
            return Promise.allSettled([
                this.hogFunctionMonitoringService
                    .queueInvocationResults(invocationResults)
                    .then(() => this.hogFunctionMonitoringService.produceQueuedMessages())
                    .catch((err) => {
                        captureException(err)
                        logger.error('Error processing invocation results', { err })
                    }),
                this.hogWatcher.observeResults(invocationResults).catch((err) => {
                    captureException(err)
                    logger.error('Error observing results', { err })
                }),
            ])
        })

        return { backgroundTask, invocationResults }
    }

    protected async queueInvocationResults(invocations: HogFunctionInvocationResult[]) {
        await this.cyclotronJobQueue.queueInvocationResults(invocations)
    }

    public async start() {
        await super.start()
        await this.cyclotronJobQueue.start()
    }

    public async stop() {
        await super.stop()
        logger.info('🔄', 'Stopping cyclotron worker consumer')
        await this.cyclotronJobQueue.stop()
    }

    public isHealthy() {
        return this.cyclotronJobQueue.isHealthy()
    }
}
