import { instrumented } from '~/common/tracing/tracing-utils'

import { HealthCheckResult, Hub } from '../../types'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import {
    CYCLOTRON_INVOCATION_JOB_QUEUES,
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    CyclotronJobQueueKind,
} from '../types'
import { isLegacyPluginHogFunction, isNativeHogFunction, isSegmentPluginHogFunction } from '../utils'
import { CdpConsumerBase } from './cdp-base.consumer'

/**
 * The future of the CDP consumer. This will be the main consumer that will handle all hog jobs from Cyclotron
 */
export class CdpCyclotronWorker extends CdpConsumerBase {
    protected name = 'CdpCyclotronWorker'
    protected cyclotronJobQueue: CyclotronJobQueue
    protected queue: CyclotronJobQueueKind

    constructor(hub: Hub, queue?: CyclotronJobQueueKind) {
        super(hub)
        this.queue = queue ?? hub.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_KIND

        if (!CYCLOTRON_INVOCATION_JOB_QUEUES.includes(this.queue)) {
            throw new Error(`Invalid cyclotron job queue kind: ${this.queue}`)
        }

        this.cyclotronJobQueue = new CyclotronJobQueue(hub, this.queue, (batch) => this.processBatch(batch))
    }

    @instrumented('cdpConsumer.handleEachBatch.executeInvocations')
    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        const loadedInvocations = await this.loadHogFunctions(invocations)

        return await Promise.all(
            loadedInvocations.map((item) => {
                if (isNativeHogFunction(item.hogFunction)) {
                    return this.nativeDestinationExecutorService.execute(item)
                } else if (isLegacyPluginHogFunction(item.hogFunction)) {
                    return this.pluginDestinationExecutorService.execute(item)
                } else if (isSegmentPluginHogFunction(item.hogFunction)) {
                    return this.segmentDestinationExecutorService.execute(item)
                } else {
                    return this.hogExecutor.executeWithAsyncFunctions(item)
                }
            })
        )
    }

    @instrumented('cdpConsumer.handleEachBatch.loadHogFunctions')
    protected async loadHogFunctions(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationHogFunction[]> {
        const loadedInvocations: CyclotronJobInvocationHogFunction[] = []
        const failedInvocations: CyclotronJobInvocation[] = []

        await Promise.all(
            invocations.map(async (item) => {
                const hogFunction = await this.hogFunctionManager.getHogFunction(item.functionId)
                if (!hogFunction) {
                    logger.error('⚠️', 'Error finding hog function', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)

                    return null
                }

                if (!hogFunction.enabled || hogFunction.deleted) {
                    logger.info('⚠️', 'Skipping invocation due to hog function being deleted or disabled', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)

                    return null
                }

                loadedInvocations.push({
                    ...item,
                    state: item.state as CyclotronJobInvocationHogFunction['state'],
                    hogFunction,
                })
            })
        )

        await this.cyclotronJobQueue.dequeueInvocations(failedInvocations)

        return loadedInvocations
    }

    public async processBatch(
        invocations: CyclotronJobInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
        if (!invocations.length) {
            return { backgroundTask: Promise.resolve(), invocationResults: [] }
        }

        logger.info('🔁', `${this.name} - handling batch`, {
            size: invocations.length,
        })

        const invocationResults = await this.processInvocations(invocations)

        // NOTE: We can queue and publish all metrics in the background whilst processing the next batch of invocations
        const backgroundTask = this.queueInvocationResults(invocationResults).then(() => {
            // NOTE: After this point we parallelize and any issues are logged rather than thrown as retrying now would end up in duplicate messages
            return Promise.allSettled([
                this.hogFunctionMonitoringService
                    .queueInvocationResults(invocationResults)
                    .then(() => this.hogFunctionMonitoringService.flush())
                    .catch((err) => {
                        captureException(err)
                        logger.error('Error processing invocation results', { err })
                    }),
                this.hogWatcher.observeResults(invocationResults).catch((err: any) => {
                    captureException(err)
                    logger.error('Error observing results', { err })
                }),
            ])
        })

        return { backgroundTask, invocationResults }
    }

    protected async queueInvocationResults(invocations: CyclotronJobInvocationResult[]) {
        await this.cyclotronJobQueue.queueInvocationResults(invocations)
    }

    public async start() {
        await super.start()
        await this.cyclotronJobQueue.start()
    }

    public async stop() {
        logger.info('🔄', 'Stopping cyclotron worker consumer')
        await this.cyclotronJobQueue.stop()

        // IMPORTANT: super always comes last
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.cyclotronJobQueue.isHealthy()
    }
}
