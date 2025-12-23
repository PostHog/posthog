/**
 * MultithreadedShardedBatchPipeline
 *
 * A batch pipeline that routes events to worker threads based on a shard key.
 * Events with the same shard key are always routed to the same worker,
 * ensuring ordering guarantees within a group.
 *
 * Workers are long-lived and maintain their own internal pipelines for processing.
 */
import { randomUUID } from 'crypto'

import { BatchPipeline, BatchPipelineResultWithContext } from '../batch-pipeline.interface'
import { GroupingFunction } from '../concurrently-grouping-batch-pipeline'
import { PipelineContext, PipelineResultWithContext } from '../pipeline.interface'
import { PipelineResult, dlq, drop, isOkResult, ok, redirect } from '../results'
import { Serializable, WorkerResult, WorkerResultType } from './serializable'
import { WorkerConfig, WorkerManager } from './worker-manager'

export interface MultithreadedShardedConfig<TInput, TOutput = void> {
    /**
     * Number of worker threads to spawn.
     */
    numWorkers: number

    /**
     * Path to the worker entry point file.
     */
    workerPath: string

    /**
     * Configuration object passed to workers.
     */
    workerConfig: WorkerConfig

    /**
     * Convert pipeline input to a Serializable for transfer to worker.
     */
    serializer: (input: TInput) => Serializable

    /**
     * Optional: deserialize OK result value from worker.
     * If not provided, OK results will have undefined value.
     */
    deserializer?: (data: Uint8Array) => TOutput
}

export class MultithreadedShardedBatchPipeline<TInput, TIntermediate, TOutput, TKey, CInput, COutput>
    implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    private workerManager: WorkerManager
    private completedResults: PipelineResultWithContext<TOutput, COutput>[][] = []
    private activePromises: Promise<void>[] = []

    constructor(
        private groupingFn: GroupingFunction<TIntermediate, TKey>,
        private previousPipeline: BatchPipeline<TInput, TIntermediate, CInput, COutput>,
        private config: MultithreadedShardedConfig<TIntermediate, TOutput>
    ) {
        this.workerManager = new WorkerManager(config.numWorkers, config.workerPath, config.workerConfig)
    }

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
        // Pull from previous pipeline and dispatch to workers
        const previousResults = await this.previousPipeline.next()
        if (previousResults !== null) {
            this.dispatchToWorkers(previousResults)
        }

        // Return any completed results
        const completed = this.completedResults.shift()
        if (completed) {
            return completed
        }

        // If we have active work, wait for some to complete
        if (this.activePromises.length > 0) {
            await Promise.race(this.activePromises)
            return this.completedResults.shift() ?? null
        }

        return null
    }

    private dispatchToWorkers(results: PipelineResultWithContext<TIntermediate, COutput>[]): void {
        const nonOkResults: PipelineResultWithContext<TOutput, COutput>[] = []

        for (const item of results) {
            if (isOkResult(item.result)) {
                const value = item.result.value
                const groupKey = String(this.groupingFn(value))
                const correlationId = randomUUID()
                const serializable = this.config.serializer(value)
                const data = serializable.serialize()

                const promise = this.workerManager.sendEvent(groupKey, correlationId, data).then((workerResult) => {
                    const pipelineResult = this.mapWorkerResult(workerResult, item.context)
                    this.completedResults.push([pipelineResult])
                    // Remove this promise from active list
                    const idx = this.activePromises.indexOf(promise)
                    if (idx >= 0) {
                        void this.activePromises.splice(idx, 1)
                    }
                })

                this.activePromises.push(promise)
            } else {
                nonOkResults.push({
                    result: item.result as PipelineResult<TOutput>,
                    context: item.context,
                })
            }
        }

        if (nonOkResults.length > 0) {
            this.completedResults.push(nonOkResults)
        }
    }

    private mapWorkerResult(
        workerResult: WorkerResult,
        context: PipelineContext<COutput>
    ): PipelineResultWithContext<TOutput, COutput> {
        switch (workerResult.type) {
            case WorkerResultType.OK:
                return {
                    result: ok(
                        this.config.deserializer?.(workerResult.value) ?? (undefined as unknown as TOutput),
                        [], // sideEffects already executed in worker
                        workerResult.warnings
                    ),
                    context,
                }
            case WorkerResultType.DLQ:
                return {
                    result: dlq(workerResult.reason, workerResult.error, [], workerResult.warnings),
                    context,
                }
            case WorkerResultType.DROP:
                return {
                    result: drop(workerResult.reason, [], workerResult.warnings),
                    context,
                }
            case WorkerResultType.REDIRECT:
                return {
                    result: redirect(
                        workerResult.reason,
                        workerResult.topic,
                        workerResult.preserveKey,
                        workerResult.awaitAck,
                        [], // sideEffects already executed in worker
                        workerResult.warnings
                    ),
                    context,
                }
        }
    }

    /**
     * Wait for all pending work to complete and flush workers.
     */
    async flush(): Promise<void> {
        // Wait for all pending work
        await Promise.all(this.activePromises)
        await this.workerManager.flush()
    }

    /**
     * Gracefully shutdown all workers.
     */
    async shutdown(): Promise<void> {
        await this.flush()
        await this.workerManager.shutdown()
    }
}
