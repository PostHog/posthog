import { ClickHouseClient, createClient as createClickHouseClient } from '@clickhouse/client'
import https from 'https'
import { Counter } from 'prom-client'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginsServerConfig } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { RERUN_QUEUE_NAME, RerunJobState } from '../rerun/rerun-job.types'
import { RerunJobQueues, RerunPaginatorService } from '../rerun/rerun-paginator.service'
import { CyclotronV2Worker } from '../services/cyclotron-v2'
import { CyclotronV2DequeuedJob } from '../services/cyclotron-v2/types'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'

// Heartbeat interval — the cyclotron-v2 lock timeout is 30s by default, send
// roughly twice that often so a slow ClickHouse page doesn't lose the lock.
const HEARTBEAT_INTERVAL_MS = 10_000

// Delay between pages of the same rerun job. Keeps a long rerun from hot-looping
// the worker; cyclotron-v2 reschedule + dequeue overhead absorbs the wait anyway.
const RERUN_PAGE_DELAY_MS = 500

const counterRerunJobsAcked = new Counter({
    name: 'cdp_hog_invocation_rerun_jobs_acked_total',
    help: 'Rerun wrapper jobs terminated by the worker, by outcome.',
    labelNames: ['outcome'],
})

/**
 * Consumes the cyclotron-v2 'rerun' queue and drives the rerun paginator.
 *
 * Each dequeued job carries a `RerunJobState` blob describing one user's
 * rerun request (by ids or by filter). The worker:
 *   1. Parses the state.
 *   2. Runs one page of ClickHouse + rehydrate + enqueue work via `RerunPaginatorService`.
 *   3. If `progress.done` → `ack()` the wrapper job (terminal).
 *      Otherwise → `reschedule({ state: updatedState, scheduledAt: now + RERUN_PAGE_DELAY_MS })`
 *      so the next worker iteration picks it back up.
 *
 * Deploy with `PLUGIN_SERVER_MODE=cdp-rerun-worker`. Multiple replicas are
 * safe — cyclotron-v2 uses `FOR UPDATE SKIP LOCKED`.
 */
