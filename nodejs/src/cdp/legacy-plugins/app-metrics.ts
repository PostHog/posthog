import { DateTime } from 'luxon'

import { KAFKA_APP_METRICS_2 } from '../../config/kafka-topics'
import { KafkaProducerWrapper, TopicMessage } from '../../kafka/producer'
import { TeamId, TimestampFormat } from '../../types'
import { logger } from '../../utils/logger'
import { castTimestampOrNow } from '../../utils/utils'

export interface AppMetricIdentifier {
    teamId: TeamId
    pluginConfigId: number
    jobId?: string
    // Keep in sync with posthog/queries/app_metrics/serializers.py
    category: 'processEvent' | 'onEvent' | 'scheduledTask' | 'webhook' | 'composeWebhook'
}

export interface AppMetric extends AppMetricIdentifier {
    successes?: number
    successesOnRetry?: number
    failures?: number
}

interface QueuedMetric {
    lastTimestamp: number

    successes: number
    successesOnRetry: number
    failures: number

    metric: AppMetricIdentifier
}

// app_source value for legacy-plugin rows in clickhouse_app_metrics2.
// Keep in sync with the value the frontend filters on.
const APP_SOURCE_LEGACY_PLUGIN = 'legacy_plugin'

interface AppMetric2Row {
    team_id: number
    timestamp: string
    app_source: string
    app_source_id: string
    instance_id: string
    metric_kind: 'success' | 'failure'
    metric_name: 'succeeded' | 'succeeded_on_retry' | 'failed'
    count: number
}

export class LegacyPluginAppMetrics {
    kafkaProducer: KafkaProducerWrapper
    queuedData: Record<string, QueuedMetric>

    flushFrequencyMs: number
    maxQueueSize: number

    lastFlushTime: number
    // For quick access to queueSize instead of using Object.keys(queuedData).length every time
    queueSize: number

    constructor(kafkaProducer: KafkaProducerWrapper, flushFrequencyMs: number, maxQueueSize: number) {
        this.queuedData = {}

        this.kafkaProducer = kafkaProducer
        this.flushFrequencyMs = flushFrequencyMs
        this.maxQueueSize = maxQueueSize
        this.lastFlushTime = Date.now()
        this.queueSize = 0
    }

    async queueMetric(metric: AppMetric, timestamp?: number): Promise<void> {
        // We don't want to immediately flush all the metrics every time as we can internally
        // aggregate them quite a bit and reduce the message count by a lot.
        // However, we also don't want to wait too long, nor have the queue grow too big resulting in
        // the flush taking a long time.
        const now = Date.now()

        timestamp = timestamp || now
        const key = this._key(metric)

        const { successes, successesOnRetry, failures, ...metricInfo } = metric

        if (!this.queuedData[key]) {
            this.queueSize += 1
            this.queuedData[key] = {
                successes: 0,
                successesOnRetry: 0,
                failures: 0,

                lastTimestamp: timestamp,
                metric: metricInfo,
            }
        }

        if (successes) {
            this.queuedData[key].successes += successes
        }
        if (successesOnRetry) {
            this.queuedData[key].successesOnRetry += successesOnRetry
        }
        if (failures) {
            this.queuedData[key].failures += failures
        }
        this.queuedData[key].lastTimestamp = timestamp

        if (now - this.lastFlushTime > this.flushFrequencyMs || this.queueSize > this.maxQueueSize) {
            await this.flush()
        }
    }

    async flush(): Promise<void> {
        logger.debug('🚽', `Flushing app metrics`)
        const startTime = Date.now()
        this.lastFlushTime = startTime
        if (Object.keys(this.queuedData).length === 0) {
            return
        }

        // TODO: We might be dropping some metrics here if someone wrote between queue assigment and queuedData={} assignment
        const queue = this.queuedData
        this.queueSize = 0
        this.queuedData = {}

        const messages: TopicMessage['messages'] = Object.values(queue).flatMap((value) => {
            const timestamp = castTimestampOrNow(DateTime.fromMillis(value.lastTimestamp), TimestampFormat.ClickHouse)
            const base = {
                team_id: value.metric.teamId,
                timestamp,
                app_source: APP_SOURCE_LEGACY_PLUGIN,
                app_source_id: String(value.metric.pluginConfigId),
                instance_id: value.metric.jobId ?? '',
            }

            const rows: AppMetric2Row[] = []
            if (value.successes > 0) {
                rows.push({ ...base, metric_kind: 'success', metric_name: 'succeeded', count: value.successes })
            }
            if (value.successesOnRetry > 0) {
                rows.push({
                    ...base,
                    metric_kind: 'success',
                    metric_name: 'succeeded_on_retry',
                    count: value.successesOnRetry,
                })
            }
            if (value.failures > 0) {
                rows.push({ ...base, metric_kind: 'failure', metric_name: 'failed', count: value.failures })
            }
            return rows.map((row) => ({ value: JSON.stringify(row) }))
        })

        if (messages.length === 0) {
            return
        }

        await this.kafkaProducer.queueMessages({
            topic: KAFKA_APP_METRICS_2,
            messages: messages,
        })
        logger.debug('🚽', `Finished flushing app metrics, took ${Date.now() - startTime}ms`)
    }

    _key(metric: AppMetric): string {
        return `${metric.teamId}.${metric.pluginConfigId}.${metric.category}.${metric.jobId}`
    }
}
