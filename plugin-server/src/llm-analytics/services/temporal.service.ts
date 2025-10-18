import { Client, Connection, TLSConfig } from '@temporalio/client'
import { Counter } from 'prom-client'

import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'

const temporalWorkflowsStarted = new Counter({
    name: 'evaluation_temporal_workflows_started',
    help: 'Number of evaluation workflows started',
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

        // Create connection first
        const connection = await Connection.connect({
            address: this.hub.TEMPORAL_HOST || 'localhost:7233',
            tls,
        })

        // Then create client with connection
        const client = new Client({
            connection,
            namespace: this.hub.TEMPORAL_NAMESPACE || 'default',
        })

        logger.info('✅ Connected to Temporal', {
            address: this.hub.TEMPORAL_HOST,
            namespace: this.hub.TEMPORAL_NAMESPACE,
            tlsEnabled: tls !== false,
        })

        return client
    }

    async startEvaluationWorkflow(evaluationId: string, targetEventId: string): Promise<void> {
        try {
            const client = await this.ensureConnected()

            const workflowId = `eval-${evaluationId}-${targetEventId}-${Date.now()}`

            await client.workflow.start('run-evaluation', {
                args: [
                    {
                        evaluation_id: evaluationId,
                        target_event_id: targetEventId,
                    },
                ],
                taskQueue: 'general-purpose-task-queue',
                workflowId,
            })

            temporalWorkflowsStarted.labels({ status: 'success' }).inc()

            logger.debug('Started evaluation workflow', {
                workflowId,
                evaluationId,
                targetEventId,
            })
        } catch (error: unknown) {
            temporalWorkflowsStarted.labels({ status: 'error' }).inc()
            logger.error('Failed to start evaluation workflow', {
                evaluationId,
                targetEventId,
                error: error instanceof Error ? error.message : String(error),
            })
            captureException(error)
            // Don't throw - we don't want to fail event processing
        }
    }

    async disconnect(): Promise<void> {
        if (this.client) {
            await this.client.connection.close()
            this.client = undefined
        }
    }
}
