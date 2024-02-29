import * as Sentry from '@sentry/node'
import {
    CronItem,
    makeWorkerUtils,
    parseCronItems,
    ParsedCronItem,
    run,
    Runner,
    TaskList,
    WorkerUtils,
} from 'graphile-worker'
import { Pool } from 'pg'

import { EnqueuedJob, Hub } from '../../types'
import { instrument } from '../../utils/metrics'
import { status } from '../../utils/status'
import { createPostgresPool } from '../../utils/utils'
import { graphileEnqueueJobCounter } from './metrics'

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
    crontab: ParsedCronItem[]

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
        this.crontab = []
    }

    // producer

    public async migrate(): Promise<void> {
        await (await this.getWorkerUtils()).migrate()
    }

    async connectProducer(): Promise<void> {
        await this.migrate()
    }

    async enqueue(jobName: string, job: EnqueuedJob, instrumentationContext?: InstrumentationContext): Promise<void> {
        const jobType = 'type' in job ? job.type : 'buffer'

        let jobPayload: Record<string, any> = {}
        if ('payload' in job) {
            jobPayload = job.payload
        }

        const enqueueFn = () => this._enqueue(jobName, job)

        await instrument(
            {
                metricName: `job_queues_enqueue_${jobName}`,
                key: instrumentationContext?.key ?? '?',
                tag: instrumentationContext?.tag ?? '?',
                data: { timestamp: job.timestamp, type: jobType, payload: jobPayload },
            },
            enqueueFn
        )
    }

    async _enqueue(jobName: string, job: EnqueuedJob): Promise<void> {
        try {
            await this.addJob(jobName, job)
            graphileEnqueueJobCounter.labels({ status: 'success', job: jobName }).inc()
        } catch (error) {
            graphileEnqueueJobCounter.labels({ status: 'fail', job: jobName }).inc()
            throw error
        }
    }

    async addJob(jobName: string, job: EnqueuedJob): Promise<void> {
        const workerUtils = await this.getWorkerUtils()
        await workerUtils.addJob(jobName, job, {
            runAt: job.timestamp ? new Date(job.timestamp) : undefined,
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
            status.info('🔄', 'Creating new Graphile worker runner...')
            this.consumerPool = await this.createPool()
            // KLUDGE: maxContiguousErrors is not configurable programmatically,
            // it is set to 300 via package.json, which leads the worker to retry
            // for 10 minutes (300 * pollInterval) before giving up and killing the pod.
            this.runner = await run({
                // graphile's types refer to a local node_modules version of Pool
                pgPool: this.consumerPool as Pool as any,
                schema: this.hub.JOB_QUEUE_GRAPHILE_SCHEMA,
                noPreparedStatements: !this.hub.JOB_QUEUE_GRAPHILE_PREPARED_STATEMENTS,
                concurrency: this.hub.JOB_QUEUE_GRAPHILE_CONCURRENCY,
                // Do not install signal handlers, we are handled signals in
                // higher level code. If we let graphile worker handle the signals it
                // ends up sending another SIGTERM.
                noHandleSignals: true,
                pollInterval: 2000,
                // you can set the taskList or taskDirectory but not both
                taskList: this.jobHandlers,
                parsedCronItems: this.crontab,
            })
            status.info('✅', 'Graphile worker runner created.')
            this.runner.events?.on('worker:stop', ({ error }) => {
                if (this.started) {
                    status.error('💀', `Graphile worker loop stopped unexpectedly`)
                    process.emit('uncaughtException', error ?? new Error(`Graphile worker loop stopped with no error`))
                } else {
                    status.info('🛑', 'Graphile worker loop stopped')
                }
            })
            return
        }

        // stop running the graphile worker
        if (this.runner) {
            status.info('🔄', 'Stopping Graphile worker runner')
            const oldRunner = this.runner
            this.runner = null
            await oldRunner?.stop()
            status.info('🔄', 'Stopping Graphile worker database connection')
            // NOTE: for some reason the call to this.consumerPool?.end() below
            // seems to hang, so I'm giving it one second to complete.
            await Promise.race([this.consumerPool?.end(), new Promise((resolve) => setTimeout(resolve, 1000))])
            status.info('🔴', 'Stopped Graphile worker runner')
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

            const role_name = this.hub.PLUGIN_SERVER_MODE ?? 'unknown'
            const pool = createPostgresPool(
                this.hub.JOB_QUEUE_GRAPHILE_URL,
                this.hub.POSTGRES_CONNECTION_POOL_SIZE,
                `${role_name}-graphile`,
                onError
            )
            try {
                await pool.query('select 1')
            } catch (error) {
                reject(error)
            }
            resolved = true
            resolve(pool)
        })
    }

    async start(jobHandlers: TaskList, crontab: CronItem[] = []): Promise<void> {
        this.jobHandlers = jobHandlers
        this.crontab = parseCronItems(crontab)
        if (!this.started) {
            this.started = true
            await this.syncState()

            const handlers = Object.keys(jobHandlers).join(', ')
            status.info('✅', `Graphile Worker started succesfully with the following handlers setup: ${handlers}`)
        }
    }

    async stop(): Promise<void> {
        status.info('🔄', 'Stopping Graphile worker...')
        this.started = false
        await this.syncState()
        status.info('🛑', 'Stopped Graphile worker...')
    }

    async pause(): Promise<void> {
        status.info('🔄', 'Pausing Graphile worker...')
        this.paused = true
        await this.syncState()
    }

    isPaused(): boolean {
        return this.paused
    }

    async resumeConsumer(): Promise<void> {
        if (this.paused) {
            status.info('🔄', 'Resuming Graphile worker...')
            this.paused = false
            await this.syncState()
        }
    }
}
