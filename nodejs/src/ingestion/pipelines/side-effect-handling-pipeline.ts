import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import { sideEffectResultCounter } from './metrics'

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
    implements BatchPipeline<TInput, TOutput, CInput, COutput, R>
{
    constructor(
        private subPipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>,
        private promiseScheduler: PromiseSchedulerInterface,
        private config: SideEffectHandlingConfig = { await: false }
    ) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, R> | null> {
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