export class CdpRerunWorkerConsumer extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpRerunWorkerConsumer'

    private worker: CyclotronV2Worker | null = null
    private jobQueues: RerunJobQueues
    private paginator: RerunPaginatorService | null = null
    private clickhouseClient: ClickHouseClient | null = null

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueues: RerunJobQueues) {
        super(config, deps)
        // Used by the paginator to re-enqueue rehydrated invocations as it
        // pages — hog functions to kafka, hog flows to postgres-v2.
        this.jobQueues = jobQueues
    }

    override async start(): Promise<void> {
        if (!this.config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CYCLOTRON_NODE_DATABASE_URL is required for the rerun worker')
        }

        await this.jobQueues.hog_function.startAsProducer()
        await this.jobQueues.hog_flow.startAsProducer()

        // Dedicated ClickHouse client for the paginator. The cluster's certs
        // are issued for an internal hostname that doesn't match the one we
        // dial in (`CLICKHOUSE_HOST` is typically a service-discovery name),
        // so we override `checkServerIdentity` to no-op the hostname check
        // while leaving the rest of the chain — signature, CA trust, expiry —
        // verified. This is a narrower bypass than `rejectUnauthorized: false`,
        // which would accept any cert from any signer.
        const chScheme = this.config.CLICKHOUSE_SECURE ? 'https' : 'http'
        const chPort = this.config.CLICKHOUSE_SECURE ? 8443 : 8123
        this.clickhouseClient = createClickHouseClient({
            url: `${chScheme}://${this.config.CLICKHOUSE_HOST}:${chPort}`,
            username: this.config.CLICKHOUSE_USER,
            password: this.config.CLICKHOUSE_PASSWORD || undefined,
            database: this.config.CLICKHOUSE_DATABASE,
            request_timeout: 60_000,
            max_open_connections: 10,
            ...(this.config.CLICKHOUSE_SECURE
                ? {
                      http_agent: new https.Agent({
                          keepAlive: true,
                          maxSockets: 10,
                          // Hostname-only bypass — full chain validation still runs.
                          checkServerIdentity: () => undefined,
                      }),
                  }
                : {}),
        })

        this.paginator = new RerunPaginatorService(
            this.clickhouseClient,
            this.hogFunctionManager,
            this.hogFlowManager,
            this.invocationResultsService.invocationResultsRowsService,
            this.jobQueues,
            this.invocationResultsService.monitoringService,
            this.config.HOG_INVOCATION_RERUN_MAX_COUNT
        )

        this.worker = new CyclotronV2Worker({
            pool: { dbUrl: this.config.CYCLOTRON_NODE_DATABASE_URL },
            queueName: RERUN_QUEUE_NAME,
            // Rerun jobs are heavy (each runs a full ClickHouse query) — the
            // default of 1 pulls them one at a time so a single replica can be
            // deployed at high concurrency without overwhelming ClickHouse.
            // Tunable via CDP_RERUN_WORKER_BATCH_SIZE.
            batchMaxSize: this.config.CDP_RERUN_WORKER_BATCH_SIZE,
            pollDelayMs: 1000,
        })

        await this.worker.connect((jobs) => this.handleBatch(jobs))

        logger.info('🎬', 'CdpRerunWorkerConsumer started', { queue: RERUN_QUEUE_NAME })
    }

    override async stop(): Promise<void> {
        this.isStopping = true
        await this.worker?.disconnect()
        await this.jobQueues.hog_function.stopProducer()
        await this.jobQueues.hog_flow.stopProducer()
        await this.clickhouseClient?.close()
        await this.invocationResultsService.flush()
    }

    override isHealthy(): HealthCheckResult {
        if (this.isStopping) {
            return new HealthCheckResultError('CdpRerunWorkerConsumer is stopping', {})
        }
        if (!this.worker || !this.worker.isHealthy()) {
            return new HealthCheckResultError('CdpRerunWorkerConsumer worker not healthy', {})
        }
        return new HealthCheckResultOk()
    }

    override get service() {
        return {
            id: 'cdp-rerun-worker',
            onShutdown: () => this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    private async handleBatch(jobs: CyclotronV2DequeuedJob[]): Promise<void> {
        // Usually one job at a time (CDP_RERUN_WORKER_BATCH_SIZE defaults to 1),
        // but the loop handles a larger batch if the env is tuned up.
        for (const job of jobs) {
            await this.handleJob(job)
        }
    }

    private async handleJob(job: CyclotronV2DequeuedJob): Promise<void> {
        if (!this.paginator) {
            await job.fail()
            return
        }

        const state = this.parseState(job)
        if (!state) {
            logger.error('Rerun job has malformed state — failing', { job_id: job.id })
            counterRerunJobsAcked.labels('malformed').inc()
            await job.fail()
            return
        }

        // Heartbeat the lock while the page is running. ClickHouse queries
        // can take longer than the 30s default lock timeout for big windows.
        const heartbeat = setInterval(() => {
            job.heartbeat().catch((e) => {
                logger.warn('Failed to heartbeat rerun job', { job_id: job.id, error: String(e) })
            })
        }, HEARTBEAT_INTERVAL_MS)

        const context = { jobId: job.id, createdAt: job.created }
        try {
            const outcome = await this.paginator.processPage(job.teamId, state, context)
            const nextState = outcome.state

            if (nextState.progress.done) {
                logger.info('🎬', 'Rerun job complete', {
                    job_id: job.id,
                    team_id: job.teamId,
                    queued: nextState.progress.queued,
                    skipped: nextState.progress.skipped,
                })
                counterRerunJobsAcked.labels('done').inc()
                await job.ack()
                return
            }

            // Persist progress + reschedule for the next page.
            await job.reschedule({
                scheduledAt: new Date(Date.now() + RERUN_PAGE_DELAY_MS),
                state: Buffer.from(JSON.stringify(nextState)),
            })
        } catch (e) {
            logger.error('Rerun worker error processing job — failing', {
                job_id: job.id,
                error: e instanceof Error ? e.message : String(e),
            })
            captureException(e)
            counterRerunJobsAcked.labels('error').inc()
            // Surface the terminal failure on the Invocations tab before we
            // ack the cyclotron job — otherwise the wrapper row would be left
            // stuck on `status='running'` forever.
            await this.paginator?.writeWrapperFailure(job.teamId, state, context, e).catch((logErr) => {
                logger.error('Rerun worker failed to write wrapper failure row', {
                    job_id: job.id,
                    error: logErr instanceof Error ? logErr.message : String(logErr),
                })
            })
            await job.fail()
        } finally {
            clearInterval(heartbeat)
        }
    }

    private parseState(job: CyclotronV2DequeuedJob): RerunJobState | null {
        if (!job.state) {
            return null
        }
        try {
            return parseJSON(job.state.toString('utf8')) as RerunJobState
        } catch {
            return null
        }
    }
}
