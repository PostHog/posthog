import { KafkaProducerWrapper } from '../../kafka/producer'
import { MetricTracker } from './metric-tracker'

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
    private trackers: Map<string, MetricTracker> = new Map()
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

    register(name: string, opts?: MetricConfig): MetricTracker {
        let tracker = this.trackers.get(name)
        if (!tracker) {
            tracker = new MetricTracker(
                name,
                opts?.topN ?? this.config.defaultTopN,
                opts?.maxKeys ?? this.config.maxKeys
            )
            this.trackers.set(name, tracker)
        }
        return tracker
    }

    async flush(): Promise<void> {
        const timestamp = new Date().toISOString()
        const messages: { value: string }[] = []

        for (const tracker of this.trackers.values()) {
            for (const { key, value } of tracker.flush()) {
                messages.push({
                    value: JSON.stringify({
                        timestamp,
                        metric: tracker.metricName,
                        key,
                        value,
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
            void this.flush()
        }, this.config.flushIntervalMs)
    }

    async stop(): Promise<void> {
        if (this.flushInterval) {
            clearInterval(this.flushInterval)
            this.flushInterval = null
        }
        await this.flush()
    }
}
