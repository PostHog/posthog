import { createClient as createClickHouseClient } from '@clickhouse/client'
import { Client, Connection, ScheduleAlreadyRunning, ScheduleOverlapPolicy } from '@temporalio/client'
import { DataConverter } from '@temporalio/common'
import { NativeConnection, Worker } from '@temporalio/worker'
import * as fs from 'fs/promises'
import https from 'https'

import { EncryptionCodec } from '~/common/temporal/codec'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    PluginsServerConfig,
} from '~/types'

import { EmailReputationService } from '../email-reputation.service'
import { createActivities } from './activities'

export const EMAIL_REPUTATION_TASK_QUEUE = 'email-reputation-task-queue'
export const EMAIL_REPUTATION_SCHEDULE_ID = 'email-reputation-evaluation'
export const EMAIL_REPUTATION_WORKFLOW_TYPE = 'emailReputationEvaluation'

/**
 * Hosts the Temporal worker for the daily email reputation snapshot run inside the plugin server
 * and idempotently ensures the Temporal Schedule that triggers it. Follows the session-replay
 * rasterizer's Temporal setup (TLS + payload encryption) but registers a TS workflow via
 * workflowsPath rather than activities only.
 */
export class EmailReputationWorkerService {
    private worker?: Worker
    private workerConnection?: NativeConnection
    private clientConnection?: Connection
    private runPromise?: Promise<void>
    private runError?: Error

    constructor(
        private config: PluginsServerConfig,
        private deps: { postgres: PostgresRouter }
    ) {}

    public async start(): Promise<void> {
        const service = this.buildReputationService()
        const address = `${this.config.TEMPORAL_HOST}:${this.config.TEMPORAL_PORT || '7233'}`
        const namespace = this.config.TEMPORAL_NAMESPACE || 'default'
        const tls = await this.buildTLSConfig()
        const dataConverter = this.buildDataConverter()

        this.workerConnection = await NativeConnection.connect({ address, tls: tls ?? undefined })
        this.worker = await Worker.create({
            connection: this.workerConnection,
            namespace,
            taskQueue: EMAIL_REPUTATION_TASK_QUEUE,
            workflowsPath: require.resolve('./workflow'),
            activities: createActivities(service, {
                batchSize: this.config.EMAIL_REPUTATION_BATCH_SIZE,
                batchDelayMs: this.config.EMAIL_REPUTATION_BATCH_DELAY_SECONDS * 1000,
            }),
            maxConcurrentActivityTaskExecutions: 2,
            dataConverter,
        })

        // Handled, not rethrown: an unobserved rejection here would trip the process-level
        // unhandledRejection handler and stop the whole plugin server (in dev this capability
        // rides along with the full CDP set). isHealthy() surfaces the crash instead.
        this.runPromise = this.worker.run().catch((error) => {
            this.runError = error instanceof Error ? error : new Error(String(error))
            logger.error('[EmailReputationWorker] worker crashed', { error })
        })

        this.clientConnection = await Connection.connect({ address, tls: tls ?? false })
        const client = new Client({ connection: this.clientConnection, namespace, dataConverter })
        await this.ensureSchedule(client)

        logger.info('[EmailReputationWorker] started', { address, taskQueue: EMAIL_REPUTATION_TASK_QUEUE })
    }

    private buildReputationService(): EmailReputationService {
        // Internal ClickHouse uses self-signed certs with a hostname mismatch, same as the
        // cdp-rerun-worker and session-replay recording-api clients.
        const chScheme = this.config.CLICKHOUSE_SECURE ? 'https' : 'http'
        const chPort = this.config.CLICKHOUSE_SECURE ? 8443 : 8123
        const clickhouse = createClickHouseClient({
            url: `${chScheme}://${this.config.CLICKHOUSE_HOST}:${chPort}`,
            username: this.config.CLICKHOUSE_USER,
            password: this.config.CLICKHOUSE_PASSWORD || undefined,
            database: this.config.CLICKHOUSE_DATABASE,
            request_timeout: 60_000,
            max_open_connections: 10,
            ...(this.config.CLICKHOUSE_SECURE
                ? {
                      http_agent: new https.Agent({ rejectUnauthorized: false, keepAlive: true, maxSockets: 10 }), // nosemgrep: problem-based-packs.insecure-transport.js-node.bypass-tls-verification.bypass-tls-verification
                  }
                : {}),
        })
        return new EmailReputationService(clickhouse, this.deps.postgres, {
            targetVolume: this.config.EMAIL_REPUTATION_TARGET_VOLUME,
            minWindowHours: this.config.EMAIL_REPUTATION_MIN_WINDOW_HOURS,
            lookbackDays: this.config.EMAIL_REPUTATION_LOOKBACK_DAYS,
            representativeVolumeMultiplier: this.config.EMAIL_REPUTATION_VOLUME_MULTIPLIER,
            thresholds: {
                minSends: this.config.EMAIL_REPUTATION_MIN_SENDS,
                bounceWarning: this.config.EMAIL_REPUTATION_BOUNCE_WARNING_RATE,
                bounceCritical: this.config.EMAIL_REPUTATION_BOUNCE_CRITICAL_RATE,
                complaintWarning: this.config.EMAIL_REPUTATION_COMPLAINT_WARNING_RATE,
                complaintCritical: this.config.EMAIL_REPUTATION_COMPLAINT_CRITICAL_RATE,
            },
        })
    }

