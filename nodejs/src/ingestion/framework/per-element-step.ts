import pLimit from 'p-limit'

import { ChunkProcessingStep } from './base-chunk-pipeline'
import { ProcessingStep } from './steps'

/**
 * Runs a single-item step over every value of a chunk, as one chunk step. The framework
 * instruments a chunk step once per chunk, and an element step once per element: where the step is
 * cheap, such as a header parse or a passthrough produce, that per-element cost dominates.
 *
 * Results keep input order. With `maxConcurrency`, values start in input order (p-limit is FIFO),
 * like `concurrently`. A step that throws rejects the chunk; the other values still run to the end,
 * because nothing cancels them.
 */
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
