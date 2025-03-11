import { Counter } from 'prom-client'

import { KAFKA_APP_METRICS_2, KAFKA_EVENTS_PLUGIN_INGESTION, KAFKA_LOG_ENTRIES } from '../../config/kafka-topics'
import { runInstrumentedFunction } from '../../main/utils'
import { AppMetric2Type, Hub, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { castTimestampOrNow } from '../../utils/utils'
import {
    HogFunctionAppMetric,
    HogFunctionInvocationLogEntry,
    HogFunctionInvocationResult,
    HogFunctionMessageToProduce,
} from '../types'
import { fixLogDeduplication } from '../utils'
import { convertToCaptureEvent } from '../utils'

export const counterHogFunctionMetric = new Counter({
    name: 'cdp_hog_function_metric',
    help: 'A function invocation was evaluated with an outcome',
    labelNames: ['metric_kind', 'metric_name'],
})

export class HogFunctionMonitoringService {
    messagesToProduce: HogFunctionMessageToProduce[] = []

    constructor(private hub: Hub) {}

    async produceQueuedMessages() {
        const messages = [...this.messagesToProduce]
        this.messagesToProduce = []

        await this.hub
            .kafkaProducer!.queueMessages(
                messages.map((x) => ({
                    topic: x.topic,
                    messages: [
                        {
                            value: safeClickhouseString(JSON.stringify(x.value)),
                            key: x.key,
                        },
                    ],
                }))
            )
            .catch((reason) => {
                status.error('⚠️', `failed to produce message: ${reason}`)
            })
    }

    produceAppMetric(metric: HogFunctionAppMetric) {
        const appMetric: AppMetric2Type = {
            app_source: 'hog_function',
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

    produceAppMetrics(metrics: HogFunctionAppMetric[]) {
        metrics.forEach((metric) => this.produceAppMetric(metric))
    }

    produceLogs(logEntries: HogFunctionInvocationLogEntry[]) {
        const logs = fixLogDeduplication(
            logEntries.map((logEntry) => ({
                ...logEntry,
                log_source: 'hog_function',
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

    async processInvocationResults(results: HogFunctionInvocationResult[]): Promise<void> {
        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.produceResults`,
            func: async () => {
                await Promise.all(
                    results.map(async (result) => {
                        if (result.finished || result.error) {
                            this.produceAppMetric({
                                team_id: result.invocation.teamId,
                                app_source_id: result.invocation.hogFunction.id,
                                metric_kind: result.error ? 'failure' : 'success',
                                metric_name: result.error ? 'failed' : 'succeeded',
                                count: 1,
                            })
                        }

                        this.produceLogs(
                            result.logs.map((logEntry) => ({
                                ...logEntry,
                                team_id: result.invocation.hogFunction.team_id,
                                log_source: 'hog_function',
                                log_source_id: result.invocation.hogFunction.id,
                                instance_id: result.invocation.id,
                            }))
                        )

                        // Clear the logs so we don't pass them on to the next invocation
                        result.logs = []

                        // PostHog capture events
                        const capturedEvents = result.capturedPostHogEvents
                        delete result.capturedPostHogEvents

                        for (const event of capturedEvents ?? []) {
                            const team = await this.hub.teamManager.fetchTeam(event.team_id)
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
