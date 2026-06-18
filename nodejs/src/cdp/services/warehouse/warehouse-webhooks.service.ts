import { Gauge } from 'prom-client'

import { IngestionOutputs } from '../../../ingestion/outputs/ingestion-outputs'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT, WarehouseSourceWebhooksOutput } from '../../outputs/outputs'
import { CyclotronJobInvocationResult, WarehouseWebhookPayload } from '../../types'

const warehouseWebhookPendingPayloads = new Gauge({
    name: 'cdp_warehouse_webhook_pending_payloads',
    help: 'Number of warehouse webhook payloads queued and waiting to be flushed to Kafka.',
})

/**
 * Collects and flushes warehouse source webhook payloads produced by hog function
 * invocations. Lifecycle mirrors `HogFunctionMonitoringService`: callers push
 * payloads in via `queueInvocationResults` (or `queue` directly) and trigger a
 * batch emit via `flush()`.
 */
export class WarehouseWebhooksService {
    private queuedPayloads: WarehouseWebhookPayload[] = []

    constructor(private outputs: IngestionOutputs<WarehouseSourceWebhooksOutput>) {}

    queue(payloads: WarehouseWebhookPayload[]): void {
        if (payloads.length === 0) {
            return
        }
        for (const payload of payloads) {
            this.queuedPayloads.push(payload)
        }
        warehouseWebhookPendingPayloads.set(this.queuedPayloads.length)
    }

    queueInvocationResults(results: CyclotronJobInvocationResult[]): void {
        for (const result of results) {
            if (result.warehouseWebhookPayloads && result.warehouseWebhookPayloads.length > 0) {
                this.queue(result.warehouseWebhookPayloads)
            }
        }
    }

    async flush(): Promise<void> {
        const payloads = this.queuedPayloads
        this.queuedPayloads = []
        warehouseWebhookPendingPayloads.set(0)

        if (payloads.length === 0) {
            return
        }

        await Promise.all(
            payloads.map((payload) =>
                this.outputs
                    .produce(WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT, {
                        key: Buffer.from(`${payload.team_id}:${payload.schema_id}`),
                        value: Buffer.from(
                            JSON.stringify({
                                schema_id: payload.schema_id,
                                team_id: payload.team_id,
                                payload: JSON.stringify(payload.payload),
                            })
                        ),
                    })
                    .catch((error) => {
                        logger.error('Error producing warehouse webhook payload', { error })
                        captureException(error)
                    })
            )
        )
    }
}
