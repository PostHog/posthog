import { Message } from 'node-rdkafka'

import { IngestionWarning } from '~/ingestion/common/ingestion-warnings'

import { PipelineResult, PipelineResultOk } from './results'

export type PipelineWarning = IngestionWarning

/**
 * Loggable origin metadata for a pipeline item or a chunk of items, e.g.
 * Kafka topic/partition/offset. Emitted in crash logs when a step throws,
 * right before the exception propagates and takes the process down.
 */
export type PipelineDebugContext = Record<string, unknown>

/**
 * The debug context type a pipeline context carries under its `debugContext`
 * key. A context that declares no key yields `unknown` — "the debug contexts
 * are unknown to you" — which no typed aggregator is assignable against, so
 * attaching one to such a composition fails to compile.
 */
export type DebugContextOf<C> = C extends { debugContext?: infer D }
    ? [D] extends [never]
        ? unknown
        : Exclude<D, undefined>
    : unknown

/**
 * Cross-cutting configuration handed to a pipeline composition at build time
 * and stored by the pipelines that need it at runtime. Builders forward it
 * through the whole composition, so extending it with a new field reaches
 * every pipeline without touching the builder plumbing again.
 *
 * `D` is the debug context type the composition's contexts carry; entry
 * points derive it from the context type via {@link DebugContextOf}, so an
 * aggregator only attaches when the context declares a `debugContext` key of
 * the matching shape.
 */
export interface PipelineBuilderContext<D = unknown> {
    /**
     * Folds a crashed chunk's debug contexts into one readable summary (a
     * chunk step failure can't be attributed to a single item). Single-item
     * failures log the item's `debugContext` directly and need no
     * configuration. Only invoked on the crash path.
     */
    aggregateDebugContexts?: (debugContexts: D[]) => PipelineDebugContext
}

/**
 * Processing context that carries message through pipeline transformations
 */
export type PipelineContext<C = { message: Message }> = C & {
    lastStep?: string
    /**
     * Loggable origin of this item, set once at the pipeline boundary (feed
     * site or fan-out) in the shape the composition's aggregator expects.
     * `C` narrows the type via its own `debugContext` declaration.
     */
    debugContext?: unknown
    /**
     * Work that outlives the step, drained with the batch. A side effect must
     * not reject. What a rejection does depends on the host: consumer-v2
     * latches a fatal and holds the offset, consumer-v1 stores the offset from
     * a `.finally` and then stops the process on the unhandled rejection,
     * ingestion-api-server stops the pod, and the gRPC driver fails every open
     * stream. Settle the promise inside the step and record the failure there.
     */
    sideEffects: Promise<unknown>[]
    warnings: PipelineWarning[]
}

/**
 * Result with context wrapper that carries both the pipeline result and processing context.
 *
 * `R` is the union of redirect output names this result can carry.
 */
export interface PipelineResultWithContext<T, C = { message: Message }, R extends string = never> {
    result: PipelineResult<T, R>
    context: PipelineContext<C>
}

/** An OK result with context — the only type that can be fed into a pipeline. */
export interface OkResultWithContext<T, C = { message: Message }> {
    result: PipelineResultOk<T>
    context: PipelineContext<C>
}

/**
 * Interface for single-item processors.
 *
 * @typeParam R - Union of redirect output names that can flow through this pipeline.
 *   Defaults to `never` (no redirects). Widens as steps that redirect are composed in.
 */
export interface Pipeline<TInput, TOutput, C = { message: Message }, R extends string = never> {
    process(input: OkResultWithContext<TInput, C>): Promise<PipelineResultWithContext<TOutput, C, R>>
}
