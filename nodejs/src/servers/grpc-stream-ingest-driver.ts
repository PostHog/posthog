import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { CompletedSubBatch, MessageCoordinates, StreamIngestDriver, SubBatchBudget } from '~/ingestion/api/grpc-server'
import { deserializeKafkaMessage } from '~/ingestion/api/kafka-message-converter'
import { SerializedKafkaMessage } from '~/ingestion/api/types'
import { BatchBudget, budgetDeadline } from '~/ingestion/framework/batch-budget'
import { BatchResult, FeedResult } from '~/ingestion/framework/batching-pipeline'
import { ChunkPipelineResultWithContext, OkResultWithContext } from '~/ingestion/framework/chunk-pipeline.interface'
import { KafkaDebugContext, createKafkaDebugContext, createOkContext } from '~/ingestion/framework/helpers'
import { isTimeoutResult } from '~/ingestion/framework/results'

/** Batch context fed with each gRPC sub-batch so its completion routes back to the right stream. */
export type GrpcBatchContext = { grpcStreamId: number; grpcSeq: number }

export type GrpcIngestInput = { message: Message }
export type GrpcIngestContext = { message: Message; debugContext: KafkaDebugContext }

/**
 * Structural, so the driver accepts any pipeline that takes a `GrpcBatchContext` as its feed context.
 * `feed` is a property, not a method, so TypeScript checks its parameters strictly.
 */
export interface GrpcIngestPipeline {
    feed: (
        elements: OkResultWithContext<GrpcIngestInput, GrpcIngestContext>[],
        batchContext: GrpcBatchContext,
        budget: BatchBudget
    ) => Promise<FeedResult>
    next: () => Promise<BatchResult<
        ChunkPipelineResultWithContext<unknown, { message: Message }, string>,
        GrpcBatchContext
    > | null>
}

/**
 * Pipeline mechanics for the gRPC stream server. The `settled` promise on
 * each completed batch is the ack barrier: it mirrors the HTTP handler's
 * contract (side effects plus the promise scheduler) but stays a promise
 * so the server can settle many batches concurrently.
 */
export class GrpcStreamIngestDriver implements StreamIngestDriver {
    constructor(
        private pipeline: GrpcIngestPipeline,
        private promiseScheduler: PromiseScheduler
    ) {}

    feed(
        streamId: number,
        seq: number,
        messages: SerializedKafkaMessage[],
        budget: SubBatchBudget
    ): Promise<FeedResult> {
        const batch = messages.map((serialized) => {
            const message = deserializeKafkaMessage(serialized)
            return createOkContext({ message }, { message, debugContext: createKafkaDebugContext(message) })
        })
        return this.pipeline.feed(batch, { grpcStreamId: streamId, grpcSeq: seq }, this.wireBudget(budget))
    }

    private wireBudget({ armedAt, softBudgetMs }: SubBatchBudget): BatchBudget {
        const softAt = budgetDeadline(armedAt, softBudgetMs)
        return softAt === null ? BatchBudget.unlimited() : BatchBudget.softDeadline(softAt)
    }

    async next(): Promise<CompletedSubBatch | null> {
        const result = await this.pipeline.next()
        if (result === null) {
            return null
        }
        // waitForAll snapshots the currently scheduled promises, so this
        // settles even under sustained load from other batches.
        const settled = (async (): Promise<void> => {
            await Promise.all(result.sideEffects ?? [])
            await this.promiseScheduler.waitForAll()
        })()
        const unfinished: MessageCoordinates[] = []
        for (const { result: elementResult, context } of result.elements) {
            if (isTimeoutResult(elementResult)) {
                unfinished.push({ partition: context.message.partition, offset: context.message.offset })
            }
        }
        return {
            streamId: result.batchContext.grpcStreamId,
            seq: result.batchContext.grpcSeq,
            accepted: result.elements.length - unfinished.length,
            unfinished,
            settled,
        }
    }
}
