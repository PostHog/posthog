import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { sideEffectResultCounter } from './metrics'

export interface PromiseSchedulerInterface {
    schedule<T>(promise: Promise<T>): Promise<T>
}

export type SideEffectHandlingConfig = {
    await: boolean
}

/**
 * Pipeline that handles side effects by scheduling and optionally awaiting them, then clearing the side effects array
 */
export class SideEffectHandlingPipeline<TInput, TOutput, CInput, COutput = CInput>
    implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    constructor(
        private subPipeline: BatchPipeline<TInput, TOutput, CInput, COutput>,
        private promiseScheduler: PromiseSchedulerInterface,
        private config: SideEffectHandlingConfig = { await: false }
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
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
