import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { pipelineLastStepCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { logDroppedMessage, redirectMessageToTopic, sendMessageToDLQ } from '../../worker/ingestion/pipeline-helpers'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { PipelineResult, isDlqResult, isDropResult, isOkResult, isRedirectResult } from './results'

export type PipelineConfig = {
    kafkaProducer?: KafkaProducerWrapper
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
                const sideEffects = this.handleNonSuccessResult(result, originalMessage, stepName)

                processedResults.push({
                    result: resultWithContext.result,
                    context: {
                        ...resultWithContext.context,
                        sideEffects: [...resultWithContext.context.sideEffects, ...sideEffects],
                    },
                })
            }
        }

        return processedResults
    }

    private handleNonSuccessResult(
        result: PipelineResult<TOutput>,
        originalMessage: Message,
        stepName: string
    ): Promise<unknown>[] {
        const sideEffects: Promise<unknown>[] = []

        if (isDlqResult(result)) {
            if (!this.config.kafkaProducer) {
                logger.warn('📝', 'pipeline_dlq_no_producer', {
                    reason: result.reason,
                    stepName,
                    partition: originalMessage.partition,
                    offset: originalMessage.offset,
                })
                logDroppedMessage(originalMessage, `dlq unavailable: ${result.reason}`, stepName)
            } else {
                const dlqPromise = sendMessageToDLQ(
                    this.config.kafkaProducer,
                    originalMessage,
                    result.error || new Error(result.reason),
                    stepName,
                    this.config.dlqTopic
                )
                sideEffects.push(dlqPromise)
            }
        } else if (isDropResult(result)) {
            logDroppedMessage(originalMessage, result.reason, stepName)
        } else if (isRedirectResult(result)) {
            if (!this.config.kafkaProducer) {
                logger.warn('📝', 'pipeline_redirect_no_producer', {
                    reason: result.reason,
                    topic: result.topic,
                    stepName,
                    partition: originalMessage.partition,
                    offset: originalMessage.offset,
                })
                logDroppedMessage(originalMessage, `redirect unavailable: ${result.reason}`, stepName)
            } else {
                const redirectPromise = redirectMessageToTopic(
                    this.config.kafkaProducer,
                    this.config.promiseScheduler,
                    originalMessage,
                    result.topic,
                    stepName,
                    result.preserveKey ?? true,
                    result.awaitAck ?? true
                )
                sideEffects.push(redirectPromise)
            }
        }

        return sideEffects
    }
}
