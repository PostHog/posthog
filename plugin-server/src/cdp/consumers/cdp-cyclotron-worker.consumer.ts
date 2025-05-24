import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    CyclotronJobQueueKind,
    HogFunctionTypeType,
} from '../types'
import { CdpConsumerBase } from './cdp-base.consumer'

/**
 * The future of the CDP consumer. This will be the main consumer that will handle all hog jobs from Cyclotron
 */
export class CdpCyclotronWorker extends CdpConsumerBase {
    protected name = 'CdpCyclotronWorker'
    private cyclotronJobQueue: CyclotronJobQueue
    protected hogTypes: HogFunctionTypeType[] = ['destination', 'internal_destination']
    private queue: CyclotronJobQueueKind

    constructor(hub: Hub, queue: CyclotronJobQueueKind = 'hog') {
        super(hub)
        this.queue = queue
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, this.queue, (batch) => this.processBatch(batch))
    }

    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        const loadedInvocations = await this.loadHogFunctions(invocations)
        return await this.runManyWithHeartbeat(loadedInvocations, (item) => this.hogExecutor.execute(item))
    }

    // TODO: Move this to an abstract function??
    protected async loadHogFunctions(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationHogFunction[]> {
        const loadedInvocations: CyclotronJobInvocationHogFunction[] = []

        await Promise.all(
            invocations.map(async (item) => {
                const hogFunction = await this.hogFunctionManager.getHogFunction(item.functionId)
                if (!hogFunction) {
                    logger.error('⚠️', 'Error finding hog function', {
                        id: item.functionId,
                    })
                    return null
                }

                loadedInvocations.push({
                    ...item,
                    state: item.state as CyclotronJobInvocationHogFunction['state'],
                    hogFunction,
                })
            })
        )

        return loadedInvocations
    }

    public async processBatch(
        invocations: CyclotronJobInvocation[]
    ): Promise<{ backgroundTask: Promise<any>; invocationResults: CyclotronJobInvocationResult[] }> {
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
                this.hogFunctionMonitoringService.processInvocationResults(invocationResults).catch((err) => {
                    captureException(err)
                    logger.error('Error processing invocation results', { err })
                }),

                this.hogWatcher.observeResults(invocationResults).catch((err) => {
                    captureException(err)
                    logger.error('Error observing results', { err })
                }),

                this.hogFunctionMonitoringService.produceQueuedMessages().catch((err) => {
                    captureException(err)
                    logger.error('Error producing queued messages for monitoring', { err })
                }),
            ])
        })

        return { backgroundTask, invocationResults }
    }

    protected async queueInvocationResults(invocations: CyclotronJobInvocationResult[]) {
        await this.cyclotronJobQueue.queueInvocationResults(invocations)
        invocations.forEach((item) => {
            // TODO: Move this to the fetch consumer?
            if (item.invocation.queue === 'fetch') {
                // Track a metric purely to say a fetch was attempted (this may be what we bill on in the future)
                this.hogFunctionMonitoringService.produceAppMetric({
                    team_id: item.invocation.teamId,
                    app_source_id: item.invocation.functionId,
                    metric_kind: 'other',
                    metric_name: 'fetch',
                    count: 1,
                })
            }
        })
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
