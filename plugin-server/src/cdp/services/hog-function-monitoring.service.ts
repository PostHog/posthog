import { Counter } from 'prom-client'

import { KAFKA_APP_METRICS_2, KAFKA_EVENTS_PLUGIN_INGESTION, KAFKA_LOG_ENTRIES } from '../../config/kafka-topics'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { castTimestampOrNow } from '../../utils/utils'
import { AppMetricType, CyclotronJobInvocationResult, LogEntry, LogEntrySerialized, MinimalAppMetric } from '../types'
import { fixLogDeduplication } from '../utils'
import { convertToCaptureEvent } from '../utils'

const counterHogFunctionMetric = new Counter({
    name: 'cdp_hog_function_metric',
    help: 'A function invocation was evaluated with an outcome',
    labelNames: ['metric_kind', 'metric_name'],
})

export type HogFunctionMonitoringMessage = {
    topic: string
    value: LogEntrySerialized | AppMetricType
    key: string
}

export class HogFunctionMonitoringService {
    messagesToProduce: HogFunctionMonitoringMessage[] = []

    constructor(private hub: Hub) {}

    async produceQueuedMessages() {
        const messages = [...this.messagesToProduce]
        this.messagesToProduce = []

        await Promise.all(
            messages.map((x) => {
                const value = x.value ? Buffer.from(safeClickhouseString(JSON.stringify(x.value))) : null
                return this.hub.kafkaProducer
                    .produce({
                        topic: x.topic,
                        key: x.key ? Buffer.from(x.key) : null,
                        value,
                    })
                    .catch((error) => {
                        // NOTE: We don't hard fail here - this is because we don't want to disrupt the
                        // entire processing just for metrics.
                        logger.error('⚠️', `failed to produce message: ${error}`, {
                            error: String(error),
                            messageLength: value?.length,
                            topic: x.topic,
                            key: x.key,
                        })

                        captureException(error)
                    })
            })
        )
    }

    produceAppMetric(metric: MinimalAppMetric, source: 'hog_function' | 'hog_flow') {
        const appMetric: AppMetricType = {
            app_source: source,
            ...metric,
            timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
        }

        counterHogFunctionMetric.labels(metric.metric_kind, metric.metric_name).inc(appMetric.count)

        this.messagesToProduce.push({
            topic: KAFKA_APP_METRICS_2,
            value: appMetric,
            key: appMetric.app_source_id,
        })
    }

    produceAppMetrics(metrics: MinimalAppMetric[], source: 'hog_function' | 'hog_flow') {
        metrics.forEach((metric) => this.produceAppMetric(metric, source))
    }

    produceLogs(logEntries: LogEntry[], source: 'hog_function' | 'hog_flow') {
        const logs = fixLogDeduplication(
            logEntries.map((logEntry) => ({
                ...logEntry,
                log_source: source,
            }))
        )

        logs.forEach((logEntry) => {
            this.messagesToProduce.push({
                topic: KAFKA_LOG_ENTRIES,
                value: logEntry,
                key: logEntry.instance_id,
            })
        })
    }

    async processInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.produceResults`,
            func: async () => {
                await Promise.all(
                    results.map(async (result) => {
                        const source = 'hogFunction' in result.invocation ? 'hog_function' : 'hog_flow'
                        if (result.finished || result.error) {
                            this.produceAppMetric(
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

                        this.produceLogs(
                            result.logs.map((logEntry) => ({
                                ...logEntry,
                                team_id: result.invocation.teamId,
                                log_source: 'hog_function',
                                log_source_id: result.invocation.functionId,
                                instance_id: result.invocation.id,
                            })),
                            source
                        )

                        if (result.metrics) {
                            this.produceAppMetrics(result.metrics, source)
                        }

                        // Clear the logs so we don't pass them on to the next invocation
                        result.logs = []

                        // PostHog capture events
                        const capturedEvents = result.capturedPostHogEvents
                        delete result.capturedPostHogEvents

                        for (const event of capturedEvents ?? []) {
                            const team = await this.hub.teamManager.getTeam(event.team_id)
                            if (!team) {
                                continue
                            }
                            this.messagesToProduce.push({
                                topic: KAFKA_EVENTS_PLUGIN_INGESTION,
                                value: convertToCaptureEvent(event, team),
                                key: `${team.api_token}:${event.distinct_id}`,
                            })
                        }
                    })
                )
            },
        })
    }
}
