import { chunk } from 'lodash'
import { Gauge } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk } from '../../../types'
import { CdpConfig } from '../../config'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { CyclotronV2DequeuedJob, CyclotronV2JobInit, CyclotronV2Manager, CyclotronV2Worker } from '../cyclotron-v2'
import { CyclotronV2WorkerConfig } from '../cyclotron-v2/types'
import { JobQueue } from './job-queue.interface'
import { cdpJobSizeCompressedKb, cdpJobSizeKb, createInvocationSanitizer, observeConsumedBatch } from './shared'

const pendingJobsGauge = new Gauge({
    name: 'cdp_cyclotron_v2_pending_jobs',
    help: 'Number of postgres-v2 jobs currently held in memory awaiting ack/fail/reschedule',
})

/**
 * State blob stored in the single `state` BYTEA column.
 * Mirrors the Kafka serialization: everything in one JSON object.
 */
type SerializedJobState = {
    state: CyclotronJobInvocation['state']
    queueParameters?: CyclotronJobInvocation['queueParameters']
    queueMetadata?: CyclotronJobInvocation['queueMetadata']
}

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
            includeEmptyBatches: true,
        })

        await this.worker.connect(async (jobs) => {
            const invocations: CyclotronJobInvocation[] = []

            for (const job of jobs) {
                this.pendingJobs.set(job.id, job)
                invocations.push(v2JobToInvocation(job))
            }

            pendingJobsGauge.set(this.pendingJobs.size)

            observeConsumedBatch({
                queue,
                source: 'postgres-v2',
                batchSize: invocations.length,
                maxBatchSize: this.consumerBatchSize,
            })

            await consumeBatch(invocations)

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
                } else if (result.finished) {
                    await job.ack()
                } else {
                    const stateBuffer = serializeState(result.invocation)
                    await job.reschedule({
                        state: stateBuffer,
                        scheduledAt: result.invocation.queueScheduledAt?.toJSDate(),
                        distinctId: extractDistinctId(result.invocation),
                        personId: extractPersonId(result.invocation),
                        actionId: extractActionId(result.invocation),
                        queueName: result.invocation.queue,
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

    public async cancelInvocations(invocations: CyclotronJobInvocation[]): Promise<void> {
        await Promise.all(
            invocations.map(async (inv) => {
                const job = this.pendingJobs.get(inv.id)
                if (job) {
                    this.pendingJobs.delete(inv.id)
                    await job.cancel()
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
}

function serializeState(invocation: CyclotronJobInvocation): Buffer {
    const blob: SerializedJobState = {
        state: invocation.state,
        queueParameters: invocation.queueParameters ?? undefined,
        queueMetadata: invocation.queueMetadata ?? undefined,
    }
    return Buffer.from(JSON.stringify(blob))
}

export function invocationToV2JobInit(invocation: CyclotronJobInvocation): CyclotronV2JobInit {
    const state = serializeState(invocation)
    cdpJobSizeKb.labels('postgres-v2').observe(state.length / 1024)
    cdpJobSizeCompressedKb.labels('postgres-v2').observe(state.length / 1024)

    return {
        id: invocation.id,
        teamId: invocation.teamId,
        functionId: invocation.functionId,
        queueName: invocation.queue,
        priority: invocation.queuePriority,
        scheduled: invocation.queueScheduledAt?.toJSDate() ?? new Date(),
        parentRunId: invocation.parentRunId ?? null,
        state,
        distinctId: extractDistinctId(invocation),
        personId: extractPersonId(invocation),
        actionId: extractActionId(invocation),
    }
}

type LookupColumnSource = {
    person?: { id?: string }
    state?: {
        event?: { distinct_id?: string }
        personId?: string
        currentAction?: { id?: string }
    } | null
}

export function extractDistinctId(invocation: CyclotronJobInvocation): string | null {
    return (invocation as LookupColumnSource).state?.event?.distinct_id || null
}

export function extractPersonId(invocation: CyclotronJobInvocation): string | null {
    const inv = invocation as LookupColumnSource
    return inv.person?.id || inv.state?.personId || null
}

export function extractActionId(invocation: CyclotronJobInvocation): string | null {
    return (invocation as LookupColumnSource).state?.currentAction?.id || null
}

function v2JobToInvocation(job: CyclotronV2DequeuedJob): CyclotronJobInvocation {
    let parsed: SerializedJobState = { state: null }

    if (job.state) {
        try {
            parsed = parseJSON(job.state.toString('utf-8'))
        } catch (e) {
            logger.error('Error parsing V2 job state', { error: String(e), jobId: job.id })
        }
    }

    const invocation: CyclotronJobInvocation = {
        id: job.id,
        teamId: job.teamId,
        functionId: job.functionId ?? '',
        queue: job.queueName as CyclotronJobQueueKind,
        queuePriority: job.priority,
        queueScheduledAt: job.scheduled ?? undefined,
        queueMetadata: parsed.queueMetadata ?? undefined,
        queueParameters: parsed.queueParameters ?? undefined,
        state: parsed.state,
        queueSource: 'postgres-v2',
    }

    if (job.parentRunId) {
        invocation.parentRunId = job.parentRunId
    }

    return invocation
}
