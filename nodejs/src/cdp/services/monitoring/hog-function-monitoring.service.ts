import { Counter, Gauge, Histogram } from 'prom-client'

import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { InternalCaptureEvent, InternalCaptureService } from '~/common/services/internal-capture'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { KAFKA_WAREHOUSE_SOURCE_WEBHOOKS } from '~/config/kafka-topics'
import { APP_METRICS_OUTPUT, AppMetricsOutput, LOG_ENTRIES_OUTPUT, LogEntriesOutput } from '~/ingestion/common/outputs'
import { IngestionOutputs } from '~/ingestion/outputs/ingestion-outputs'
import { KafkaProducerWrapper } from '~/kafka/producer'

import { safeClickhouseString } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { TeamManager } from '../../../utils/team-manager'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    LogEntry,
    LogEntrySerialized,
    MetricLogSource,
    MinimalAppMetric,
    WarehouseWebhookPayload,
} from '../../types'
import { fixLogDeduplication } from '../../utils'

const counterHogFunctionMetric = new Counter({
    name: 'cdp_hog_function_metric',
    help: 'A function invocation was evaluated with an outcome',
    labelNames: ['metric_kind', 'metric_name'],
})

export const hogFunctionExecutionTimeSummary = new Histogram({
    name: 'cdp_hog_function_duration',
    help: 'Processing time of hog function execution by kind',
    labelNames: ['kind'],
})

const hogFunctionMonitoringPendingMessages = new Gauge({
    name: 'cdp_hog_function_monitoring_pending_messages',
    help: 'Number of log entries queued and waiting to be flushed to Kafka. App-metric backlog is tracked separately by app_metrics_aggregator_queued_total / app_metrics_aggregator_flushed_total. High values indicate accumulation and potential memory leak.',
})

const hogFunctionMonitoringPendingEvents = new Gauge({
    name: 'cdp_hog_function_monitoring_pending_events',
    help: 'Number of internal capture events queued and waiting to be flushed. High values indicate accumulation and potential memory leak.',
})

export type MonitoringOutput = AppMetricsOutput | LogEntriesOutput

// Check if the result is of type CyclotronJobInvocationHogFunction
export const isHogFunctionResult = (
    result: CyclotronJobInvocationResult
): result is CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> => {
    return 'hogFunction' in result.invocation
}

export class HogFunctionMonitoringService {
    queuedLogMessages: LogEntrySerialized[] = []
    eventsToCapture: InternalCaptureEvent[] = []
    warehouseWebhookPayloads: WarehouseWebhookPayload[] = []

    private warehouseKafkaProducer?: KafkaProducerWrapper
    private appMetricsAggregator: AppMetricsAggregator

    constructor(
        private outputs: IngestionOutputs<MonitoringOutput>,
        private internalCaptureService: InternalCaptureService,
        private teamManager: TeamManager
    ) {
        this.appMetricsAggregator = new AppMetricsAggregator(outputs.get(APP_METRICS_OUTPUT))
    }

    setWarehouseKafkaProducer(producer: KafkaProducerWrapper): void {
        this.warehouseKafkaProducer = producer
    }

    async flush() {
        const messages = [...this.queuedLogMessages]
        this.queuedLogMessages = []
        hogFunctionMonitoringPendingMessages.set(0)

        const eventsToCapture = [...this.eventsToCapture]
        this.eventsToCapture = []
        hogFunctionMonitoringPendingEvents.set(0)

        const warehouseWebhookPayloads = [...this.warehouseWebhookPayloads]
        this.warehouseWebhookPayloads = []

        await Promise.all([
            this.appMetricsAggregator.flush().catch((error) => {
                // Best-effort — don't disrupt processing just for metrics.
                logger.error('⚠️', `failed to flush app metrics: ${error}`, { error: String(error) })
                captureException(error)
            }),
            ...messages.map((x) => {
                const value = x ? Buffer.from(safeClickhouseString(JSON.stringify(x))) : null
                return this.outputs
                    .produce(LOG_ENTRIES_OUTPUT, {
                        key: null,
                        value,
                    })
                    .catch((error) => {
                        // NOTE: We don't hard fail here - this is because we don't want to disrupt the
                        // entire processing just for metrics.
                        logger.error('⚠️', `failed to produce log entry: ${error}`, {
                            error: String(error),
                            messageLength: value?.length,
                        })

                        captureException(error)
                    })
            }),
            ...eventsToCapture.map((event) =>
                this.internalCaptureService.capture(event).catch((error) => {
                    logger.error('Error capturing internal event', { error })
                    captureException(error)
                })
            ),
            ...(this.warehouseKafkaProducer
                ? warehouseWebhookPayloads.map((payload) =>
                      this.warehouseKafkaProducer!.produce({
                          topic: KAFKA_WAREHOUSE_SOURCE_WEBHOOKS,
                          key: Buffer.from(`${payload.team_id}:${payload.schema_id}`),
                          value: Buffer.from(
                              JSON.stringify({
                                  schema_id: payload.schema_id,
                                  team_id: payload.team_id,
                                  payload: JSON.stringify(payload.payload),
                              })
                          ),
                      }).catch((error) => {
                          logger.error('Error producing warehouse webhook payload', { error })
                          captureException(error)
                      })
                  )
                : []),
        ])
    }

