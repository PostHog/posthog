/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */

import {
    CyclotronJob,
    CyclotronJobInit,
    CyclotronJobUpdate,
    CyclotronManager,
    CyclotronWorker,
} from '@posthog/cyclotron'
import { chunk } from 'lodash'
import { DateTime } from 'luxon'

import { PluginsServerConfig } from '../../../types'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import {
    HogFunctionInvocation,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionInvocationJobQueue,
    HogFunctionInvocationQueueParameters,
    HogFunctionInvocationResult,
    HogFunctionInvocationSerialized,
    HogFunctionType,
} from '../../types'
import { HogFunctionManagerService } from '../hog-function-manager.service'
import { serializeHogFunctionInvocation } from './job-queue-kafka'

export class CyclotronJobQueuePostgres {
    private cyclotronWorker?: CyclotronWorker
    private cyclotronManager?: CyclotronManager

    constructor(
        private config: PluginsServerConfig,
        private queue: HogFunctionInvocationJobQueue,
        private hogFunctionManager: HogFunctionManagerService,
        private consumeBatch: (invocations: HogFunctionInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    ) {}

    /**
     * Helper to only start the producer related code (e.g. when not a consumer)
     */
    public async startAsProducer() {
        if (!this.config.CYCLOTRON_DATABASE_URL) {
            throw new Error('Cyclotron database URL not set! This is required for the CDP services to work.')
        }
        this.cyclotronManager = new CyclotronManager({
            shards: [
                {
                    dbUrl: this.config.CYCLOTRON_DATABASE_URL,
                },
            ],
            shardDepthLimit: this.config.CYCLOTRON_SHARD_DEPTH_LIMIT ?? 1000000,
            shouldCompressVmState: this.config.CDP_CYCLOTRON_COMPRESS_VM_STATE,
            shouldUseBulkJobCopy: this.config.CDP_CYCLOTRON_USE_BULK_COPY_JOB,
        })

        await this.cyclotronManager.connect()
    }

    public async startAsConsumer() {
        if (!this.config.CYCLOTRON_DATABASE_URL) {
            throw new Error('Cyclotron database URL not set! This is required for the CDP services to work.')
        }
        // The consumer always needs the producers as well
        await this.startAsProducer()

        this.cyclotronWorker = new CyclotronWorker({
            pool: {
                dbUrl: this.config.CYCLOTRON_DATABASE_URL,
            },
            queueName: this.queue,
            includeVmState: true, // NOTE: We used to omit the vmstate but given we can requeue to kafka we need it
            batchMaxSize: this.config.CDP_CYCLOTRON_BATCH_SIZE,
            pollDelayMs: this.config.CDP_CYCLOTRON_BATCH_DELAY_MS,
            includeEmptyBatches: true,
            shouldCompressVmState: this.config.CDP_CYCLOTRON_COMPRESS_VM_STATE,
        })
        await this.cyclotronWorker.connect((jobs) => this.consumeCyclotronJobs(jobs))
    }

    public async stop() {
        await this.cyclotronWorker?.disconnect()
    }

    public isHealthy() {
        return this.getCyclotronWorker().isHealthy()
    }

    public async queueInvocations(invocations: HogFunctionInvocation[]) {
        if (invocations.length === 0) {
            return
        }

        const cyclotronManager = this.getCyclotronManager()

        // For the cyclotron ones we simply create the jobs
        const cyclotronJobs = invocations.map((item) => invocationToCyclotronJobInitial(item))

        try {
            // Cyclotron batches inserts into one big INSERT which can lead to contention writing WAL information hence we chunk into batches
            const chunkedCyclotronJobs = chunk(cyclotronJobs, this.config.CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE)

            if (this.config.CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES) {
                // NOTE: It's not super clear the perf tradeoffs of doing this in parallel hence the config option
                await Promise.all(chunkedCyclotronJobs.map((jobs) => cyclotronManager.bulkCreateJobs(jobs)))
            } else {
                for (const jobs of chunkedCyclotronJobs) {
                    await cyclotronManager.bulkCreateJobs(jobs)
                }
            }
        } catch (e) {
            logger.error('⚠️', 'Error creating cyclotron jobs', e)
            logger.warn('⚠️', 'Failed jobs', { jobs: cyclotronJobs })
            throw e
        }
    }

    public async queueInvocationResults(invocationResults: HogFunctionInvocationResult[]) {
        const worker = this.getCyclotronWorker()
        await Promise.all(
            invocationResults.map(async (item) => {
                const id = item.invocation.id
                if (item.error) {
                    logger.debug('⚡️', 'Updating job to failed', id)
                    worker.updateJob(id, 'failed')
                } else if (item.finished) {
                    logger.debug('⚡️', 'Updating job to completed', id)
                    worker.updateJob(id, 'completed')
                } else {
                    logger.debug('⚡️', 'Updating job to available', id)

                    const updates = invocationToCyclotronJobUpdate(item.invocation)

                    if (this.queue === 'fetch') {
                        // When updating fetch jobs, we don't want to include the vm state
                        updates.vmState = undefined
                    }

                    worker.updateJob(id, 'available', updates)
                }
                return worker.releaseJob(id)
            })
        )
    }

    public async releaseInvocations(invocations: HogFunctionInvocation[]) {
        // Called specially for jobs that came from postgres but are being requeued to kafka
        const worker = this.getCyclotronWorker()
        await Promise.all(
            invocations.map(async (item) => {
                const id = item.id
                logger.debug('⚡️', 'Releasing job', id)
                worker.updateJob(id, 'completed')
                return worker.releaseJob(id)
            })
        )
    }

    private getCyclotronWorker(): CyclotronWorker {
        if (!this.cyclotronWorker) {
            throw new Error('CyclotronWorker not initialized')
        }
        return this.cyclotronWorker
    }

    private getCyclotronManager(): CyclotronManager {
        if (!this.cyclotronManager) {
            throw new Error('CyclotronManager not initialized')
        }
        return this.cyclotronManager
    }

    private async consumeCyclotronJobs(jobs: CyclotronJob[]) {
        const worker = this.getCyclotronWorker()
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

        await Promise.all([this.consumeBatch!(invocations), ...failReleases])
    }
}

function serializeHogFunctionInvocationForCyclotron(
    invocation: HogFunctionInvocation
): HogFunctionInvocationSerialized {
    const serializedInvocation = serializeHogFunctionInvocation(invocation)

    // Ensure we don't include this as it is set elsewhere
    delete serializedInvocation.queueParameters

    return serializedInvocation
}

function invocationToCyclotronJobInitial(invocation: HogFunctionInvocation): CyclotronJobInit {
    const queueParameters: HogFunctionInvocation['queueParameters'] = invocation.queueParameters
    let blob: CyclotronJobInit['blob'] = null
    let parameters: CyclotronJobInit['parameters'] = null

    if (queueParameters) {
        const { body, ...rest } = queueParameters
        parameters = rest
        blob = body ? Buffer.from(body) : null
    }

    const job: CyclotronJobInit = {
        teamId: invocation.globals.project.id,
        functionId: invocation.hogFunction.id,
        queueName: invocation.queue,
        priority: invocation.queuePriority,
        vmState: serializeHogFunctionInvocationForCyclotron(invocation),
        parameters,
        blob,
        metadata: invocation.queueMetadata ?? null,
        scheduled: invocation.queueScheduledAt?.toISO() ?? DateTime.now().toISO(),
    }
    return job
}

function invocationToCyclotronJobUpdate(invocation: HogFunctionInvocation): CyclotronJobUpdate {
    const job = invocationToCyclotronJobInitial(invocation)
    // Currently the job updates are identical to the initial job
    return job
}

function cyclotronJobToInvocation(job: CyclotronJob, hogFunction: HogFunctionType): HogFunctionInvocation {
    const parsedState = job.vmState as HogFunctionInvocationSerialized | null
    const params = job.parameters as HogFunctionInvocationQueueParameters | undefined

    if (job.blob && params) {
        // Deserialize the blob into the params
        try {
            params.body = job.blob ? Buffer.from(job.blob).toString('utf-8') : undefined
        } catch (e) {
            logger.error('Error parsing blob', e, job.blob)
            captureException(e)
        }
    }

    // TRICKY: If this is being converted for the fetch service we don't deserialize the vmstate as it isn't necessary
    // We cast it to the right type as we would rather things crash if they try to use it
    // This will be fixed in an upcoming PR

    return {
        id: job.id,
        globals: parsedState?.globals ?? ({} as unknown as HogFunctionInvocationGlobalsWithInputs),
        teamId: hogFunction.team_id,
        hogFunction,
        queue: (job.queueName as HogFunctionInvocationJobQueue) ?? 'hog',
        queuePriority: job.priority,
        queueScheduledAt: job.scheduled ? DateTime.fromISO(job.scheduled) : undefined,
        queueMetadata: job.metadata ?? undefined,
        queueParameters: params,
        queueSource: 'postgres', // NOTE: We always set this here, as we know it came from postgres
        vmState: parsedState?.vmState,
        timings: parsedState?.timings ?? [],
    }
}
