import { chunk } from 'lodash'
import { Counter, Gauge, Histogram } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk } from '../../../types'
import { CdpConfig } from '../../config'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { CyclotronV2DequeuedJob, CyclotronV2JobInit, CyclotronV2Manager, CyclotronV2Worker } from '../cyclotron-v2'
import { encodeJob, encodeStateColumns, v2JobToInvocation } from '../cyclotron-v2/job-codec'
import { CyclotronV2WorkerConfig } from '../cyclotron-v2/types'
import { JobQueue } from './job-queue.interface'
import { cdpJobSizeCompressedKb, cdpJobSizeKb, createInvocationSanitizer, observeConsumedBatch } from './shared'

export { extractActionId, extractDistinctId, extractPersonId } from '../cyclotron-v2/job-codec'

const pendingJobsGauge = new Gauge({
    name: 'cdp_cyclotron_v2_pending_jobs',
    help: 'Number of postgres-v2 jobs currently held in memory awaiting ack/fail/reschedule',
})

const resultWriteFailuresCounter = new Counter({
    name: 'cdp_cyclotron_v2_result_write_failures_total',
    help: 'Batches whose acks, reschedules or new jobs failed to write; dequeued jobs wait for the janitor stall reset',
    labelNames: ['queue'],
})

const jobLatenessHistogram = new Histogram({
    name: 'cdp_cyclotron_job_lateness_seconds',
    help: 'Seconds between a postgres-v2 job becoming due and a worker dequeuing it',
    labelNames: ['queue'],
    buckets: [0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300, 900],
})

export class CyclotronJobQueuePostgresV2 implements JobQueue {
    private manager?: CyclotronV2Manager
    private worker?: CyclotronV2Worker
    private pendingJobs = new Map<string, CyclotronV2DequeuedJob>()
    private sanitizer: ReturnType<typeof createInvocationSanitizer>

    constructor(
        // protected — the rate-limited subclass needs this to cap its token
        // claim at the actual batch size we can process (avoids deducting
        // tokens we'd never use).
        protected consumerBatchSize: number,
        private config: Pick<
            CdpConfig,
            | 'CYCLOTRON_NODE_DATABASE_URL'
            | 'CYCLOTRON_SHARD_DEPTH_LIMIT'
            | 'CDP_CYCLOTRON_BATCH_DELAY_MS'
            | 'CDP_CYCLOTRON_BOUNDED_POLLS'
            | 'CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE'
            | 'CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES'
            | 'CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS'
        >
    ) {
        this.sanitizer = createInvocationSanitizer(config)
    }

    public async startAsProducer(): Promise<void> {
        if (this.manager) {
            return
        }
        if (!this.config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('Cyclotron V2 database URL not set')
        }

        this.manager = new CyclotronV2Manager({
            pool: { dbUrl: this.config.CYCLOTRON_NODE_DATABASE_URL },
            depthLimit: this.config.CYCLOTRON_SHARD_DEPTH_LIMIT,
        })
        await this.manager.connect()
    }

    /**
     * Factory hook for the worker. Subclasses override this to plug in a
     * different worker class (e.g. CyclotronV2RateLimitedWorker) without
     * having to reimplement `startAsConsumer`.
     */
    protected createWorker(workerConfig: CyclotronV2WorkerConfig): CyclotronV2Worker {
        return new CyclotronV2Worker(workerConfig)
    }

    public async startAsConsumer(
        queue: CyclotronJobQueueKind,
        consumeBatch: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    ): Promise<void> {
        if (!this.config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('Cyclotron V2 database URL not set')
        }

        await this.startAsProducer()

        this.worker = this.createWorker({
            pool: { dbUrl: this.config.CYCLOTRON_NODE_DATABASE_URL },
            queueName: queue,
            batchMaxSize: this.consumerBatchSize,
            pollDelayMs: this.config.CDP_CYCLOTRON_BATCH_DELAY_MS,
            boundedPolls: this.config.CDP_CYCLOTRON_BOUNDED_POLLS,
            includeEmptyBatches: true,
        })

        await this.worker.connect(async (jobs) => {
            const invocations: CyclotronJobInvocation[] = []
            const now = Date.now()
            const jobLateness = jobLatenessHistogram.labels({ queue })

            for (const job of jobs) {
                this.pendingJobs.set(job.id, job)
                invocations.push(v2JobToInvocation(job))
                jobLateness.observe(Math.max(0, now - job.scheduled.toMillis()) / 1000)
            }

            pendingJobsGauge.set(this.pendingJobs.size)

            observeConsumedBatch({
                queue,
                source: 'postgres-v2',
                batchSize: invocations.length,
                maxBatchSize: this.consumerBatchSize,
            })

            const { backgroundTask } = await consumeBatch(invocations)
            void backgroundTask.catch((error) => {
                resultWriteFailuresCounter.labels({ queue }).inc()
                logger.warn('CyclotronV2 failed to write batch results', {
                    queue,
                    error: String(error),
                })
            })

            pendingJobsGauge.set(this.pendingJobs.size)
        })
    }

    public async stopConsumer(): Promise<void> {
        await this.worker?.disconnect()
        this.worker = undefined
    }

    public async stopProducer(): Promise<void> {
        await this.manager?.disconnect()
        this.manager = undefined
    }

