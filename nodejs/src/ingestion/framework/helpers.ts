import { Message } from 'node-rdkafka'

import { ChunkPipelineBuilder, newChunkPipelineBuilder } from './builders'
import { ChunkPipelineUnwrapper } from './chunk-pipeline-unwrapper'
import { ChunkPipeline } from './chunk-pipeline.interface'
import {
    DebugContextOf,
    OkResultWithContext,
    PipelineBuilderContext,
    PipelineDebugContext,
    PipelineWarning,
} from './pipeline.interface'
import { PipelineResult, ok } from './results'
import { StartPipeline } from './start-pipeline'

/** Loggable origin of a Kafka message, stored on the context at feed time. */
export type KafkaDebugContext = { topic?: string; partition: number; offset: number }

export type DefaultContext = { message: Message; debugContext?: KafkaDebugContext }

export function createKafkaDebugContext(message: Message): KafkaDebugContext {
    return { topic: message.topic, partition: message.partition, offset: message.offset }
}

/**
 * Compact a list of offsets into a human-readable ranges string, e.g.
 * [1, 2, 3, 7, 10, 9] -> "1-3,7,9-10". Duplicates are collapsed.
 */
export function compactOffsetRanges(offsets: number[]): string {
    const sorted = [...new Set(offsets)].sort((a, b) => a - b)
    const ranges: string[] = []
    let start: number | null = null
    let end = 0
    for (const offset of sorted) {
        if (start === null) {
            start = end = offset
        } else if (offset === end + 1) {
            end = offset
        } else {
            ranges.push(start === end ? `${start}` : `${start}-${end}`)
            start = end = offset
        }
    }
    if (start !== null) {
        ranges.push(start === end ? `${start}` : `${start}-${end}`)
    }
    return ranges.join(',')
}

/**
 * Folds a crashed chunk's Kafka debug contexts into one compact summary: one
 * offsets-ranges string per topic-partition, so the log stays a single
 * readable line instead of one object per message. Duplicate offsets (e.g.
 * fan-out sub-elements sharing a parent) collapse in the range compaction.
 */
export function aggregateKafkaDebugContexts(debugContexts: KafkaDebugContext[]): PipelineDebugContext {
    const offsetsByPartition = new Map<string, number[]>()
    for (const debugContext of debugContexts) {
        const key = `${debugContext.topic}[${debugContext.partition}]`
        const offsets = offsetsByPartition.get(key)
        if (offsets) {
            offsets.push(debugContext.offset)
        } else {
            offsetsByPartition.set(key, [debugContext.offset])
        }
    }
    return {
        count: debugContexts.length,
        offsets: Array.from(offsetsByPartition, ([key, offsets]) => `${key}:${compactOffsetRanges(offsets)}`),
    }
}

/**
 * Helper function to create a new processing pipeline for single items
 */
export function createNewPipeline<T = { message: Message }, C = DefaultContext>(): StartPipeline<T, C> {
    return new StartPipeline<T, C>()
}

/**
 * Helper function to create a new chunk processing pipeline starting with a root pipeline
 */
export function createNewChunkPipeline<T = { message: Message }, C = DefaultContext>(
    builderContext?: PipelineBuilderContext<DebugContextOf<C>>
): ChunkPipelineBuilder<T, T, C, C, never, DebugContextOf<C>> {
    return newChunkPipelineBuilder<T, C>(builderContext)
}

/**
 * Helper function to create a batch of ResultWithContext from Kafka messages or objects with a message property
 */
export function createBatch<T extends DefaultContext>(items: T[]) {
    return items.map((item) =>
        createOkContext(item, { message: item.message, debugContext: createKafkaDebugContext(item.message) })
    )
}

/**
 * Base context properties that are always present in pipeline context
 */
export type BasePipelineContext = {
    lastStep?: string
    debugContext?: unknown
    sideEffects?: Promise<unknown>[]
    warnings?: PipelineWarning[]
}

/**
 * Result type for createContext that represents the actual shape of the returned context
 */
export type CreateContextResult<T, PartialContext, R extends string = never> = {
    result: PipelineResult<T, R>
    context: {
        lastStep: string | undefined
        sideEffects: Promise<unknown>[]
        warnings: PipelineWarning[]
    } & PartialContext
}

/**
 * Helper function to create a PipelineResultWithContext from a result and partial context
 */
export function createContext<
    T,
    PartialContext extends Record<string, unknown> = Record<string, never>,
    R extends string = never,
>(
    result: PipelineResult<T, R>,
    ...args: PartialContext extends Record<string, never>
        ? [partialContext?: PartialContext & BasePipelineContext]
        : [partialContext: PartialContext & BasePipelineContext]
): CreateContextResult<T, PartialContext, R> {
    const partialContext = args[0] || ({} as PartialContext & BasePipelineContext)
    const { lastStep, sideEffects, warnings, ...rest } = partialContext
    return {
        result,
        context: {
            lastStep: lastStep,
            sideEffects: sideEffects || [],
            warnings: warnings || [],
            ...rest,
        } as CreateContextResult<T, PartialContext>['context'],
    }
}

/**
 * Create an OK result with context, suitable for feeding into a pipeline via feed().
 */
export function createOkContext<T, C extends Record<string, unknown> = Record<string, never>>(
    value: T,
    partialContext: C & BasePipelineContext
): OkResultWithContext<T, C> {
    return {
        result: ok(value),
        context: {
            lastStep: undefined,
            sideEffects: [],
            warnings: [],
            ...partialContext,
        },
    }
}

/**
 * Helper function to create a chunk pipeline unwrapper
 */
export function createUnwrapper<TInput, TOutput, C, R extends string = never>(
    chunkPipeline: ChunkPipeline<TInput, TOutput, C, C, R>
): ChunkPipelineUnwrapper<TInput, TOutput, C, R> {
    return new ChunkPipelineUnwrapper(chunkPipeline)
}
