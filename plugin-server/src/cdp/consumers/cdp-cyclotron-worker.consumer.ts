import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import {
    HogFunctionInvocation,
    HogFunctionInvocationJobQueue,
    HogFunctionInvocationResult,
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
    private queue: HogFunctionInvocationJobQueue

    constructor(hub: Hub, queue: HogFunctionInvocationJobQueue = 'hog') {
        super(hub)
        this.queue = queue
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, this.queue, this.hogFunctionManager, (batch) =>
            this.processBatch(batch)
        )
    }

    public async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        return await this.runManyWithHeartbeat(invocations, (item) => this.hogExecutor.execute(item))
    }

    public async processBatch(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        if (!invocations.length) {
            return []
        }

        const invocationResults = await this.runInstrumented(
            'handleEachBatch.executeInvocations',
            async () => await this.processInvocations(invocations)
        )

        await this.queueInvocationResults(invocationResults)
        await this.hogFunctionMonitoringService.processInvocationResults(invocationResults)

        // After this point we parallelize and any issues are logged rather than thrown as retrying now would end up in duplicate messages
        await Promise.allSettled([
            this.hogWatcher.observeResults(invocationResults),
            this.hogFunctionMonitoringService.produceQueuedMessages(),
        ])

        return invocationResults
    }

    protected async queueInvocationResults(invocations: HogFunctionInvocationResult[]) {
        await this.cyclotronJobQueue.queueInvocationResults(invocations)
        invocations.forEach((item) => {
            if (item.invocation.queue === 'fetch') {
                // Track a metric purely to say a fetch was attempted (this may be what we bill on in the future)
                this.hogFunctionMonitoringService.produceAppMetric({
                    team_id: item.invocation.teamId,
                    app_source_id: item.invocation.hogFunction.id,
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
