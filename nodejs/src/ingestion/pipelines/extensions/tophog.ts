import { MetricConfig } from '../../tophog/tophog'
import { PipelineResult, isOkResult } from '../results'
import type { ProcessingStep } from '../steps'
import { wrapStep } from './helpers'

type Recorder = { record(key: Record<string, string>, value: number): void }

export interface TopHogRegistry {
    registerSum(name: string, opts?: MetricConfig): Recorder
    registerMax(name: string, opts?: MetricConfig): Recorder
    registerAverage(name: string, opts?: MetricConfig): Recorder
}

export interface TopHogMetric<TInput, TOutput> {
    start(input: TInput): (result: PipelineResult<TOutput>) => void
}

export type TopHogMetricFactory<TInput, TOutput> = (registry: TopHogRegistry) => TopHogMetric<TInput, TOutput>

export function count<TInput, TOutput>(
    name: string,
    key: (input: TInput) => Record<string, string>,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new InputMetric(registry.registerSum(name, opts), key, () => 1)
}

export function countResult<TInput, TOutput>(
    name: string,
    key: (result: PipelineResult<TOutput>, input: TInput) => Record<string, string>,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new CompletionMetric(registry.registerSum(name, opts), key, () => 1)
}

export function countOk<TInput, TOutput>(
    name: string,
    key: (output: TOutput, input: TInput) => Record<string, string>,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new OutputMetric(registry.registerSum(name, opts), key, () => 1)
}

export function sum<TInput, TOutput>(
    name: string,
    key: (input: TInput) => Record<string, string>,
    value: (input: TInput) => number,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new InputMetric(registry.registerSum(name, opts), key, value)
}

export function sumResult<TInput, TOutput>(
    name: string,
    key: (result: PipelineResult<TOutput>, input: TInput) => Record<string, string>,
    value: (result: PipelineResult<TOutput>, input: TInput) => number,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new CompletionMetric(registry.registerSum(name, opts), key, value)
}

export function sumOk<TInput, TOutput>(
    name: string,
    key: (output: TOutput, input: TInput) => Record<string, string>,
    value: (output: TOutput, input: TInput) => number,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new OutputMetric(registry.registerSum(name, opts), key, value)
}

export function max<TInput, TOutput>(
    name: string,
    key: (input: TInput) => Record<string, string>,
    value: (input: TInput) => number,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new InputMetric(registry.registerMax(name, opts), key, value)
}

export function maxResult<TInput, TOutput>(
    name: string,
    key: (result: PipelineResult<TOutput>, input: TInput) => Record<string, string>,
    value: (result: PipelineResult<TOutput>, input: TInput) => number,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new CompletionMetric(registry.registerMax(name, opts), key, value)
}

export function maxOk<TInput, TOutput>(
    name: string,
    key: (output: TOutput, input: TInput) => Record<string, string>,
    value: (output: TOutput, input: TInput) => number,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new OutputMetric(registry.registerMax(name, opts), key, value)
}

export function average<TInput, TOutput>(
    name: string,
    key: (input: TInput) => Record<string, string>,
    value: (input: TInput) => number,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new InputMetric(registry.registerAverage(name, opts), key, value)
}

export function averageResult<TInput, TOutput>(
    name: string,
    key: (result: PipelineResult<TOutput>, input: TInput) => Record<string, string>,
    value: (result: PipelineResult<TOutput>, input: TInput) => number,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new CompletionMetric(registry.registerAverage(name, opts), key, value)
}

export function averageOk<TInput, TOutput>(
    name: string,
    key: (output: TOutput, input: TInput) => Record<string, string>,
    value: (output: TOutput, input: TInput) => number,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new OutputMetric(registry.registerAverage(name, opts), key, value)
}

export function timer<TInput, TOutput>(
    name: string,
    key: (input: TInput) => Record<string, string>,
    opts?: MetricConfig
): TopHogMetricFactory<TInput, TOutput> {
    return (registry) => new TimingMetric(registry.registerSum(name, opts), key)
}

export type TopHogWrapper = <TInput, TOutput>(
    step: ProcessingStep<TInput, TOutput>,
    factories: TopHogMetricFactory<TInput, TOutput>[]
) => ProcessingStep<TInput, TOutput>

export function createTopHogWrapper(tracker: TopHogRegistry): TopHogWrapper {
    return <TInput, TOutput>(
        step: ProcessingStep<TInput, TOutput>,
        factories: TopHogMetricFactory<TInput, TOutput>[]
    ): ProcessingStep<TInput, TOutput> => {
        if (!factories.length) {
            return step
        }
        const metrics = factories.map((f) => f(tracker))
        return wrapStep(step, async (input, s) => {
            const ends = metrics.map((m) => m.start(input))
            const result = await s(input)
            ends.forEach((end) => end(result))
            return result
        })
    }
}

class InputMetric<TInput, TOutput> implements TopHogMetric<TInput, TOutput> {
    constructor(
        private readonly tracker: Recorder,
        private readonly key: (input: TInput) => Record<string, string>,
        private readonly value: (input: TInput) => number
    ) {}

    start(input: TInput): (result: PipelineResult<TOutput>) => void {
        this.tracker.record(this.key(input), this.value(input))
        return noop
    }
}

class CompletionMetric<TInput, TOutput> implements TopHogMetric<TInput, TOutput> {
    constructor(
        private readonly tracker: Recorder,
        private readonly key: (result: PipelineResult<TOutput>, input: TInput) => Record<string, string>,
        private readonly value: (result: PipelineResult<TOutput>, input: TInput) => number
    ) {}

    start(input: TInput): (result: PipelineResult<TOutput>) => void {
        return (result) => {
            this.tracker.record(this.key(result, input), this.value(result, input))
        }
    }
}

class OutputMetric<TInput, TOutput> implements TopHogMetric<TInput, TOutput> {
    constructor(
        private readonly tracker: Recorder,
        private readonly key: (output: TOutput, input: TInput) => Record<string, string>,
        private readonly value: (output: TOutput, input: TInput) => number
    ) {}

    start(input: TInput): (result: PipelineResult<TOutput>) => void {
        return (result) => {
            if (isOkResult(result)) {
                this.tracker.record(this.key(result.value, input), this.value(result.value, input))
            }
        }
    }
}

class TimingMetric<TInput, TOutput> implements TopHogMetric<TInput, TOutput> {
    constructor(
        private readonly tracker: Recorder,
        private readonly key: (input: TInput) => Record<string, string>
    ) {}

    start(input: TInput): (result: PipelineResult<TOutput>) => void {
        const k = this.key(input)
        const startTime = performance.now()
        return () => {
            this.tracker.record(k, performance.now() - startTime)
        }
    }
}

function noop(): void {}
