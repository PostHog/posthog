/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */
import { chunk } from 'lodash'
import { DateTime } from 'luxon'

import {
    CyclotronJob,
    CyclotronJobInit,
    CyclotronJobUpdate,
    CyclotronManager,
    CyclotronWorker,
} from '@posthog/cyclotron'

import { CyclotronInvocationQueueParametersType } from '~/schema/cyclotron'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginsServerConfig } from '../../../types'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'

export class CyclotronJobQueuePostgres {
    private cyclotronWorker?: CyclotronWorker
    private cyclotronManager?: CyclotronManager

    constructor(
        private config: PluginsServerConfig,
        private queue: CyclotronJobQueueKind,
        private consumeBatch: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
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
            batchMaxSize: this.config.CONSUMER_BATCH_SIZE, // Use the common value
            pollDelayMs: this.config.CDP_CYCLOTRON_BATCH_DELAY_MS,
            includeEmptyBatches: true,
            shouldCompressVmState: this.config.CDP_CYCLOTRON_COMPRESS_VM_STATE,
        })
        await this.cyclotronWorker.connect((jobs) => this.consumeCyclotronJobs(jobs))
    }

    public async stopConsumer() {
        await this.cyclotronWorker?.disconnect()
    }

    public async stopProducer() {
        // NOTE: Currently doesn't do anything as there is no disconnect logic - just keeps the interfaces the same
        return Promise.resolve()
    }

    public isHealthy(): HealthCheckResult {
        try {
            const worker = this.getCyclotronWorker()
            const isHealthy = worker.isHealthy()
            if (isHealthy) {
                return new HealthCheckResultOk()
            } else {
                return new HealthCheckResultError('Cyclotron worker is not healthy', {})
            }
        } catch (error) {
            return new HealthCheckResultError('Cyclotron worker not initialized', {
                error: error instanceof Error ? error.message : String(error),
            })
        }
    }

    public async queueInvocations(invocations: CyclotronJobInvocation[]) {
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

    public async dequeueInvocations(invocations: CyclotronJobInvocation[]) {
        const worker = this.getCyclotronWorker()

        await Promise.all(
            invocations.map(async (item) => {
                worker.updateJob(item.id, 'failed')
                return worker.releaseJob(item.id)
            })
        )
    }

    public async queueInvocationResults(invocationResults: CyclotronJobInvocationResult[]) {
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

                    worker.updateJob(id, 'available', updates)
                }
                return worker.releaseJob(id)
            })
        )
    }

    public async releaseInvocations(invocations: CyclotronJobInvocation[]) {
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
        const invocations: CyclotronJobInvocation[] = []
        // A list of all the promises related to job releasing that we need to await

        for (const job of jobs) {
            const invocation = cyclotronJobToInvocation(job)
            invocations.push(invocation)
        }

        await Promise.all([this.consumeBatch!(invocations)])
        // TODO: Ensure that all jobs eventually get acked!!!
    }
}

function invocationToCyclotronJobInitial(invocation: CyclotronJobInvocation): CyclotronJobInit {
    const queueParameters: CyclotronJobInvocation['queueParameters'] = invocation.queueParameters
    let blob: CyclotronJobInit['blob'] = null
    let parameters: CyclotronJobInit['parameters'] = null

    // TODO: Ditch this queue params stuff
    if (queueParameters) {
        if (queueParameters.type === 'fetch') {
            const { body, ...rest } = queueParameters
            parameters = rest
            blob = body ? Buffer.from(body) : null
        } else if (queueParameters.type === 'email') {
            parameters = queueParameters
            blob = null
        }
    }

    // Preserve the invocation id when inserting into Postgres so switching backends keeps the same ID
    // Only provide id if it looks like a UUID to avoid DB errors if caller used a different id format
    const looksLikeUuid = typeof invocation.id === 'string' && /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(invocation.id)

    const job: CyclotronJobInit & { id?: string } = {
        id: looksLikeUuid ? invocation.id : undefined,
        teamId: invocation.teamId,
        functionId: invocation.functionId,
        queueName: invocation.queue,
        priority: invocation.queuePriority,
        vmState: invocation.state,
        parameters,
        blob,
        metadata: invocation.queueMetadata ?? null,
        scheduled: invocation.queueScheduledAt?.toISO() ?? DateTime.now().toISO(),
    }
    return job
}

function invocationToCyclotronJobUpdate(invocation: CyclotronJobInvocation): CyclotronJobUpdate {
    const job = invocationToCyclotronJobInitial(invocation)
    // Currently the job updates are identical to the initial job
    return job
}

function cyclotronJobToInvocation(job: CyclotronJob): CyclotronJobInvocation {
    const params = job.parameters as CyclotronInvocationQueueParametersType | undefined

    if (job.blob && params && params.type === 'fetch') {
        // Deserialize the blob into the params
        try {
            params.body = job.blob ? Buffer.from(job.blob).toString('utf-8') : undefined
        } catch (e) {
            logger.error('Error parsing blob', e, job.blob)
            captureException(e)
        }
    }

    return {
        id: job.id,
        state: job.vmState,
        teamId: job.teamId,
        functionId: job.functionId!, // TODO: Fix this in the underlying cyclotron library - it should never be nullable
        queue: job.queueName as CyclotronJobQueueKind,
        queuePriority: job.priority,
        queueScheduledAt: job.scheduled ? DateTime.fromISO(job.scheduled) : undefined,
        queueMetadata: job.metadata ?? undefined,
        queueParameters: params,
        queueSource: 'postgres', // NOTE: We always set this here, as we know it came from postgres
    }
}
