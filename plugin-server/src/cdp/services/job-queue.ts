// NOTE: We are often experimenting with different job queue implementations.
// To make this easier this class is designed to abstract the queue as much as possible from
// the underlying implementation.

import { CyclotronJob, CyclotronWorker } from '@posthog/cyclotron'
import { Counter, Gauge } from 'prom-client'

import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { HogFunctionInvocation, HogFunctionInvocationJobQueue, HogFunctionInvocationResult } from '../types'
import { cyclotronJobToInvocation, invocationToCyclotronJobUpdate } from '../utils'
import { HogFunctionManagerService } from './hog-function-manager.service'

const cyclotronBatchUtilizationGauge = new Gauge({
    name: 'cdp_cyclotron_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['queue'],
})

const counterJobsProcessed = new Counter({
    name: 'cdp_cyclotron_jobs_processed',
    help: 'The number of jobs we are managing to process',
    labelNames: ['queue'],
})

export class CyclotronJobQueue {
    private implementation: 'cyclotron' | 'kafka' = 'cyclotron'
    private cyclotronWorker?: CyclotronWorker

    constructor(
        private hub: Hub,
        private queue: HogFunctionInvocationJobQueue,
        private hogFunctionManager: HogFunctionManagerService,
        private consumeBatch: (invocations: HogFunctionInvocation[]) => Promise<any>
    ) {
        this.implementation = this.hub.CDP_CYCLOTRON_DELIVERY_MODE
    }

    public async start() {
        if (this.implementation === 'cyclotron') {
            await this.startCyclotronWorker()
        }
    }

    public async stop() {
        await this.cyclotronWorker?.disconnect()
    }

    public isHealthy() {
        if (this.implementation === 'cyclotron') {
            return this.cyclotronWorker?.isHealthy()
        }
        // TODO: Kafka version
        return true
    }

    public async queueInvocation(invocation: HogFunctionInvocation) {
        // TODO: Implement
    }

    public async queueInvocationResults(invocationResults: HogFunctionInvocationResult[]) {
        if (this.implementation === 'cyclotron') {
            await this.updateCyclotronJobs(invocationResults)
        }
    }

    private async startCyclotronWorker() {
        if (!this.hub.CYCLOTRON_DATABASE_URL) {
            throw new Error('Cyclotron database URL not set! This is required for the CDP services to work.')
        }
        this.cyclotronWorker = new CyclotronWorker({
            pool: {
                dbUrl: this.hub.CYCLOTRON_DATABASE_URL,
            },
            queueName: this.queue,
            // For the fetch queue we never need the state
            includeVmState: this.queue === 'fetch' ? false : true,
            batchMaxSize: this.hub.CDP_CYCLOTRON_BATCH_SIZE,
            pollDelayMs: this.hub.CDP_CYCLOTRON_BATCH_DELAY_MS,
            includeEmptyBatches: true,
            shouldCompressVmState: this.hub.CDP_CYCLOTRON_COMPRESS_VM_STATE,
        })
        await this.cyclotronWorker.connect((jobs) => this.consumeCyclotronJobs(jobs))
    }

    private getCyclotronWorker(): CyclotronWorker {
        if (!this.cyclotronWorker) {
            throw new Error('CyclotronWorker not initialized')
        }
        return this.cyclotronWorker
    }

    private async consumeCyclotronJobs(jobs: CyclotronJob[]) {
        const worker = this.getCyclotronWorker()
        cyclotronBatchUtilizationGauge
            .labels({ queue: this.queue })
            .set(jobs.length / this.hub.CDP_CYCLOTRON_BATCH_SIZE)

        const invocations: HogFunctionInvocation[] = []
        // A list of all the promises related to job releasing that we need to await
        const failReleases: Promise<void>[] = []

        const hogFunctionIds: string[] = []

        for (const job of jobs) {
            if (!job.functionId) {
                throw new Error('Bad job: ' + JSON.stringify(job))
            }

            hogFunctionIds.push(job.functionId)
        }

        const hogFunctions = await this.hogFunctionManager.getHogFunctions(hogFunctionIds)

        for (const job of jobs) {
            // NOTE: This is all a bit messy and might be better to refactor into a helper
            const hogFunction = hogFunctions[job.functionId!]

            if (!hogFunction) {
                // Here we need to mark the job as failed

                logger.error('⚠️', 'Error finding hog function', {
                    id: job.functionId,
                })
                worker.updateJob(job.id, 'failed')
                failReleases.push(worker.releaseJob(job.id))
                continue
            }

            const invocation = cyclotronJobToInvocation(job, hogFunction)
            invocations.push(invocation)
        }

        await this.consumeBatch(invocations)

        await Promise.all(failReleases)
        counterJobsProcessed.inc({ queue: this.queue }, jobs.length)
    }

    private async updateCyclotronJobs(invocationResults: HogFunctionInvocationResult[]) {
        await Promise.all(
            invocationResults.map(async (item) => {
                const id = item.invocation.id
                if (item.error) {
                    logger.debug('⚡️', 'Updating job to failed', id)
                    this.cyclotronWorker?.updateJob(id, 'failed')
                } else if (item.finished) {
                    logger.debug('⚡️', 'Updating job to completed', id)
                    this.cyclotronWorker?.updateJob(id, 'completed')
                } else {
                    logger.debug('⚡️', 'Updating job to available', id)

                    const updates = invocationToCyclotronJobUpdate(item.invocation)

                    if (this.queue === 'fetch') {
                        // When updating fetch jobs, we don't want to include the vm state
                        updates.vmState = undefined
                    }

                    this.cyclotronWorker?.updateJob(id, 'available', updates)
                }
                return this.cyclotronWorker?.releaseJob(id)
            })
        )
    }
}