    private async ensureSchedule(client: Client): Promise<void> {
        const hour = this.config.EMAIL_REPUTATION_EVALUATION_HOUR_UTC
        try {
            await client.schedule.create({
                scheduleId: EMAIL_REPUTATION_SCHEDULE_ID,
                spec: { calendars: [{ hour }] },
                action: {
                    type: 'startWorkflow',
                    workflowType: EMAIL_REPUTATION_WORKFLOW_TYPE,
                    taskQueue: EMAIL_REPUTATION_TASK_QUEUE,
                    args: [],
                },
                policies: { overlap: ScheduleOverlapPolicy.SKIP },
            })
            logger.info('[EmailReputationWorker] created schedule', { hour })
        } catch (error) {
            if (error instanceof ScheduleAlreadyRunning) {
                // Update the existing schedule so config stays authoritative (hour changes, or a
                // stale spec left by an earlier build, would otherwise be silently ignored forever).
                await client.schedule.getHandle(EMAIL_REPUTATION_SCHEDULE_ID).update((previous) => ({
                    ...previous,
                    spec: { calendars: [{ hour }] },
                    // Reassert the action too: a schedule left by an older build could otherwise
                    // keep dispatching a stale workflow type/queue/args forever.
                    action: {
                        type: 'startWorkflow',
                        workflowType: EMAIL_REPUTATION_WORKFLOW_TYPE,
                        taskQueue: EMAIL_REPUTATION_TASK_QUEUE,
                        args: [],
                    },
                    policies: { ...previous.policies, overlap: ScheduleOverlapPolicy.SKIP },
                }))
                logger.info('[EmailReputationWorker] updated existing schedule', { hour })
                return
            }
            throw error
        }
    }

    private async buildTLSConfig(): Promise<{
        serverRootCACertificate: Buffer
        clientCertPair: { crt: Buffer; key: Buffer }
    } | null> {
        const { TEMPORAL_CLIENT_ROOT_CA, TEMPORAL_CLIENT_CERT, TEMPORAL_CLIENT_KEY } = this.config
        if (!(TEMPORAL_CLIENT_ROOT_CA && TEMPORAL_CLIENT_CERT && TEMPORAL_CLIENT_KEY)) {
            return null
        }

        let systemCAs = Buffer.alloc(0)
        try {
            systemCAs = Buffer.from(await fs.readFile('/etc/ssl/certs/ca-certificates.crt'))
        } catch {
            // System CA bundle not found — use only the provided root CA
        }

        return {
            serverRootCACertificate: Buffer.concat([systemCAs, Buffer.from(TEMPORAL_CLIENT_ROOT_CA)]),
            clientCertPair: {
                crt: Buffer.from(TEMPORAL_CLIENT_CERT),
                key: Buffer.from(TEMPORAL_CLIENT_KEY),
            },
        }
    }

    private buildDataConverter(): DataConverter | undefined {
        const { TEMPORAL_SECRET_KEY, TEMPORAL_FALLBACK_SECRET_KEYS } = this.config
        if (!TEMPORAL_SECRET_KEY) {
            logger.warn('[EmailReputationWorker] no TEMPORAL_SECRET_KEY configured — payloads will not be encrypted')
            return undefined
        }
        const fallbackKeys = (TEMPORAL_FALLBACK_SECRET_KEYS ?? '')
            .split(',')
            .map((key) => key.trim())
            .filter(Boolean)
        return { payloadCodecs: [new EncryptionCodec(TEMPORAL_SECRET_KEY, fallbackKeys)] }
    }

    public isHealthy(): HealthCheckResult {
        const state = this.worker?.getState()
        if (state !== 'RUNNING') {
            return new HealthCheckResultError(
                `Email reputation Temporal worker is ${state ?? 'not started'}${this.runError ? `: ${this.runError.message}` : ''}`,
                {}
            )
        }
        return new HealthCheckResultOk()
    }

    public async stop(): Promise<void> {
        // shutdown() throws IllegalStateError unless the worker is RUNNING (e.g. it already
        // crashed) — skipping it must not skip the connection cleanup below.
        if (this.worker?.getState() === 'RUNNING') {
            this.worker.shutdown()
        }
        // run() resolves once shutdown drains in-flight activities
        await this.runPromise?.catch(() => {})
        await this.clientConnection?.close().catch(() => {})
        await this.workerConnection?.close().catch(() => {})
    }

    public get service(): PluginServerService {
        return {
            id: 'email-reputation-evaluator',
            onShutdown: () => this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }
}
