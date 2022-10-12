import * as Sentry from '@sentry/node'
import { makeWorkerUtils, run, Runner, TaskList, WorkerUtils } from 'graphile-worker'
import { Pool } from 'pg'

import { EnqueuedJob, Hub } from '../../types'
import { instrument } from '../../utils/metrics'
import { runRetriableFunction } from '../../utils/retries'
import { status } from '../../utils/status'
import { createPostgresPool } from '../../utils/utils'

export interface InstrumentationContext {
    key: string
    tag: string
}

export class GraphileWorker {
    hub: Hub
    runner: Runner | null
    consumerPool: Pool | null
    producerPool: Pool | null
    workerUtilsPromise: Promise<WorkerUtils> | null
    started: boolean
    paused: boolean
    jobHandlers: TaskList
    timeout: NodeJS.Timeout | null
    intervalSeconds: number

    constructor(hub: Hub) {
        this.hub = hub
        this.started = false
        this.paused = false
        this.jobHandlers = {}
        this.timeout = null
        this.intervalSeconds = 10
        this.runner = null
        this.consumerPool = null
        this.producerPool = null
        this.workerUtilsPromise = null
    }

    // producer

    public async migrate(): Promise<void> {
        await (await this.getWorkerUtils()).migrate()
    }

    async connectProducer(): Promise<void> {
        await this.migrate()
    }

    async enqueue(
        jobName: string,
        job: EnqueuedJob,
        instrumentationContext?: InstrumentationContext,
        retryOnFailure = false
    ): Promise<void> {
        const jobType = 'type' in job ? job.type : 'buffer'
        const jobPayload = 'payload' in job ? job.payload : job.eventPayload
        let enqueueFn = () => this._enqueue(jobName, job)

        // This branch will be removed once we implement a Kafka queue for all jobs
        // as we've done for buffer events (see e.g. anonymous-event-buffer-consumer.ts)
        if (retryOnFailure) {
            enqueueFn = () =>
                runRetriableFunction({
                    hub: this.hub,
                    metricName: 'job_queues_enqueue',
                    metricTags: {
                        jobName,
                    },
                    maxAttempts: 10,
                    retryBaseMs: 6000,
                    retryMultiplier: 2,
                    tryFn: async () => this._enqueue(jobName, job),
                    catchFn: () => status.error('🔴', 'Exhausted attempts to enqueue job.'),
                    payload: job,
                })
        }

        await instrument(
            this.hub.statsd,
            {
                metricName: 'job_queues_enqueue',
                key: instrumentationContext?.key ?? '?',
                tag: instrumentationContext?.tag ?? '?',
                tags: { jobName, type: jobType },
                data: { timestamp: job.timestamp, type: jobType, payload: jobPayload },
            },
            enqueueFn
        )
    }

    async _enqueue(jobName: string, job: EnqueuedJob): Promise<void> {
        const workerUtils = await this.getWorkerUtils()
        await workerUtils.addJob(jobName, job, {
            runAt: new Date(job.timestamp),
            maxAttempts: 1,
            priority: 1,
            jobKey: job.jobKey,
        })
    }

    private async getWorkerUtils(): Promise<WorkerUtils> {
        if (!this.producerPool) {
            this.producerPool = await this.createPool()
        }
        if (!this.workerUtilsPromise) {
            this.workerUtilsPromise = makeWorkerUtils({
                pgPool: this.producerPool as any,
                schema: this.hub.JOB_QUEUE_GRAPHILE_SCHEMA,
                noPreparedStatements: !this.hub.JOB_QUEUE_GRAPHILE_PREPARED_STATEMENTS,
            })
        }
        return await this.workerUtilsPromise
    }

    async disconnectProducer(): Promise<void> {
        const oldWorkerUtils = await this.workerUtilsPromise
        this.workerUtilsPromise = null
        await oldWorkerUtils?.release()
        await this.producerPool?.end()
    }

    // consumer

    // TODO: Split this legacy generic "toggle" function into proper `startWorker` and `stopWorker` methods
    async syncState(): Promise<void> {
        // start running the graphile worker
        if (this.started && !this.paused && !this.runner) {
            this.consumerPool = await this.createPool()
            this.runner = await run({
                // graphile's types refer to a local node_modules version of Pool
                pgPool: this.consumerPool as Pool as any,
                schema: this.hub.JOB_QUEUE_GRAPHILE_SCHEMA,
                noPreparedStatements: !this.hub.JOB_QUEUE_GRAPHILE_PREPARED_STATEMENTS,
                concurrency: 1,
                // Do not install signal handlers, we are handled signals in
                // higher level code. If we let graphile handle signals it
                // ends up sending another SIGTERM.
                noHandleSignals: true,
                pollInterval: 2000,
                // you can set the taskList or taskDirectory but not both
                taskList: this.jobHandlers,
            })
            return
        }

        // stop running the graphile worker
        if (this.runner) {
            const oldRunner = this.runner
            this.runner = null
            await oldRunner?.stop()
            await this.consumerPool?.end()
        }
    }

    private onConnectionError(error: Error) {
        Sentry.captureException(error)
        status.error('🔴', 'Unhandled PostgreSQL error encountered in Graphile Worker!\n', error)

        // TODO: throw a wrench in the gears
    }

    async createPool(): Promise<Pool> {
        return await new Promise(async (resolve, reject) => {
            let resolved = false

            const onError = (error: Error) => {
                if (resolved) {
                    this.onConnectionError(error)
                } else {
                    reject(error)
                }
            }
            const pool = createPostgresPool(this.hub, onError)
            try {
                await pool.query('select 1')
            } catch (error) {
                reject(error)
            }
            resolved = true
            resolve(pool)
        })
    }

    async startConsumer(jobHandlers: TaskList): Promise<void> {
        this.jobHandlers = jobHandlers
        if (!this.started) {
            this.started = true
            await this.syncState()
        }
    }

    async stopConsumer(): Promise<void> {
        this.started = false
        await this.syncState()
    }

    async pauseConsumer(): Promise<void> {
        this.paused = true
        await this.syncState()
    }

    isConsumerPaused(): boolean {
        return this.paused
    }

    async resumeConsumer(): Promise<void> {
        if (this.paused) {
            this.paused = false
            await this.syncState()
        }
    }
}
