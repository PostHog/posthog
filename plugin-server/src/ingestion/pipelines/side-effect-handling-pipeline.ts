import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'

export interface PromiseSchedulerInterface {
    schedule<T>(promise: Promise<T>): Promise<T>
}

export type SideEffectHandlingConfig = {
    await: boolean
}

/**
 * Pipeline that handles side effects by scheduling and optionally awaiting them, then clearing the side effects array
 */
export class SideEffectHandlingPipeline<T> implements BatchPipeline<T, T> {
    constructor(
        private subPipeline: BatchPipeline<T, T>,
        private promiseScheduler: PromiseSchedulerInterface,
        private config: SideEffectHandlingConfig = { await: false }
    ) {}

    feed(elements: BatchPipelineResultWithContext<T>): void {
        this.subPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<T> | null> {
        const results = await this.subPipeline.next()

        if (results === null) {
            return null
        }

        // Process all side effects
        const sideEffectPromises: Promise<unknown>[] = []

        for (const resultWithContext of results) {
            sideEffectPromises.push(...resultWithContext.context.sideEffects)
        }

        // Handle side effects based on config
        if (sideEffectPromises.length > 0) {
            if (this.config.await) {
                // When awaiting, handle promises directly without scheduler
                await Promise.allSettled(sideEffectPromises)
            } else {
                // When not awaiting, schedule the promises
                sideEffectPromises.forEach((promise) => this.promiseScheduler.schedule(promise))
            }
        }

        // Return results with cleared side effects
        return results.map((resultWithContext) => ({
            result: resultWithContext.result,
            context: {
                ...resultWithContext.context,
                sideEffects: [],
            },
        }))
    }
}