    queueAppMetric(metric: MinimalAppMetric, source: MetricLogSource) {
        counterHogFunctionMetric.labels(metric.metric_kind, metric.metric_name).inc(metric.count)

        this.appMetricsAggregator.queue({
            team_id: metric.team_id,
            app_source: source,
            app_source_id: metric.app_source_id,
            instance_id: metric.instance_id,
            metric_kind: metric.metric_kind,
            metric_name: metric.metric_name,
            count: metric.count,
        })
    }

    queueAppMetrics(metrics: MinimalAppMetric[], source: MetricLogSource) {
        metrics.forEach((metric) => this.queueAppMetric(metric, source))
    }

    queueLogs(logEntries: LogEntry[], source: MetricLogSource) {
        const logs = fixLogDeduplication(
            logEntries.map((logEntry) => ({
                ...logEntry,
                log_source: source,
            }))
        )

        logs.forEach((logEntry) => {
            this.queuedLogMessages.push(logEntry)
        })
        hogFunctionMonitoringPendingMessages.set(this.queuedLogMessages.length)
    }

    async queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        return await instrumentFn(`cdpConsumer.handleEachBatch.produceResults`, async () => {
            await Promise.all(
                results.map(async (result) => {
                    const source = 'hogFunction' in result.invocation ? 'hog_function' : 'hog_flow'
                    const logSourceId = result.invocation.parentRunId
                        ? result.invocation.parentRunId
                        : result.invocation.functionId

                    this.queueLogs(
                        result.logs.map((logEntry) => ({
                            ...logEntry,
                            team_id: result.invocation.teamId,
                            log_source: source,
                            log_source_id: logSourceId,
                            instance_id: result.invocation.id,
                        })),
                        source
                    )

                    if (result.metrics) {
                        this.queueAppMetrics(result.metrics, source)
                    }

                    if (result.finished || result.error) {
                        // Process each timing entry individually instead of totaling them
                        const timings = isHogFunctionResult(result) ? (result.invocation.state?.timings ?? []) : []
                        for (const timing of timings) {
                            // Record metrics for this timing entry
                            hogFunctionExecutionTimeSummary.labels({ kind: timing.kind }).observe(timing.duration_ms)
                        }

                        this.queueAppMetric(
                            {
                                team_id: result.invocation.teamId,
                                app_source_id: result.invocation.parentRunId ?? result.invocation.functionId,
                                metric_kind: result.error ? 'failure' : 'success',
                                metric_name: result.error ? 'failed' : 'succeeded',
                                count: 1,
                            },
                            source
                        )
                    }

                    // Warehouse webhook payloads
                    for (const payload of result.warehouseWebhookPayloads ?? []) {
                        this.warehouseWebhookPayloads.push(payload)
                    }

                    // PostHog capture events
                    const capturedEvents = result.capturedPostHogEvents

                    for (const event of capturedEvents ?? []) {
                        const team = await this.teamManager.getTeam(event.team_id)
                        if (!team) {
                            continue
                        }

                        this.eventsToCapture.push({
                            team_token: team.api_token,
                            event: event.event,
                            distinct_id: event.distinct_id,
                            timestamp: event.timestamp,
                            properties: event.properties,
                        })
                        hogFunctionMonitoringPendingEvents.set(this.eventsToCapture.length)
                    }
                })
            )
        })
    }
}
