import {
    Client,
    Connection,
    DataConverter,
    TLSConfig,
    WorkflowExecutionAlreadyStartedError,
    WorkflowHandle,
} from '@temporalio/client'
import * as crypto from 'crypto'
import fs from 'fs/promises'
import { Counter } from 'prom-client'

import { EncryptionCodec } from '~/common/temporal/codec'
import { isDevEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'

import { RawKafkaEvent } from '../../types'
import { AIObservabilityConfig } from '../config'

export type TemporalServiceConfig = Pick<
    AIObservabilityConfig,
    | 'TEMPORAL_CLIENT_ROOT_CA'
    | 'TEMPORAL_CLIENT_CERT'
    | 'TEMPORAL_CLIENT_KEY'
    | 'TEMPORAL_PORT'
    | 'TEMPORAL_HOST'
    | 'TEMPORAL_NAMESPACE'
    | 'TEMPORAL_SECRET_KEY'
    | 'TEMPORAL_FALLBACK_SECRET_KEYS'
>

const EVALUATION_TASK_QUEUE = isDevEnv() ? 'development-task-queue' : 'llm-analytics-evals-task-queue'

const EVALUATION_WORKFLOW_PREFIXES = {
    hog: 'llma-hog-eval',
    llm_judge: 'llma-llm-eval',
    sentiment: 'llma-sentiment-eval',
} as const

export type EvaluationWorkflowRuntime = keyof typeof EVALUATION_WORKFLOW_PREFIXES

export function isEvaluationWorkflowRuntime(
    evaluationRuntime: unknown
): evaluationRuntime is EvaluationWorkflowRuntime {
    return typeof evaluationRuntime === 'string' && Object.hasOwn(EVALUATION_WORKFLOW_PREFIXES, evaluationRuntime)
}

function getEvaluationWorkflowPrefix(evaluationRuntime: EvaluationWorkflowRuntime): string {
    return EVALUATION_WORKFLOW_PREFIXES[evaluationRuntime]
}

// Fallback aggregation window when an evaluation's target_config carries no window_seconds.
// Per-eval values come from the eval config; this only applies to legacy/empty configs. Must
// comfortably exceed a single LLM turn (seconds, or a few minutes with heavy tool usage).
export const DEFAULT_TRACE_EVALUATION_WINDOW_SECONDS = 30 * 60

const temporalWorkflowsStarted = new Counter({
    name: 'evaluation_run_workflows_started',
    help: 'Number of evaluation run workflows started',
    labelNames: ['status'],
})

/**
 * Trace ids are user-controlled and unbounded; Temporal workflow ids are capped at 1000
 * bytes. Hash anything suspiciously long so the workflow id stays valid while remaining
 * deterministic for dedup.
 */
export function workflowSafeTraceId(traceId: string): string {
    if (traceId.length <= 128) {
        return traceId
    }
    return crypto.createHash('md5').update(traceId).digest('hex')
}

export class TemporalService {
    private client?: Client
    private connecting?: Promise<Client>

    constructor(private config: TemporalServiceConfig) {}

    private async ensureConnected(): Promise<Client> {
        if (this.client) {
            return this.client
        }

        if (this.connecting) {
            return await this.connecting
        }

        this.connecting = this.createClient()
        this.client = await this.connecting
        this.connecting = undefined

        return this.client
    }

    private async buildTLSConfig(): Promise<TLSConfig | false> {
        const { TEMPORAL_CLIENT_ROOT_CA, TEMPORAL_CLIENT_CERT, TEMPORAL_CLIENT_KEY } = this.config

        if (!(TEMPORAL_CLIENT_ROOT_CA && TEMPORAL_CLIENT_CERT && TEMPORAL_CLIENT_KEY)) {
            return false
        }

        let systemCAs = Buffer.alloc(0)
        try {
            const fileBuffer = await fs.readFile('/etc/ssl/certs/ca-certificates.crt')
            systemCAs = Buffer.from(fileBuffer)
        } catch (err: any) {
            if (err.code !== 'ENOENT') {
                logger.warn('⚠️ Failed to load system CA bundle', { err })
            } else {
                logger.debug('ℹ️ System CA bundle not found — using only provided root CA')
            }
        }

        const combinedCA = Buffer.concat([systemCAs, Buffer.from(TEMPORAL_CLIENT_ROOT_CA)])

        logger.debug('🔐 TLS configuration built', {
            systemCABundle: systemCAs.length > 0,
            combinedCABytes: combinedCA.length,
        })

        return {
            serverRootCACertificate: combinedCA,
            clientCertPair: {
                crt: Buffer.from(TEMPORAL_CLIENT_CERT),
                key: Buffer.from(TEMPORAL_CLIENT_KEY),
            },
        }
    }

    private buildDataConverter(): DataConverter | undefined {
        const { TEMPORAL_SECRET_KEY, TEMPORAL_FALLBACK_SECRET_KEYS } = this.config

        if (!TEMPORAL_SECRET_KEY) {
            logger.warn('⚠️ No TEMPORAL_SECRET_KEY configured — workflow payloads will NOT be encrypted')
            return undefined
        }

        const fallbackKeys = (TEMPORAL_FALLBACK_SECRET_KEYS ?? '')
            .split(',')
            .map((key) => key.trim())
            .filter(Boolean)

        return { payloadCodecs: [new EncryptionCodec(TEMPORAL_SECRET_KEY, fallbackKeys)] }
    }

    private async createClient(): Promise<Client> {
        const tls = await this.buildTLSConfig()

        const port = this.config.TEMPORAL_PORT || '7233'
        const address = `${this.config.TEMPORAL_HOST}:${port}`

        const connection = await Connection.connect({ address, tls })

        const dataConverter = this.buildDataConverter()

        const client = new Client({
            connection,
            namespace: this.config.TEMPORAL_NAMESPACE || 'default',
            dataConverter,
        })

        logger.info('✅ Connected to Temporal', {
            address,
            namespace: this.config.TEMPORAL_NAMESPACE,
            tlsEnabled: tls !== false,
            payloadEncryption: dataConverter !== undefined,
        })

        return client
    }

    async startEvaluationRunWorkflow(
        evaluationId: string,
        event: RawKafkaEvent,
        evaluationRuntime: EvaluationWorkflowRuntime
    ): Promise<WorkflowHandle> {
        const client = await this.ensureConnected()

        if (!isEvaluationWorkflowRuntime(evaluationRuntime)) {
            throw new Error(`Unsupported evaluation runtime: ${evaluationRuntime}`)
        }
        const prefix = getEvaluationWorkflowPrefix(evaluationRuntime)
        const workflowId = `${prefix}-${evaluationId}-${event.uuid}-ingestion`

        const handle = await client.workflow.start('run-evaluation', {
            args: [
                {
                    evaluation_id: evaluationId,
                    event_data: event,
                },
            ],
            taskQueue: EVALUATION_TASK_QUEUE,
            workflowId,
            workflowIdConflictPolicy: 'USE_EXISTING',
            workflowIdReusePolicy: 'ALLOW_DUPLICATE_FAILED_ONLY',
            workflowTaskTimeout: '2 minutes',
        })

        temporalWorkflowsStarted.labels({ status: 'success' }).inc()

        logger.debug('Started evaluation run workflow', {
            workflowId,
            evaluationId,
            targetEventId: event.uuid,
            timestamp: event.timestamp,
        })

        return handle
    }

    /**
     * Start (or join) the delayed whole-trace evaluation for (evaluation, trace).
     *
     * The workflow id deliberately excludes the event uuid: the first matching generation of a
     * trace creates the workflow, and every later one lands on it as a no-op (USE_EXISTING
     * while pending/running). Once a run completed, ALLOW_DUPLICATE_FAILED_ONLY rejects new
     * starts — a trace is evaluated at most once per evaluation, which also caps the damage
     * from runaway shared trace ids ("0", "fixed_id", ...). Returns null when the trace was
     * already evaluated.
     */
    async startTraceEvaluationRunWorkflow(
        evaluationId: string,
        event: RawKafkaEvent,
        traceId: string,
        sessionId: string | null,
        windowSeconds: number
    ): Promise<WorkflowHandle | null> {
        const client = await this.ensureConnected()

        const workflowId = `llma-trace-eval-${evaluationId}-${workflowSafeTraceId(traceId)}`

        try {
            const handle = await client.workflow.start('run-trace-evaluation', {
                args: [
                    {
                        evaluation_id: evaluationId,
                        team_id: event.team_id,
                        trace_id: traceId,
                        distinct_id: event.distinct_id,
                        session_id: sessionId,
                        window_seconds: windowSeconds,
                    },
                ],
                taskQueue: EVALUATION_TASK_QUEUE,
                workflowId,
                workflowIdConflictPolicy: 'USE_EXISTING',
                workflowIdReusePolicy: 'ALLOW_DUPLICATE_FAILED_ONLY',
                workflowTaskTimeout: '2 minutes',
            })

            temporalWorkflowsStarted.labels({ status: 'success' }).inc()

            logger.debug('Started trace evaluation run workflow', {
                workflowId,
                evaluationId,
                traceId,
                timestamp: event.timestamp,
            })

            return handle
        } catch (error) {
            // A completed run for this (evaluation, trace) already exists — the expected
            // outcome for every matching event after the trace was evaluated.
            if (error instanceof WorkflowExecutionAlreadyStartedError) {
                temporalWorkflowsStarted.labels({ status: 'already_completed' }).inc()
                return null
            }
            throw error
        }
    }

    async startTaggerRunWorkflow(taggerId: string, event: RawKafkaEvent): Promise<WorkflowHandle> {
        const client = await this.ensureConnected()

        const workflowId = `llma-tagger-${taggerId}-${event.uuid}-ingestion`

        const handle = await client.workflow.start('run-tagger', {
            args: [
                {
                    tagger_id: taggerId,
                    event_data: event,
                },
            ],
            taskQueue: EVALUATION_TASK_QUEUE,
            workflowId,
            workflowIdConflictPolicy: 'USE_EXISTING',
            workflowIdReusePolicy: 'ALLOW_DUPLICATE_FAILED_ONLY',
            workflowTaskTimeout: '2 minutes',
        })

        temporalWorkflowsStarted.labels({ status: 'success' }).inc()

        logger.debug('Started tagger run workflow', {
            workflowId,
            taggerId,
            targetEventId: event.uuid,
            timestamp: event.timestamp,
        })

        return handle
    }

    async disconnect(): Promise<void> {
        if (this.client) {
            await this.client.connection.close()
            this.client = undefined
        }
    }
}