    public isHealthy(): HealthCheckResult {
        if (!this.worker) {
            return new HealthCheckResultError('CyclotronV2Worker not initialized', {})
        }
        if (this.worker.isHealthy()) {
            return new HealthCheckResultOk()
        }
        return new HealthCheckResultError('CyclotronV2Worker is not healthy', {})
    }

    public async queueInvocations(
        invocations: CyclotronJobInvocation[],
        options: { overwriteExisting?: boolean } = {}
    ): Promise<void> {
        if (invocations.length === 0) {
            return
        }

        if (!this.manager) {
            throw new Error('CyclotronV2Manager not initialized')
        }

        invocations = this.sanitizer.sanitizeInvocations(invocations)

        const jobs = invocations.map((inv) => ({
            ...invocationToV2JobInit(inv),
            overwriteExisting: options.overwriteExisting,
        }))

        try {
            const chunked = chunk(jobs, this.config.CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE)
            if (this.config.CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES) {
                await Promise.all(
                    chunked.map((batch) =>
                        instrumentFn(
                            {
                                key: 'cyclotron_v2.bulk_create_jobs',
                                sendException: false,
                                getLoggingContext: () => ({ batchSize: batch.length, parallel: true }),
                            },
                            () => this.manager!.bulkCreateJobs(batch)
                        )
                    )
                )
            } else {
                for (const batch of chunked) {
                    await instrumentFn(
                        {
                            key: 'cyclotron_v2.bulk_create_jobs',
                            sendException: false,
                            getLoggingContext: () => ({ batchSize: batch.length, parallel: false }),
                        },
                        () => this.manager!.bulkCreateJobs(batch)
                    )
                }
            }
        } catch (e) {
            logger.error('Error creating cyclotron V2 jobs', { error: String(e) })
            throw e
        }
    }

    public async queueInvocationResults(invocationResults: CyclotronJobInvocationResult[]): Promise<void> {
        const sanitizedResults = this.sanitizer.sanitizeResults(invocationResults)

        await Promise.all(
            sanitizedResults.map(async (result) => {
                const job = this.pendingJobs.get(result.invocation.id)
                if (!job) {
                    logger.warn('No pending V2 job found for result, creating new job', {
                        id: result.invocation.id,
                    })
                    if (!result.finished && !result.error) {
                        await this.queueInvocations([result.invocation])
                    }
                    return
                }

                this.pendingJobs.delete(result.invocation.id)

                if (result.error) {
                    await job.fail()
                } else if (result.canceled) {
                    await job.cancel()
                } else if (result.finished) {
                    await job.ack()
                } else {
                    await job.reschedule({
                        ...encodeStateColumns(result.invocation),
                        scheduledAt: result.invocation.queueScheduledAt?.toJSDate(),
                        queueName: result.invocation.queue,
                        // Persisted only across email-queue transitions: entering carries the
                        // class routeEmailToQueue assigned, leaving restores the origin
                        // priority. Elsewhere the row keeps its insert-time priority, so the
                        // in-memory retry bumps on other queues stay unpersisted as before.
                        priority:
                            result.invocation.queue === 'email' || job.queueName === 'email'
                                ? result.invocation.queuePriority
                                : undefined,
                    })
                }
            })
        )
    }

    public async dequeueInvocations(invocations: CyclotronJobInvocation[]): Promise<void> {
        await Promise.all(
            invocations.map(async (inv) => {
                const job = this.pendingJobs.get(inv.id)
                if (job) {
                    this.pendingJobs.delete(inv.id)
                    await job.fail()
                }
            })
        )
    }

    public async releaseInvocations(invocations: CyclotronJobInvocation[]): Promise<void> {
        await Promise.all(
            invocations.map(async (inv) => {
                const job = this.pendingJobs.get(inv.id)
                if (job) {
                    this.pendingJobs.delete(inv.id)
                    await job.ack()
                }
            })
        )
    }

    public async heartbeatInvocations(invocations: CyclotronJobInvocation[]): Promise<void> {
        await Promise.all(
            invocations.map(async (inv) => {
                const job = this.pendingJobs.get(inv.id)
                if (!job) {
                    return
                }
                try {
                    await job.heartbeat()
                } catch (err) {
                    const message = err instanceof Error ? err.message : String(err)
                    if (message.includes('already released')) {
                        // Benign race with ack/fail/reschedule flipping `released` on the wrapper.
                        logger.debug('CyclotronV2 heartbeat skipped for released job', { id: inv.id })
                    } else {
                        // Real failure (connection error, pool exhaustion, query timeout) —
                        // surface it so we can act. Don't rethrow: the tick continues for
                        // the other jobs and the interval keeps firing so a transient blip
                        // doesn't kill the batch.
                        logger.warn('CyclotronV2 heartbeat failed', { id: inv.id, error: message })
                    }
                }
            })
        )
    }
}

export function invocationToV2JobInit(invocation: CyclotronJobInvocation): CyclotronV2JobInit {
    const init = encodeJob(invocation)
    const sizeKb = (init.state?.length ?? 0) / 1024
    cdpJobSizeKb.labels('postgres-v2').observe(sizeKb)
    cdpJobSizeCompressedKb.labels('postgres-v2').observe(sizeKb)
    return init
}
