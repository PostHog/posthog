import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { pipelineLastStepCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { logDroppedMessage, redirectMessageToTopic, sendMessageToDLQ } from '../../worker/ingestion/pipeline-helpers'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { PipelineResult, isDlqResult, isDropResult, isOkResult, isRedirectResult } from './results'

export type PipelineConfig = {
    kafkaProducer: KafkaProducerWrapper
    dlqTopic: string
    promiseScheduler: PromiseScheduler
}

/**
 * Unified result handling pipeline that wraps any BatchProcessingPipeline and handles
 * non-success results (DLQ, DROP, REDIRECT) by adding side effects.
 */
export class ResultHandlingPipeline<
    TInput,
    TOutput,
    CInput extends { message: Message },
    COutput extends { message: Message } = CInput,
> implements BatchPipeline<TInput, TOutput, CInput, COutput>
{
    constructor(
        private pipeline: BatchPipeline<TInput, TOutput, CInput, COutput>,
        private config: PipelineConfig
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.pipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput> | null> {
        const results = await this.pipeline.next()

        if (results === null) {
            return null
        }

        const processedResults: BatchPipelineResultWithContext<TOutput, COutput> = []

        for (const resultWithContext of results) {
            const lastStep = resultWithContext.context.lastStep
            if (lastStep) {
                pipelineLastStepCounter.labels(lastStep).inc()
            }

            if (isOkResult(resultWithContext.result)) {
                processedResults.push(resultWithContext)
            } else {
                const result = resultWithContext.result
                const originalMessage = resultWithContext.context.message
                const stepName = resultWithContext.context.lastStep || 'unknown'
                this.handleNonSuccessResult(result, originalMessage, stepName)

                processedResults.push(resultWithContext)
            }
        }

        return processedResults
    }

    private handleNonSuccessResult(result: PipelineResult<TOutput>, originalMessage: Message, stepName: string): void {
        if (isDlqResult(result)) {
            sendMessageToDLQ(
                this.config.kafkaProducer,
                originalMessage,
                result.error || new Error(result.reason),
                stepName,
                this.config.dlqTopic
            )
        } else if (isDropResult(result)) {
            logDroppedMessage(originalMessage, result.reason, stepName)
        } else if (isRedirectResult(result)) {
            redirectMessageToTopic(
                this.config.kafkaProducer,
                this.config.promiseScheduler,
                originalMessage,
                result.topic,
                stepName,
                result.preserveKey ?? true
            )
        }
    }
}
