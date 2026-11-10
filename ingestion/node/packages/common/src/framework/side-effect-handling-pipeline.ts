import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { sideEffectResultCounter } from './metrics'
import { Pipeline, PipelineResultWithContext } from './pipeline.interface'

export interface PromiseSchedulerInterface {
    schedule<T>(promise: Promise<T>): Promise<T>
    schedule<T extends readonly [Promise<unknown>, Promise<unknown>, ...Promise<unknown>[]]>(
        ...promises: T
    ): Promise<{ -readonly [K in keyof T]: Awaited<T[K]> }>
}

export type SideEffectHandlingConfig = {
    await: boolean
}

/**
 * Pipeline that handles side effects by scheduling and optionally awaiting them, then clearing the side effects array
 */
export class SideEffectHandlingPipeline<TInput, TOutput, CInput, COutput = CInput, R extends string = never>
    implements ChunkPipeline<TInput, TOutput, CInput, COutput, R>
{
    constructor(
        private subPipeline: ChunkPipeline<TInput, TOutput, CInput, COutput, R>,
        private promiseScheduler: PromiseSchedulerInterface,
        private config: SideEffectHandlingConfig = { await: false }
    ) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, R> | null> {
        const results = await this.subPipeline.next()
        if (results === null) {
            return null
        }

        const sideEffectPromises: Promise<unknown>[] = []
        for (const resultWithContext of results) {
            sideEffectPromises.push(...resultWithContext.context.sideEffects)
        }

        if (sideEffectPromises.length > 0) {
            if (this.config.await) {
                const settledResults = await Promise.allSettled(sideEffectPromises)
                settledResults.forEach((result) => {
                    if (result.status === 'fulfilled') {
                        sideEffectResultCounter.labels('ok').inc()
                    } else {
                        sideEffectResultCounter.labels('error').inc()
                    }
                })
            } else {
                sideEffectPromises.forEach((promise) => void this.promiseScheduler.schedule(promise))
            }
        }

        return results.map((resultWithContext) => ({
            result: resultWithContext.result,
            context: {
                ...resultWithContext.context,
                sideEffects: [],
            },
        }))
    }
}

/**
 * Single-item counterpart of {@link SideEffectHandlingPipeline}: wraps a
 * {@link Pipeline} and schedules (or awaits) the side effects its results
 * carry, then clears them. Lets simple pipelines — like the batching
 * before/afterBatch hooks — handle their own side effects instead of leaving
 * them for the driver to drain.
 */
export class SideEffectHandlingProcessor<TInput, TOutput, C, R extends string = never>
    implements Pipeline<TInput, TOutput, C, R>
{
    constructor(
        private subPipeline: Pipeline<TInput, TOutput, C, R>,
        private promiseScheduler: PromiseSchedulerInterface,
        private config: SideEffectHandlingConfig = { await: false }
    ) {}

    async process(input: OkResultWithContext<TInput, C>): Promise<PipelineResultWithContext<TOutput, C, R>> {
        const resultWithContext = await this.subPipeline.process(input)
        const sideEffects = resultWithContext.context.sideEffects

        if (sideEffects.length > 0) {
            if (this.config.await) {
                const settledResults = await Promise.allSettled(sideEffects)
                settledResults.forEach((result) => {
                    sideEffectResultCounter.labels(result.status === 'fulfilled' ? 'ok' : 'error').inc()
                })
            } else {
                sideEffects.forEach((promise) => void this.promiseScheduler.schedule(promise))
            }
        }

        return {
            result: resultWithContext.result,
            context: {
                ...resultWithContext.context,
                sideEffects: [],
            },
        }
    }
}
