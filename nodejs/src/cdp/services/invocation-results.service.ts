import { instrumentFn } from '~/common/tracing/tracing-utils'

import { CyclotronJobInvocationResult } from '../types'
import { CapturedEventsService } from './captured-events/captured-events.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { WarehouseWebhooksService } from './warehouse/warehouse-webhooks.service'

/**
 * Fans `CyclotronJobInvocationResult` batches out to the three sinks every
 * CDP consumer/API caller needs:
 *
 * - `HogFunctionMonitoringService` — app metrics + log entries
 * - `WarehouseWebhooksService`    — warehouse source webhook payloads
 * - `CapturedEventsService`       — PostHog events emitted via posthog.capture()
 *
 * Callers interact with this one service instead of coordinating queue/flush
 * calls across the three individually. `queueInvocationResultsAndFlush` is the
 * common path — `queueInvocationResults` + `flush` are exposed for the rare
 * cases that split the two (e.g. source webhooks, which queue inline and flush
 * asynchronously after the HTTP response).
 */
export class InvocationResultsService {
    constructor(
        public readonly monitoringService: HogFunctionMonitoringService,
        public readonly warehouseWebhooksService: WarehouseWebhooksService,
        public readonly capturedEventsService: CapturedEventsService
    ) {}

    queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        return instrumentFn(`cdpConsumer.handleEachBatch.produceResults`, async () => {
            this.monitoringService.queueInvocationResults(results)
            this.warehouseWebhooksService.queueInvocationResults(results)
            await this.capturedEventsService.queueInvocationResults(results)
        })
    }

    async flush(): Promise<void> {
        await Promise.all([
            this.monitoringService.flush(),
            this.warehouseWebhooksService.flush(),
            this.capturedEventsService.flush(),
        ])
    }

    async queueInvocationResultsAndFlush(results: CyclotronJobInvocationResult[]): Promise<void> {
        await this.queueInvocationResults(results)
        await this.flush()
    }
}
