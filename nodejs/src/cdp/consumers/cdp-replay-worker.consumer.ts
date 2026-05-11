import { ClickHouseClient, createClient as createClickHouseClient } from '@clickhouse/client'
import https from 'https'
import { Counter } from 'prom-client'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginsServerConfig } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { REPLAY_QUEUE_NAME, ReplayJobState } from '../replay/replay-job.types'
import { ReplayPaginatorService } from '../replay/replay-paginator.service'
import { CyclotronV2Worker } from '../services/cyclotron-v2'
import { CyclotronV2DequeuedJob } from '../services/cyclotron-v2/types'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'

// Heartbeat interval — the cyclotron-v2 lock timeout is 30s by default, send
// roughly twice that often so a slow ClickHouse page doesn't lose the lock.
const HEARTBEAT_INTERVAL_MS = 10_000

// Delay between pages of the same replay job. Keeps a long replay from hot-looping
// the worker; cyclotron-v2 reschedule + dequeue overhead absorbs the wait anyway.
const REPLAY_PAGE_DELAY_MS = 500

const counterReplayJobsAcked = new Counter({
    name: 'cdp_hog_invocation_replay_jobs_acked_total',
    help: 'Replay wrapper jobs terminated by the worker, by outcome.',
    labelNames: ['outcome'],
})

/**
 * Consumes the cyclotron-v2 'replay' queue and drives the replay paginator.
 *
 * Each dequeued job carries a `ReplayJobState` blob describing one user's
 * replay request (by ids or by filter). The worker:
 *   1. Parses the state.
 *   2. Runs one page of ClickHouse + rehydrate + enqueue work via `ReplayPaginatorService`.
 *   3. If `progress.done` → `ack()` the wrapper job (terminal).
 *      Otherwise → `reschedule({ state: updatedState, scheduledAt: now + REPLAY_PAGE_DELAY_MS })`
 *      so the next worker iteration picks it back up.
 *
 * Deploy with `PLUGIN_SERVER_MODE=cdp-replay-worker`. Multiple replicas are
 * safe — cyclotron-v2 uses `FOR UPDATE SKIP LOCKED`.
 */
export class CdpReplayWorkerConsumer extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpReplayWorkerConsumer'

    private worker: CyclotronV2Worker | null = null
    private cyclotronJobQueue: CyclotronJobQueue
    private paginator: ReplayPaginatorService | null = null
    private clickhouseClient: ClickHouseClient | null = null

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        // Used by the paginator to re-enqueue invocations as it pages.
        this.cyclotronJobQueue = new CyclotronJobQueue(config.CONSUMER_BATCH_SIZE, config.KAFKA_CLIENT_RACK, config)
    }

    override async start(): Promise<void> {
        if (!this.config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CYCLOTRON_NODE_DATABASE_URL is required for the replay worker')
        }

        await this.cyclotronJobQueue.startAsProducer()

        // Dedicated ClickHouse client for the paginator. Same shape the
        // recording-api uses — accepts the cluster's self-signed certs.
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
                ? { http_agent: new https.Agent({ rejectUnauthorized: false, keepAlive: true, maxSockets: 10 }) } // nosemgrep: problem-based-packs.insecure-transport.js-node.bypass-tls-verification.bypass-tls-verification
                : {}),
        })

        this.paginator = new ReplayPaginatorService(
            this.clickhouseClient,
            this.hogFunctionManager,
            this.hogFlowManager,
            this.invocationResultsService.invocationResultsRowsService,
            this.cyclotronJobQueue
        )

        this.worker = new CyclotronV2Worker({
            pool: { dbUrl: this.config.CYCLOTRON_NODE_DATABASE_URL },
            queueName: REPLAY_QUEUE_NAME,
            // Replay jobs are heavy (each runs a full ClickHouse query) — pull
            // them one at a time so a single replica can be deployed at high
            // concurrency without overwhelming ClickHouse.
            batchMaxSize: 1,
            pollDelayMs: 1000,
        })

        await this.worker.connect((jobs) => this.handleBatch(jobs))

        logger.info('🎬', 'CdpReplayWorkerConsumer started', { queue: REPLAY_QUEUE_NAME })
    }

    override async stop(): Promise<void> {
        this.isStopping = true
        await this.worker?.disconnect()
        await this.cyclotronJobQueue.stop()
        await this.clickhouseClient?.close()
        await this.invocationResultsService.flush()
    }

    override isHealthy(): HealthCheckResult {
        if (this.isStopping) {
            return new HealthCheckResultError('CdpReplayWorkerConsumer is stopping', {})
        }
        if (!this.worker || !this.worker.isHealthy()) {
            return new HealthCheckResultError('CdpReplayWorkerConsumer worker not healthy', {})
        }
        return new HealthCheckResultOk()
    }

    override get service() {
        return {
            id: 'cdp-replay-worker',
            onShutdown: () => this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    private async handleBatch(jobs: CyclotronV2DequeuedJob[]): Promise<void> {
        // batchMaxSize=1, so this is effectively one job at a time. The loop
        // exists for symmetry with other consumer base classes.
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
            logger.error('Replay job has malformed state — failing', { job_id: job.id })
            counterReplayJobsAcked.labels('malformed').inc()
            await job.fail()
            return
        }

        // Heartbeat the lock while the page is running. ClickHouse queries
        // can take longer than the 30s default lock timeout for big windows.
        const heartbeat = setInterval(() => {
            job.heartbeat().catch((e) => {
                logger.warn('Failed to heartbeat replay job', { job_id: job.id, error: String(e) })
            })
        }, HEARTBEAT_INTERVAL_MS)

        try {
            const outcome = await this.paginator.processPage(job.teamId, state)
            const nextState = outcome.state

            if (nextState.progress.done) {
                logger.info('🎬', 'Replay job complete', {
                    job_id: job.id,
                    team_id: job.teamId,
                    queued: nextState.progress.queued,
                    skipped: nextState.progress.skipped,
                })
                counterReplayJobsAcked.labels('done').inc()
                await job.ack()
                return
            }

            // Persist progress + reschedule for the next page.
            await job.reschedule({
                scheduledAt: new Date(Date.now() + REPLAY_PAGE_DELAY_MS),
                state: Buffer.from(JSON.stringify(nextState)),
            })
        } catch (e) {
            logger.error('Replay worker error processing job — failing', {
                job_id: job.id,
                error: e instanceof Error ? e.message : String(e),
            })
            captureException(e)
            counterReplayJobsAcked.labels('error').inc()
            await job.fail()
        } finally {
            clearInterval(heartbeat)
        }
    }

    private parseState(job: CyclotronV2DequeuedJob): ReplayJobState | null {
        if (!job.state) {
            return null
        }
        try {
            return parseJSON(job.state.toString('utf8')) as ReplayJobState
        } catch {
            return null
        }
    }
}
