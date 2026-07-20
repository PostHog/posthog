import { instrumentFn } from '~/common/tracing/tracing-utils'

import { CyclotronJobInvocationResult } from '../types'
import { CapturedEventsService } from './captured-events/captured-events.service'
import { MessageAssetsService } from './messaging/message-assets.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { HogInvocationResultsService } from './monitoring/hog-invocation-results.service'
import { WarehouseWebhooksService } from './warehouse/warehouse-webhooks.service'

/**
 * Fans `CyclotronJobInvocationResult` batches out to the sinks every
 * CDP consumer/API caller needs:
 *
 * - `HogFunctionMonitoringService` — aggregated app metrics + log entries
 * - `HogInvocationResultsService`  — per-invocation lifecycle row in ClickHouse
 *                                    (powers the new runs UI + rerun path)
 * - `WarehouseWebhooksService`    — warehouse source webhook payloads
 * - `CapturedEventsService`       — PostHog events emitted via posthog.capture()
 * - `MessageAssetsService`        — rendered-email snapshots for the workflow
 *                                    Assets tab
 *
 * Callers interact with this one service instead of coordinating queue/flush
 * calls across the five individually. `queueInvocationResultsAndFlush` is the
 * common path — `queueInvocationResults` + `flush` are exposed for the rare
 * cases that split the two (e.g. source webhooks, which queue inline and flush
 * asynchronously after the HTTP response).
 */
export class InvocationResultsService {
    constructor(
        public readonly monitoringService: HogFunctionMonitoringService,
        public readonly invocationResultsRowsService: HogInvocationResultsService,
        public readonly warehouseWebhooksService: WarehouseWebhooksService,
        public readonly capturedEventsService: CapturedEventsService,
        public readonly messageAssetsService: MessageAssetsService
    ) {}

    queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        return instrumentFn(`cdpConsumer.handleEachBatch.produceResults`, async () => {
            this.monitoringService.queueInvocationResults(results)
            this.invocationResultsRowsService.queueInvocationResults(results)
            this.warehouseWebhooksService.queueInvocationResults(results)
            this.messageAssetsService.queueInvocationResults(results)
            await this.capturedEventsService.queueInvocationResults(results)
        })
    }

    async flush(): Promise<void> {
        await Promise.all([
            this.monitoringService.flush(),
            this.invocationResultsRowsService.flush(),
            this.warehouseWebhooksService.flush(),
            this.capturedEventsService.flush(),
            this.messageAssetsService.flush(),
        ])
    }

    async queueInvocationResultsAndFlush(results: CyclotronJobInvocationResult[]): Promise<void> {
        await this.queueInvocationResults(results)
        await this.flush()
    }
}
