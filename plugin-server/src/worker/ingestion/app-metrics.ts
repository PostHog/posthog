import * as Sentry from '@sentry/node'
import { Message } from 'kafkajs'
import { DateTime } from 'luxon'
import { configure } from 'safe-stable-stringify'
import { serializeError } from 'serialize-error'

import { KAFKA_APP_METRICS } from '../../config/kafka-topics'
import { Hub, TeamId, TimestampFormat } from '../../types'
import { status } from '../../utils/status'
import { castTimestampOrNow, UUIDT } from '../../utils/utils'

export interface AppMetricIdentifier {
    teamId: TeamId
    pluginConfigId: number
    jobId?: string
    // Keep in sync with posthog/queries/app_metrics/serializers.py
    category: 'processEvent' | 'onEvent' | 'exportEvents'
}

export interface AppMetric extends AppMetricIdentifier {
    successes?: number
    successesOnRetry?: number
    failures?: number

    error_uuid?: string
    error_type?: string
    // Should be json-encoded!
    error_details?: string
}

export interface ErrorWithContext {
    error: Error
    context: {
        // Passed from processEvent/onEvent
        event?: any
        // Passed from exportEvents
        eventCount?: any
    }
}

interface QueuedMetric {
    successes: number
    successesOnRetry: number
    failures: number
    lastTimestamp: number
    queuedAt: number
    metric: AppMetricIdentifier
}

const MAX_STRING_LENGTH = 1000

const safeJSONStringify = configure({
    bigint: true,
    deterministic: false,
    maximumDepth: 3,
    maximumBreadth: 10,
})

export class AppMetrics {
    hub: Hub
    queuedData: Record<string, QueuedMetric>

    flushFrequencyMs: number

    timer: NodeJS.Timeout | null

    constructor(hub: Hub) {
        this.hub = hub
        this.queuedData = {}

        this.flushFrequencyMs = hub.APP_METRICS_FLUSH_FREQUENCY_MS
        this.timer = null
    }

    async isAvailable(metric: AppMetric, errorWithContext?: ErrorWithContext): Promise<boolean> {
        // :TRICKY: If postgres connection is down, we ignore this metric
        try {
            return await this.hub.organizationManager.hasAvailableFeature(metric.teamId, 'app_metrics')
        } catch (err) {
            status.warn(
                '⚠️',
                'Error querying whether app_metrics is available. Ignoring this metric',
                metric,
                errorWithContext,
                err
            )
            return false
        }
    }

    async queueMetric(metric: AppMetric, timestamp?: number): Promise<void> {
        timestamp = timestamp || Date.now()
        const key = this._key(metric)

        if (!(await this.isAvailable(metric))) {
            return
        }

        const { successes, successesOnRetry, failures, ...metricInfo } = metric

        if (!this.queuedData[key]) {
            this.queuedData[key] = {
                successes: 0,
                successesOnRetry: 0,
                failures: 0,
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

        if (this.timer === null) {
            this.timer = setTimeout(() => {
                this.hub.promiseManager.trackPromise(this.flush())
                this.timer = null
            }, this.flushFrequencyMs)
        }
    }

    async queueError(metric: AppMetric, errorWithContext: ErrorWithContext, timestamp?: number) {
        if (await this.isAvailable(metric, errorWithContext)) {
            await this.queueMetric(
                {
                    ...metric,
                    ...this._metricErrorParameters(errorWithContext),
                },
                timestamp
            )
        }
    }

    async flush(): Promise<void> {
        if (Object.keys(this.queuedData).length === 0) {
            return
        }

        const queue = this.queuedData
        this.queuedData = {}

        const kafkaMessages: Message[] = Object.values(queue).map((value) => ({
            value: JSON.stringify({
                timestamp: castTimestampOrNow(DateTime.fromMillis(value.lastTimestamp), TimestampFormat.ClickHouse),
                team_id: value.metric.teamId,
                plugin_config_id: value.metric.pluginConfigId,
                job_id: value.metric.jobId ?? null,
                category: value.metric.category,

                successes: value.successes,
                successes_on_retry: value.successesOnRetry,
                failures: value.failures,
            }),
        }))

        await this.hub.kafkaProducer.queueMessage({
            topic: KAFKA_APP_METRICS,
            messages: kafkaMessages,
        })
    }

    _metricErrorParameters(errorWithContext: ErrorWithContext): Partial<AppMetric> {
        try {
            const serializedError = serializeError(errorWithContext.error, { maxDepth: 2 })

            return {
                error_uuid: new UUIDT().toString(),
                error_type: serializedError.name,
                error_details: safeJSONStringify(
                    {
                        error: serializedError,
                        context: errorWithContext.context,
                    },
                    this._serializeJSONValue
                ),
            }
        } catch (err) {
            Sentry.captureException(err)
            status.warn('⚠️', 'Failed to serialize error for app metrics. Not reporting this error.', err)
            return {}
        }
    }

    _key(metric: AppMetric): string {
        return `${metric.teamId}.${metric.pluginConfigId}.${metric.category}.${metric.jobId}`
    }

    _serializeJSONValue(key: string, value: any): string {
        if (typeof value === 'string' && value.length > MAX_STRING_LENGTH) {
            return value.slice(MAX_STRING_LENGTH)
        }
        return value
    }
}
