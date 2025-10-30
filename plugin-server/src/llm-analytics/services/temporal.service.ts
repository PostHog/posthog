import { Client, Connection, TLSConfig, WorkflowHandle } from '@temporalio/client'
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

    private async createClient(): Promise<Client> {
        // Configure TLS if certificates are provided (for production)
        let tls: TLSConfig | boolean = false
        if (this.hub.TEMPORAL_CLIENT_ROOT_CA && this.hub.TEMPORAL_CLIENT_CERT && this.hub.TEMPORAL_CLIENT_KEY) {
            tls = {
                serverRootCACertificate: Buffer.from(this.hub.TEMPORAL_CLIENT_ROOT_CA),
                clientCertPair: {
                    crt: Buffer.from(this.hub.TEMPORAL_CLIENT_CERT),
                    key: Buffer.from(this.hub.TEMPORAL_CLIENT_KEY),
                },
            }
        }

        const port = this.hub.TEMPORAL_PORT || '7233'
        const address = `${this.hub.TEMPORAL_HOST}:${port}`

        // Create connection first
        const connection = await Connection.connect({ address, tls })

        // Then create client with connection
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
