import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { AverageMetricTracker, MaxMetricTracker, SummingMetricTracker, Tracker } from './metric-tracker'

export interface MetricConfig {
    topN?: number
    maxKeys?: number
}

export interface TopHogRequiredConfig {
    kafkaProducer: KafkaProducerWrapper
    topic: string
    pipeline: string
    lane: string
}

export interface TopHogOptionalConfig {
    flushIntervalMs: number
    defaultTopN: number
    maxKeys: number
    labels: Record<string, string>
}

const DEFAULT_FLUSH_INTERVAL_MS = 60_000
const DEFAULT_TOP_N = 10
const DEFAULT_MAX_KEYS = 1_000

export class TopHog {
    private summingTrackers: Map<string, SummingMetricTracker> = new Map()
    private maxTrackers: Map<string, MaxMetricTracker> = new Map()
    private averageTrackers: Map<string, AverageMetricTracker> = new Map()
    private flushInterval: ReturnType<typeof setInterval> | null = null
    private readonly config: TopHogRequiredConfig & TopHogOptionalConfig

    constructor(options: TopHogRequiredConfig & Partial<TopHogOptionalConfig>) {
        this.config = {
            flushIntervalMs: DEFAULT_FLUSH_INTERVAL_MS,
            defaultTopN: DEFAULT_TOP_N,
            maxKeys: DEFAULT_MAX_KEYS,
            labels: {},
            ...options,
        }
    }

    registerSum(name: string, opts?: MetricConfig): SummingMetricTracker {
        let tracker = this.summingTrackers.get(name)
        if (!tracker) {
            tracker = new SummingMetricTracker(
                name,
                opts?.topN ?? this.config.defaultTopN,
                opts?.maxKeys ?? this.config.maxKeys
            )
            this.summingTrackers.set(name, tracker)
        }
        return tracker
    }

    registerMax(name: string, opts?: MetricConfig): MaxMetricTracker {
        let tracker = this.maxTrackers.get(name)
        if (!tracker) {
            tracker = new MaxMetricTracker(
                name,
                opts?.topN ?? this.config.defaultTopN,
                opts?.maxKeys ?? this.config.maxKeys
            )
            this.maxTrackers.set(name, tracker)
        }
        return tracker
    }

    registerAverage(name: string, opts?: MetricConfig): AverageMetricTracker {
        let tracker = this.averageTrackers.get(name)
        if (!tracker) {
            tracker = new AverageMetricTracker(
                name,
                opts?.topN ?? this.config.defaultTopN,
                opts?.maxKeys ?? this.config.maxKeys
            )
            this.averageTrackers.set(name, tracker)
        }
        return tracker
    }

    async flush(): Promise<void> {
        const timestamp = new Date().toISOString()
        const messages: { value: string }[] = []

        for (const tracker of this.allTrackers()) {
            for (const { key, value, count } of tracker.flush()) {
                messages.push({
                    value: JSON.stringify({
                        timestamp,
                        metric: tracker.metricName,
                        type: tracker.type,
                        key,
                        value,
                        count,
                        pipeline: this.config.pipeline,
                        lane: this.config.lane,
                        labels: this.config.labels,
                    }),
                })
            }
        }

        if (messages.length > 0) {
            await this.config.kafkaProducer.queueMessages({
                topic: this.config.topic,
                messages,
            })
        }
    }

    start(): void {
        if (this.flushInterval) {
            return
        }
        this.flushInterval = setInterval(() => {
            void this.flush().catch((error) => {
                logger.error('TopHog flush failed', { error })
            })
        }, this.config.flushIntervalMs)
    }

    async stop(): Promise<void> {
        if (this.flushInterval) {
            clearInterval(this.flushInterval)
            this.flushInterval = null
        }
        await this.flush()
    }

    private *allTrackers(): Iterable<Tracker> {
        yield* this.summingTrackers.values()
        yield* this.maxTrackers.values()
        yield* this.averageTrackers.values()
    }
}
