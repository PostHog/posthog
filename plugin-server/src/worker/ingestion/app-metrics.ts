import { DateTime } from 'luxon'
import { configure } from 'safe-stable-stringify'

import { KAFKA_APP_METRICS } from '../../config/kafka-topics'
import { KafkaProducerWrapper, TopicMessage } from '../../kafka/producer'
import { TeamId, TimestampFormat } from '../../types'
import { cleanErrorStackTrace } from '../../utils/db/error'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { UUIDT, castTimestampOrNow } from '../../utils/utils'

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

    errorUuid?: string
    errorType?: string
    // Should be json-encoded!
    errorDetails?: string
}

export interface ErrorWithContext {
    error: Error | string
    // Passed from processEvent/onEvent
    event?: any
    // Passed from exportEvents
    eventCount?: any
}

interface QueuedMetric {
    lastTimestamp: number
    queuedAt: number

    successes: number
    successesOnRetry: number
    failures: number

    errorUuid?: string
    errorType?: string
    // Should be json-encoded!
    errorDetails?: string

    metric: AppMetricIdentifier
}

/** An aggregated AppMetric, as written to/read from a ClickHouse row. */
export interface RawAppMetric {
    timestamp: string
    team_id: number
    plugin_config_id: number
    job_id?: string
    category: string
    successes: number
    successes_on_retry: number
    failures: number
    error_uuid?: string
    error_type?: string
    error_details?: string
}

const MAX_STRING_LENGTH = 1000

const safeJSONStringify = configure({
    deterministic: false,
    maximumDepth: 4,
    maximumBreadth: 40,
})

export class AppMetrics {
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

        const { successes, successesOnRetry, failures, errorUuid, errorType, errorDetails, ...metricInfo } = metric

        if (!this.queuedData[key]) {
            this.queueSize += 1
            this.queuedData[key] = {
                successes: 0,
                successesOnRetry: 0,
                failures: 0,
                errorUuid,
                errorType,
                errorDetails,

                lastTimestamp: timestamp,
                queuedAt: timestamp,
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

    async queueError(metric: AppMetric, errorWithContext: ErrorWithContext, timestamp?: number) {
        await this.queueMetric(
            {
                ...metric,
                ...this._metricErrorParameters(errorWithContext),
            },
            timestamp
        )
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

        const messages: TopicMessage['messages'] = Object.values(queue).map((value) => ({
            value: JSON.stringify({
                timestamp: castTimestampOrNow(DateTime.fromMillis(value.lastTimestamp), TimestampFormat.ClickHouse),
                team_id: value.metric.teamId,
                plugin_config_id: value.metric.pluginConfigId,
                job_id: value.metric.jobId ?? null,
                category: value.metric.category,

                successes: value.successes,
                successes_on_retry: value.successesOnRetry,
                failures: value.failures,

                error_uuid: value.errorUuid,
                error_type: value.errorType,
                error_details: value.errorDetails,
            } as RawAppMetric),
        }))

        await this.kafkaProducer.queueMessages({
            topic: KAFKA_APP_METRICS,
            messages: messages,
        })
        logger.debug('🚽', `Finished flushing app metrics, took ${Date.now() - startTime}ms`)
    }

    _metricErrorParameters(errorWithContext: ErrorWithContext): Partial<AppMetric> {
        try {
            const { error, ...context } = errorWithContext

            let serializedError: Record<string, string | undefined>
            if (typeof error === 'string') {
                serializedError = { name: error }
            } else {
                serializedError = {
                    name: error.name,
                    message: error.message,
                    stack: cleanErrorStackTrace(error.stack),
                }
            }

            return {
                errorUuid: new UUIDT().toString(),
                errorType: serializedError.name,
                errorDetails: safeJSONStringify(
                    {
                        error: serializedError,
                        ...context,
                    },
                    this._serializeJSONValue
                ),
            }
        } catch (err) {
            captureException(err)
            logger.warn('⚠️', 'Failed to serialize error for app metrics. Not reporting this error.', err)
            return {}
        }
    }

    _key(metric: AppMetric): string {
        return `${metric.teamId}.${metric.pluginConfigId}.${metric.category}.${metric.jobId}.${metric.errorUuid}`
    }

    _serializeJSONValue(key: string, value: any): string {
        if (typeof value === 'string' && value.length > MAX_STRING_LENGTH) {
            return value.slice(0, MAX_STRING_LENGTH)
        }
        return value
    }
}
