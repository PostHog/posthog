import { Counter, Histogram } from 'prom-client'

import { InternalCaptureEvent } from '~/common/services/internal-capture'
import { instrumentFn } from '~/common/tracing/tracing-utils'

import { Hub, TimestampFormat } from '../../../types'
import { safeClickhouseString } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { castTimestampOrNow } from '../../../utils/utils'
import {
    AppMetricType,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    LogEntry,
    LogEntrySerialized,
    MetricLogSource,
    MinimalAppMetric,
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

export type HogFunctionMonitoringMessage = {
    topic: string
    value: LogEntrySerialized | AppMetricType
    headers?: Record<string, string>
    key: string
}

// Check if the result is of type CyclotronJobInvocationHogFunction
export const isHogFunctionResult = (
    result: CyclotronJobInvocationResult
): result is CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> => {
    return 'hogFunction' in result.invocation
}

export class HogFunctionMonitoringService {
    messagesToProduce: HogFunctionMonitoringMessage[] = []
    eventsToCapture: InternalCaptureEvent[] = []

    constructor(private hub: Hub) {}

    async flush() {
        const messages = [...this.messagesToProduce]
        this.messagesToProduce = []
        const eventsToCapture = [...this.eventsToCapture]
        this.eventsToCapture = []

        await Promise.all([
            ...messages.map((x) => {
                const value = x.value ? Buffer.from(safeClickhouseString(JSON.stringify(x.value))) : null
                return this.hub.kafkaProducer
                    .produce({
                        topic: x.topic,
                        key: x.key ? Buffer.from(x.key) : null,
                        value,
                        headers: x.headers,
                    })
                    .catch((error) => {
                        // NOTE: We don't hard fail here - this is because we don't want to disrupt the
                        // entire processing just for metrics.
                        logger.error('⚠️', `failed to produce message: ${error}`, {
                            error: String(error),
                            messageLength: value?.length,
                            topic: x.topic,
                            key: x.key,
                            headers: x.headers,
                        })

                        captureException(error)
                    })
            }),
            eventsToCapture.map((event) =>
                this.hub.internalCaptureService.capture(event).catch((error) => {
                    logger.error('Error capturing internal event', { error })
                    captureException(error)
                })
            ),
        ])
    }

    queueAppMetric(metric: MinimalAppMetric, source: MetricLogSource) {
        const appMetric: AppMetricType = {
            app_source: source,
            ...metric,
            timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
        }

        counterHogFunctionMetric.labels(metric.metric_kind, metric.metric_name).inc(appMetric.count)

        this.messagesToProduce.push({
            topic: this.hub.HOG_FUNCTION_MONITORING_APP_METRICS_TOPIC,
            value: appMetric,
            key: appMetric.app_source_id,
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
            this.messagesToProduce.push({
                topic: this.hub.HOG_FUNCTION_MONITORING_LOG_ENTRIES_TOPIC,
                value: logEntry,
                key: logEntry.instance_id,
            })
        })
    }

    async queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        return await instrumentFn(`cdpConsumer.handleEachBatch.produceResults`, async () => {
            await Promise.all(
                results.map(async (result) => {
                    const source = 'hogFunction' in result.invocation ? 'hog_function' : 'hog_flow'

                    this.queueLogs(
                        result.logs.map((logEntry) => ({
                            ...logEntry,
                            team_id: result.invocation.teamId,
                            log_source: source,
                            log_source_id: result.invocation.functionId,
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
                                app_source_id: result.invocation.functionId,
                                metric_kind: result.error ? 'failure' : 'success',
                                metric_name: result.error ? 'failed' : 'succeeded',
                                count: 1,
                            },
                            source
                        )
                    }

                    // PostHog capture events
                    const capturedEvents = result.capturedPostHogEvents

                    for (const event of capturedEvents ?? []) {
                        const team = await this.hub.teamManager.getTeam(event.team_id)
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
                    }
                })
            )
        })
    }
}
