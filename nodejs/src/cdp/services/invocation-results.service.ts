import { instrumentFn } from '~/common/tracing/tracing-utils'

import { CyclotronJobInvocationResult } from '../types'
import { CapturedEventsService } from './captured-events/captured-events.service'
import { ConversionWatchersService } from './conversion-watchers/conversion-watchers.service'
import { MessageAssetsService } from './messaging/message-assets.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { HogInvocationResultsService } from './monitoring/hog-invocation-results.service'
import { WarehouseWebhooksService } from './warehouse/warehouse-webhooks.service'

/**
 * What every result sink has to expose so this service can drive it by list rather
 * than by name. `stop` is on the interface even though most sinks hold nothing to
 * release: a sink that later acquires a resource then has one obvious place to free
 * it, and teardown cannot quietly skip a sink because someone forgot to add a call.
 */
export interface ResultSink {
    flush(): Promise<void>
    stop(): Promise<void>
}

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
 * - `ConversionWatchersService`   — per-run conversion watchers, which outlive the
 *                                    run so a late conversion stays observable
 *
 * Callers interact with this one service instead of coordinating queue/flush
 * calls across the five individually. `queueInvocationResultsAndFlush` is the
 * common path — `queueInvocationResults` + `flush` are exposed for the rare
 * cases that split the two (e.g. source webhooks, which queue inline and flush
 * asynchronously after the HTTP response).
 */
export class InvocationResultsService {
    private readonly sinks: ResultSink[]

    constructor(
        public readonly monitoringService: HogFunctionMonitoringService,
        public readonly invocationResultsRowsService: HogInvocationResultsService,
        public readonly warehouseWebhooksService: WarehouseWebhooksService,
        public readonly capturedEventsService: CapturedEventsService,
        public readonly messageAssetsService: MessageAssetsService,
        public readonly conversionWatchersService: ConversionWatchersService
    ) {
        this.sinks = [
            monitoringService,
            invocationResultsRowsService,
            warehouseWebhooksService,
            capturedEventsService,
            messageAssetsService,
            conversionWatchersService,
        ]
    }

    queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        return instrumentFn(`cdpConsumer.handleEachBatch.produceResults`, async () => {
            this.monitoringService.queueInvocationResults(results)
            this.invocationResultsRowsService.queueInvocationResults(results)
            this.warehouseWebhooksService.queueInvocationResults(results)
            this.messageAssetsService.queueInvocationResults(results)
            this.conversionWatchersService.queueInvocationResults(results)
            await this.capturedEventsService.queueInvocationResults(results)
        })
    }

    async flush(): Promise<void> {
        await Promise.all(this.sinks.map((sink) => sink.flush()))
    }

    async queueInvocationResultsAndFlush(results: CyclotronJobInvocationResult[]): Promise<void> {
        await this.queueInvocationResults(results)
        await this.flush()
    }

    async stop(): Promise<void> {
        await Promise.all(this.sinks.map((sink) => sink.stop()))
    }
}
