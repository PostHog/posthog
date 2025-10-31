import { Client, Connection, TLSConfig, WorkflowHandle } from '@temporalio/client'
import fs from 'fs/promises'
import { Counter } from 'prom-client'

import { Hub } from '../../types'
import { logger } from '../../utils/logger'

const EVALUATION_TASK_QUEUE = 'general-purpose-task-queue'

const temporalWorkflowsStarted = new Counter({
    name: 'evaluation_run_workflows_started',
    help: 'Number of evaluation run workflows started',
    labelNames: ['status'],
})

export class TemporalService {
    private client?: Client
    private connecting?: Promise<Client>

    constructor(private hub: Hub) {}

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
        const { TEMPORAL_CLIENT_ROOT_CA, TEMPORAL_CLIENT_CERT, TEMPORAL_CLIENT_KEY } = this.hub

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

    private async createClient(): Promise<Client> {
        const tls = await this.buildTLSConfig()

        const port = this.hub.TEMPORAL_PORT || '7233'
        const address = `${this.hub.TEMPORAL_HOST}:${port}`

        const connection = await Connection.connect({ address, tls })

        const client = new Client({
            connection,
            namespace: this.hub.TEMPORAL_NAMESPACE || 'default',
        })

        logger.info('✅ Connected to Temporal', {
            address,
            namespace: this.hub.TEMPORAL_NAMESPACE,
            tlsEnabled: tls !== false,
        })

        return client
    }

    async startEvaluationRunWorkflow(evaluationId: string, targetEventId: string): Promise<WorkflowHandle> {
        const client = await this.ensureConnected()

        const workflowId = `${evaluationId}-${targetEventId}-ingestion`

        const handle = await client.workflow.start('run-evaluation', {
            args: [
                {
                    evaluation_id: evaluationId,
                    target_event_id: targetEventId,
                },
            ],
            taskQueue: EVALUATION_TASK_QUEUE,
            workflowId,
            workflowIdConflictPolicy: 'USE_EXISTING',
        })

        temporalWorkflowsStarted.labels({ status: 'success' }).inc()

        logger.debug('Started evaluation run workflow', {
            workflowId,
            evaluationId,
            targetEventId,
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
