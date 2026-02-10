import { KafkaProducerWrapper } from '../../kafka/producer'

export interface TopHogOptions {
    kafkaProducer: KafkaProducerWrapper
    topic: string
    pipeline: string
    lane: string
    flushIntervalMs?: number
    defaultTopN?: number
    maxKeys?: number
    labels?: Record<string, string>
}

export enum TopHogMetricType {
    Count,
    Time,
}

export interface TopHogMetric<T> {
    key: (input: T) => string
    type: TopHogMetricType
    name: string
    maxKeys?: number
}

export type TopHogPipeOptions<T> = TopHogMetric<T>[]

interface TopHogConfig {
    kafkaProducer: KafkaProducerWrapper
    topic: string
    pipeline: string
    lane: string
    flushIntervalMs: number
    defaultTopN: number
    maxKeys?: number
    labels: Record<string, string>
}

export class TopHog {
    private counters: Map<string, Map<string, number>> = new Map()
    private flushInterval: ReturnType<typeof setInterval> | null = null
    private readonly config: TopHogConfig

    constructor(options: TopHogOptions) {
        this.config = {
            ...options,
            flushIntervalMs: options.flushIntervalMs ?? 60_000,
            defaultTopN: options.defaultTopN ?? 10,
            maxKeys: options.maxKeys,
            labels: options.labels ?? {},
        }
    }

    increment(metric: string, key: string, value: number = 1, maxKeys?: number): void {
        let metricCounters = this.counters.get(metric)
        if (!metricCounters) {
            metricCounters = new Map()
            this.counters.set(metric, metricCounters)
        }

        const existing = metricCounters.get(key)
        if (existing === undefined) {
            const limit = maxKeys ?? this.config.maxKeys
            if (limit && metricCounters.size >= limit) {
                // Evict LRU (first key in insertion order)
                const lruKey = metricCounters.keys().next().value!
                metricCounters.delete(lruKey)
            }
        } else {
            // Move to end of insertion order (mark as most recently used)
            metricCounters.delete(key)
        }

        metricCounters.set(key, (existing ?? 0) + value)
    }

    async flush(): Promise<void> {
        const timestamp = new Date().toISOString()
        const messages: { value: string }[] = []

        for (const [metric, metricCounters] of this.counters.entries()) {
            if (metricCounters.size === 0) {
                continue
            }

            const topEntries = Array.from(metricCounters.entries())
                .sort(([, a], [, b]) => b - a)
                .slice(0, this.config.defaultTopN)

            for (const [key, value] of topEntries) {
                messages.push({
                    value: JSON.stringify({
                        timestamp,
                        metric,
                        key,
                        value,
                        pipeline: this.config.pipeline,
                        lane: this.config.lane,
                        labels: this.config.labels,
                    }),
                })
            }
        }

        this.counters.clear()

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
