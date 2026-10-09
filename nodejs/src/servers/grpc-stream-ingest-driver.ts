import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { CompletedSubBatch, StreamIngestDriver, SubBatchBudget } from '~/ingestion/api/grpc-server'
import { deserializeKafkaMessage } from '~/ingestion/api/kafka-message-converter'
import { SerializedKafkaMessage } from '~/ingestion/api/types'
import { BatchBudget, budgetDeadline } from '~/ingestion/framework/batch-budget'
import { FeedResult } from '~/ingestion/framework/batching-pipeline'
import { createKafkaDebugContext, createOkContext } from '~/ingestion/framework/helpers'
import { isTimeoutResult } from '~/ingestion/framework/results'
import {
    JoinedIngestionPipelineContext,
    JoinedIngestionPipelineInput,
    createJoinedIngestionPipeline,
} from '~/ingestion/pipelines/analytics/joined-ingestion-pipeline'

/** Batch context fed with each gRPC sub-batch so its completion routes back to the right stream. */
export type GrpcBatchContext = { grpcStreamId: number; grpcSeq: number }

export type GrpcIngestPipeline = ReturnType<
    typeof createJoinedIngestionPipeline<JoinedIngestionPipelineInput, JoinedIngestionPipelineContext, GrpcBatchContext>
>

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

    /**
     * Turn what the consumer sent into the batch's budget, and nothing else:
     * the worker has no sizing config of its own.
     */
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
        // The elements are in feed order, so their positions are the message
        // positions the consumer sent.
        const timedOut: number[] = []
        result.elements.forEach((element, index) => {
            if (isTimeoutResult(element.result)) {
                timedOut.push(index)
            }
        })
        return {
            streamId: result.batchContext.grpcStreamId,
            seq: result.batchContext.grpcSeq,
            accepted: result.elements.length - timedOut.length,
            timedOut,
            settled,
        }
    }
}
