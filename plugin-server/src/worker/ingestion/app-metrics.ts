import { Message } from 'kafkajs'

import { KAFKA_APP_METRICS } from '../../config/kafka-topics'
import { Hub, TeamId } from '../../types'

export interface AppMetricIdentifier {
    teamId: TeamId
    pluginConfigId: number
    jobId?: string
    // :TODO: Verify this list
    category: 'processEvent' | 'onEvent' | 'exportEvents'
}

export interface AppMetric extends AppMetricIdentifier {
    successes?: number
    successesOnRetry?: number
    failures?: number
}

interface QueuedMetric {
    successes: number
    successesOnRetry: number
    failures: number
    lastTimestamp: number
    queuedAt: number
    metric: AppMetricIdentifier
}

export class AppMetrics {
    hub: Hub
    queuedData: Record<string, QueuedMetric>

    flushFrequencyMs: number
    maxQueueSize: number

    timer: NodeJS.Timeout | null

    constructor(hub: Hub) {
        this.hub = hub
        this.queuedData = {}

        this.flushFrequencyMs = hub.APP_METRICS_FLUSH_FREQUENCY_MS
        this.maxQueueSize = hub.APP_METRICS_MAX_QUEUE_SIZE
        this.timer = null
    }

    async queueMetric(metric: AppMetric, timestamp?: number): Promise<void> {
        timestamp = timestamp || Date.now()
        const key = this._key(metric)

        if (!(await this.hub.organizationManager.hasAvailableFeature(metric.teamId, 'app_metrics'))) {
            return
        }

        const { successes, successesOnRetry, failures, ...metricInfo } = metric

        if (!this.queuedData[key]) {
            if (this.shouldFlushQueue()) {
                this.hub.promiseManager.trackPromise(this.flush())
                await this.hub.promiseManager.awaitPromisesIfNeeded()
            }

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

    async flush(): Promise<void> {
        if (Object.keys(this.queuedData).length === 0) {
            return
        }

        const queue = this.queuedData
        this.queuedData = {}

        const kafkaMessages: Message[] = Object.values(queue).map((value) => ({
            value: JSON.stringify({
                team_id: value.metric.teamId,
                plugin_config_id: value.metric.pluginConfigId,
                job_id: value.metric.jobId ?? null,
                category: value.metric.category,

                successes: value.successes,
                successes_on_retry: value.successesOnRetry,
                failures: value.failures,
            }),
        }))

        await this.hub.db.kafkaProducer.queueMessage({
            topic: KAFKA_APP_METRICS,
            messages: kafkaMessages,
        })
    }

    shouldFlushQueue(): boolean {
        return Object.keys(this.queuedData).length >= this.maxQueueSize
    }

    _key(metric: AppMetric): string {
        return `${metric.teamId}.${metric.pluginConfigId}.${metric.category}.${metric.jobId}`
    }
}
