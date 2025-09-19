import { Message } from 'node-rdkafka'

import {
    BatchProcessingPipeline,
    BatchProcessingResult,
    BatchProcessingStep,
} from '../../ingestion/batch-processing-pipeline'
import {
    AsyncProcessingStep,
    ProcessingPipeline,
    ProcessingResult,
    SyncProcessingStep,
} from '../../ingestion/processing-pipeline'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { isDlqResult, isDropResult, isRedirectResult, isSuccessResult } from './event-pipeline/pipeline-step-result'
import { logDroppedMessage, redirectMessageToTopic, sendMessageToDLQ } from './pipeline-helpers'

export type PipelineConfig = {
    kafkaProducer: KafkaProducerWrapper
    dlqTopic: string
    promiseScheduler: PromiseScheduler
}

/**
 * Base class for handling pipeline results (DLQ, DROP, REDIRECT).
 * Contains common logic for processing non-success results.
 */
abstract class BaseResultHandlingPipeline<T> {
    protected constructor(
        protected originalMessage: Message,
        protected config: PipelineConfig
    ) {}

    /**
     * Handles a pipeline result, processing non-success results appropriately.
     * Returns the value for success results, null for non-success results.
     */
    protected async handleResult(result: ProcessingResult<T>, stepName: string): Promise<T | null> {
        if (isSuccessResult(result)) {
            return result.value
        }

        // Handle non-success results
        await this.handleNonSuccessResult(result, stepName)
        return null
    }

    private async handleNonSuccessResult(result: ProcessingResult<T>, stepName: string): Promise<void> {
        if (isDlqResult(result)) {
            await this.handleDlqResult(result, stepName)
        } else if (isDropResult(result)) {
            this.handleDropResult(result, stepName)
        } else if (isRedirectResult(result)) {
            await this.handleRedirectResult(result, stepName)
        }
    }

    private async handleDlqResult(result: { reason: string; error?: unknown }, stepName: string): Promise<void> {
        await sendMessageToDLQ(
            this.config.kafkaProducer,
            this.originalMessage,
            result.error || new Error(result.reason),
            stepName,
            this.config.dlqTopic
        )
    }

    private handleDropResult(result: { reason: string }, stepName: string): void {
        logDroppedMessage(this.originalMessage, result.reason, stepName)
    }

    private async handleRedirectResult(
        result: {
            reason: string
            topic: string
            preserveKey?: boolean
            awaitAck?: boolean
        },
        stepName: string
    ): Promise<void> {
        await redirectMessageToTopic(
            this.config.kafkaProducer,
            this.config.promiseScheduler,
            this.originalMessage,
            result.topic,
            stepName,
            result.preserveKey ?? true,
            result.awaitAck ?? true
        )
    }
}

/**
 * Wrapper around ProcessingPipeline that automatically handles result types (DLQ, DROP, REDIRECT)
 * and cuts execution short when encountering non-success results.
 *
 * Requires a KafkaProducerWrapper for DLQ and redirect functionality.
 */
export class ResultHandlingPipeline<T> extends BaseResultHandlingPipeline<T> {
    constructor(
        private pipeline: ProcessingPipeline<T>,
        originalMessage: Message,
        config: PipelineConfig
    ) {
        super(originalMessage, config)
    }

    pipe<U>(step: SyncProcessingStep<T, U>, _stepName?: string): ResultHandlingPipeline<U> {
        const newPipeline = this.pipeline.pipe(step)
        return new ResultHandlingPipeline(newPipeline, this.originalMessage, this.config)
    }

    pipeAsync<U>(step: AsyncProcessingStep<T, U>, _stepName?: string): ResultHandlingPipeline<U> {
        const newPipeline = this.pipeline.pipeAsync(step)
        return new ResultHandlingPipeline(newPipeline, this.originalMessage, this.config)
    }

    async unwrap(): Promise<T | null> {
        const result = await this.pipeline.unwrap()
        return this.handleResult(result, 'pipeline_result_handler')
    }

    static of<T>(value: T, originalMessage: Message, config: PipelineConfig): ResultHandlingPipeline<T> {
        const pipeline = ProcessingPipeline.of(value)
        return new ResultHandlingPipeline(pipeline, originalMessage, config)
    }
}

/**
 * Wrapper around BatchProcessingPipeline that automatically handles result types (DLQ, DROP, REDIRECT)
 * for each element in the batch and filters out non-success results.
 *
 * Requires a KafkaProducerWrapper for DLQ and redirect functionality.
 */
export class BatchResultHandlingPipeline<T> {
    constructor(
        private pipeline: BatchProcessingPipeline<T>,
        private originalMessages: Message[],
        private config: PipelineConfig
    ) {}

    pipe<U>(step: BatchProcessingStep<T, U>, _stepName?: string): BatchResultHandlingPipeline<U> {
        const newPipeline = this.pipeline.pipe(step)
        return new BatchResultHandlingPipeline(newPipeline, this.originalMessages, this.config)
    }

    pipeConcurrently<U>(
        stepConstructor: AsyncProcessingStep<T, U>,
        _stepName?: string
    ): BatchResultHandlingPipeline<U> {
        const newPipeline = this.pipeline.pipeConcurrently(stepConstructor)
        return new BatchResultHandlingPipeline(newPipeline, this.originalMessages, this.config)
    }

    async unwrap(): Promise<T[]> {
        const results = await this.pipeline.unwrap()
        return await this.handleBatchResults(results, 'batch_pipeline_result_handler')
    }

    private async handleBatchResults(results: BatchProcessingResult<T>, stepName: string): Promise<T[]> {
        const successfulValues: T[] = []

        for (let i = 0; i < results.length; i++) {
            const result = results[i]
            const originalMessage = this.originalMessages[i] || this.originalMessages[0] // Fallback to first message

            if (isSuccessResult(result)) {
                successfulValues.push(result.value)
            } else {
                await this.handleNonSuccessResult(result, originalMessage, stepName)
            }
        }

        return successfulValues
    }

    private async handleNonSuccessResult(
        result: ProcessingResult<T>,
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

    static of<T>(
        pipeline: BatchProcessingPipeline<T>,
        originalMessages: Message[],
        config: PipelineConfig
    ): BatchResultHandlingPipeline<T> {
        return new BatchResultHandlingPipeline(pipeline, originalMessages, config)
    }
}
