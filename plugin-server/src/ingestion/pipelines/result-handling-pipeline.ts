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
 * non-success results (DLQ, DROP, REDIRECT) while filtering to only successful values.
 */
export class ResultHandlingPipeline<TInput, TOutput> {
    constructor(
        private pipeline: BatchPipeline<TInput, TOutput>,
        private config: PipelineConfig
    ) {}

    feed(elements: BatchPipelineResultWithContext<TInput>): void {
        this.pipeline.feed(elements)
    }

    async next(): Promise<TOutput[] | null> {
        const results = await this.pipeline.next()

        if (results === null) {
            return null
        }

        // Process results and handle non-success cases
        const processedResults: TOutput[] = []

        for (const resultWithContext of results) {
            // Report last step for all results (success and failure)
            const lastStep = resultWithContext.context.lastStep
            if (lastStep) {
                pipelineLastStepCounter.labels(lastStep).inc()
            }

            if (isOkResult(resultWithContext.result)) {
                const value = resultWithContext.result.value as TOutput
                processedResults.push(value)
            } else {
                // For non-success results, get the message from context
                const result = resultWithContext.result
                const originalMessage = resultWithContext.context.message
                const lastStep = resultWithContext.context.lastStep || 'unknown'
                await this.handleNonSuccessResult(result, originalMessage, lastStep)
            }
        }

        // Return only successful results
        return processedResults
    }

    private async handleNonSuccessResult(
        result: PipelineResult<TOutput>,
        originalMessage: Message,
        stepName: string
    ): Promise<void> {
        if (isDlqResult(result)) {
            await sendMessageToDLQ(
                this.config.kafkaProducer,
                originalMessage,
                result.error || new Error(result.reason),
                stepName,
                this.config.dlqTopic
            )
        } else if (isDropResult(result)) {
            logDroppedMessage(originalMessage, result.reason, stepName)
        } else if (isRedirectResult(result)) {
            await redirectMessageToTopic(
                this.config.kafkaProducer,
                this.config.promiseScheduler,
                originalMessage,
                result.topic,
                stepName,
                result.preserveKey ?? true,
                result.awaitAck ?? true
            )
        }
    }

    static of<TInput, TOutput>(
        pipeline: BatchPipeline<TInput, TOutput>,
        config: PipelineConfig
    ): ResultHandlingPipeline<TInput, TOutput> {
        return new ResultHandlingPipeline(pipeline, config)
    }
}
