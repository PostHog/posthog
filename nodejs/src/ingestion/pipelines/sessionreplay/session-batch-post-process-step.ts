import { Message } from 'node-rdkafka'

import { OverflowOutput } from '~/common/outputs'
import { BatchPipelineResultWithContext } from '~/ingestion/framework/batch-pipeline.interface'
import {
    AfterBatchInput,
    AfterBatchOutput,
    BatchingContext,
    BeforeBatchInput,
    BeforeBatchOutput,
} from '~/ingestion/framework/batching-pipeline'
import { isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { KafkaOffsetManager } from './kafka/offset-manager'
import { SessionReplayPipelineOutput } from './session-replay-pipeline'

/**
 * beforeBatch passthrough for the record pipeline: the accumulating pipeline mints and tags on the
 * real batch context (the recorder), so the batching pipeline itself needs no batch state — its
 * batch context is empty and the fed elements pass straight through to the sub-pipeline.
 */
export function createReplayBeforeBatchStep<TInput, CInput>(): ProcessingStep<
    BeforeBatchInput<TInput, CInput>,
    BeforeBatchOutput<TInput, CInput, Record<never, object>>
> {
    return (input) => Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
}

/**
 * Trimmed record-pipeline output: the heavy Kafka `message` and parsed payload are dropped once a
 * message is recorded, so what accumulates for the flush is a lightweight per-message row.
 */
export interface TrimmedReplayElement {
    partition: number
    timestamp: number
}

/**
 * Narrows the recorded element down to the pipeline's declared output ({@link SessionReplayPipelineOutput}).
 * The record step passes its rich input straight through; this projection makes the sub-pipeline's
 * output type exact, which the batching pipeline requires (the afterBatch then trims it further).
 */
export function createProjectReplayOutputStep<T extends SessionReplayPipelineOutput>(): ProcessingStep<
    T,
    SessionReplayPipelineOutput
> {
    return (input) => Promise.resolve(ok({ team: input.team, parsedMessage: input.parsedMessage }))
}

type PostProcessInput = AfterBatchInput<
    SessionReplayPipelineOutput,
    { message: Message } & BatchingContext,
    Record<never, object>,
    OverflowOutput
>

type PostProcessOutput = AfterBatchOutput<
    TrimmedReplayElement,
    { messageId: number },
    Record<never, object>,
    OverflowOutput
>

/**
 * afterBatch post-process for the session replay record pipeline. For every result (ok, drop, dlq,
 * redirect) it tracks the source message's offset — so dropped and DLQ'd messages advance offsets
 * too — and surfaces the result's side effects (the DLQ/overflow produces result handling attached)
 * so the accumulating pipeline can make them durable before committing. It emits only the OK results,
 * trimmed to a lightweight row with just the messageId kept on the context.
 */
export function createPostProcessStep(
    offsetManager: KafkaOffsetManager
): ProcessingStep<PostProcessInput, PostProcessOutput> {
    return function postProcessStep(input) {
        const sideEffects: Promise<unknown>[] = []
        const elements: BatchPipelineResultWithContext<TrimmedReplayElement, { messageId: number }, OverflowOutput> = []

        for (const element of input.elements) {
            offsetManager.trackOffset({
                partition: element.context.message.partition,
                offset: element.context.message.offset,
            })
            sideEffects.push(...element.context.sideEffects)

            if (isOkResult(element.result)) {
                elements.push({
                    result: ok({
                        partition: element.context.message.partition,
                        timestamp: Date.now(),
                    }),
                    context: {
                        messageId: element.context.messageId,
                        sideEffects: [],
                        warnings: [],
                    },
                })
            }
        }

        return Promise.resolve(ok({ elements, batchContext: input.batchContext, batchId: input.batchId }, sideEffects))
    }
}
