import pLimit from 'p-limit'

import { ChunkProcessingStep } from './base-chunk-pipeline'
import { ProcessingStep } from './steps'

// One chunk step, so instrumentation runs per chunk. A throw rejects the chunk but does not cancel the other values.
export function perElement<T, U, R extends string = never>(
    step: ProcessingStep<T, U, R>,
    options: { maxConcurrency?: number } = {}
): ChunkProcessingStep<T, U, R> {
    const limit = options.maxConcurrency !== undefined ? pLimit(options.maxConcurrency) : null
    const chunkStep: ChunkProcessingStep<T, U, R> = (values) =>
        Promise.all(values.map((value) => (limit ? limit(() => step(value)) : step(value))))
    Object.defineProperty(chunkStep, 'name', { value: step.name })
    return chunkStep
}
