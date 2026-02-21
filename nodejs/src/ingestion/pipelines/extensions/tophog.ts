import { MetricTracker } from '../../tophog/metric-tracker'
import { MetricConfig } from '../../tophog/tophog'
import type { ProcessingStep } from '../steps'
import { wrapStep } from './helpers'

export interface TopHogRegistry {
    register(name: string, opts?: MetricConfig): MetricTracker
}

export interface TopHogMetric<T> {
    start(input: T): () => void
}

export type TopHogMetricFactory<T> = (registry: TopHogRegistry) => TopHogMetric<T>

export function counter<T>(
    name: string,
    key: (input: T) => Record<string, string>,
    opts?: MetricConfig
): TopHogMetricFactory<T> {
    return (registry) => new CounterMetric(registry.register(name, opts), key)
}

export function timing<T>(
    name: string,
    key: (input: T) => Record<string, string>,
    opts?: MetricConfig
): TopHogMetricFactory<T> {
    return (registry) => new TimingMetric(registry.register(name, opts), key)
}

export type TopHogWrapper = <T, U>(
    step: ProcessingStep<T, U>,
    factories: TopHogMetricFactory<T>[]
) => ProcessingStep<T, U>

export function createTopHogWrapper(tracker: TopHogRegistry): TopHogWrapper {
    return <T, U>(step: ProcessingStep<T, U>, factories: TopHogMetricFactory<T>[]): ProcessingStep<T, U> => {
        if (!factories.length) {
            return step
        }
        const metrics = factories.map((f) => f(tracker))
        return wrapStep(step, async (input, s) => {
            const ends = metrics.map((m) => m.start(input))
            const result = await s(input)
            ends.forEach((end) => end())
            return result
        })
    }
}

class CounterMetric<T> implements TopHogMetric<T> {
    constructor(
        private readonly tracker: { record(key: Record<string, string>, value: number): void },
        private readonly key: (input: T) => Record<string, string>
    ) {}

    start(input: T): () => void {
        const k = this.key(input)
        return () => {
            this.tracker.record(k, 1)
        }
    }
}

class TimingMetric<T> implements TopHogMetric<T> {
    constructor(
        private readonly tracker: { record(key: Record<string, string>, value: number): void },
        private readonly key: (input: T) => Record<string, string>
    ) {}

    start(input: T): () => void {
        const k = this.key(input)
        const startTime = performance.now()
        return () => {
            this.tracker.record(k, performance.now() - startTime)
        }
    }
}
