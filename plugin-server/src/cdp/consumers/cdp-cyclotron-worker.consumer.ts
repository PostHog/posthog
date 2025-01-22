import { CyclotronJob, CyclotronWorker } from '@posthog/cyclotron'

import { runInstrumentedFunction } from '../../main/utils'
import { status } from '../../utils/status'
import { HogFunctionInvocation, HogFunctionInvocationResult, HogFunctionTypeType } from '../types'
import { cyclotronJobToInvocation, invocationToCyclotronJobUpdate } from '../utils'
import { CdpConsumerBase, counterJobsProcessed, gaugeBatchUtilization } from './cdp-base.consumer'

/**
 * The future of the CDP consumer. This will be the main consumer that will handle all hog jobs from Cyclotron
 */
export class CdpCyclotronWorker extends CdpConsumerBase {
    protected name = 'CdpCyclotronWorker'
    private cyclotronWorker?: CyclotronWorker
    private runningWorker: Promise<void> | undefined
    protected queue: 'hog' | 'fetch' = 'hog'
    protected hogTypes: HogFunctionTypeType[] = ['destination', 'internal_destination']

    public async processBatch(invocations: HogFunctionInvocation[]): Promise<void> {
        if (!invocations.length) {
            return
        }

        const invocationResults = await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.executeInvocations`,
            func: async () => {
                const hogQueue = invocations.filter((item) => item.queue === 'hog')
                const hogResults = await this.runManyWithHeartbeat(hogQueue, (item) => this.hogExecutor.execute(item))
                return [...hogResults]
            },
        })

        await this.processInvocationResults(invocationResults)
        await this.updateJobs(invocationResults)
        await this.produceQueuedMessages()
    }

    private async updateJobs(invocations: HogFunctionInvocationResult[]) {
        await Promise.all(
            invocations.map((item) => {
                if (item.invocation.queue === 'fetch') {
                    // Track a metric purely to say a fetch was attempted (this may be what we bill on in the future)
                    this.produceAppMetric({
                        team_id: item.invocation.teamId,
                        app_source_id: item.invocation.hogFunction.id,
                        metric_kind: 'other',
                        metric_name: 'fetch',
                        count: 1,
                    })
                }

                const id = item.invocation.id
                if (item.error) {
                    status.debug('⚡️', 'Updating job to failed', id)
                    this.cyclotronWorker?.updateJob(id, 'failed')
                } else if (item.finished) {
                    status.debug('⚡️', 'Updating job to completed', id)
                    this.cyclotronWorker?.updateJob(id, 'completed')
                } else {
                    status.debug('⚡️', 'Updating job to available', id)

                    const updates = invocationToCyclotronJobUpdate(item.invocation)

                    this.cyclotronWorker?.updateJob(id, 'available', updates)
                }
                return this.cyclotronWorker?.releaseJob(id)
            })
        )
    }

    private async handleJobBatch(jobs: CyclotronJob[]) {
        gaugeBatchUtilization.labels({ queue: this.queue }).set(jobs.length / this.hub.CDP_CYCLOTRON_BATCH_SIZE)
        if (!this.cyclotronWorker) {
            throw new Error('No cyclotron worker when trying to handle batch')
        }
        const invocations: HogFunctionInvocation[] = []
        // A list of all the promises related to job releasing that we need to await
        const failReleases: Promise<void>[] = []
        for (const job of jobs) {
            // NOTE: This is all a bit messy and might be better to refactor into a helper
            if (!job.functionId) {
                throw new Error('Bad job: ' + JSON.stringify(job))
            }
            const hogFunction = this.hogFunctionManager.getHogFunction(job.functionId)

            if (!hogFunction) {
                // Here we need to mark the job as failed

                status.error('Error finding hog function', {
                    id: job.functionId,
                })
                this.cyclotronWorker.updateJob(job.id, 'failed')
                failReleases.push(this.cyclotronWorker.releaseJob(job.id))
                continue
            }

            const invocation = cyclotronJobToInvocation(job, hogFunction)
            invocations.push(invocation)
        }

        await this.processBatch(invocations)
        await Promise.all(failReleases)
        counterJobsProcessed.inc({ queue: this.queue }, jobs.length)
    }

    public async start() {
        await super.start()

        this.cyclotronWorker = new CyclotronWorker({
            pool: { dbUrl: this.hub.CYCLOTRON_DATABASE_URL },
            queueName: this.queue,
            includeVmState: true,
            batchMaxSize: this.hub.CDP_CYCLOTRON_BATCH_SIZE,
            pollDelayMs: this.hub.CDP_CYCLOTRON_BATCH_DELAY_MS,
            includeEmptyBatches: true,
        })
        await this.cyclotronWorker.connect((jobs) => this.handleJobBatch(jobs))
    }

    public async stop() {
        await super.stop()
        await this.cyclotronWorker?.disconnect()
        await this.runningWorker
    }

    public isHealthy() {
        return this.cyclotronWorker?.isHealthy() ?? false
    }
}

// Mostly used for testing the fetch executor
export class CdpCyclotronWorkerFetch extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerFetch'
    protected queue = 'fetch' as const
}
