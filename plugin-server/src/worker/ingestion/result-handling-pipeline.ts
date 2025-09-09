import { Message } from 'node-rdkafka'

import {
    AsyncPreprocessingStep,
    AsyncProcessingPipeline,
    ProcessingPipeline,
    ProcessingResult,
    SyncPreprocessingStep,
} from '../../ingestion/processing-pipeline'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import {
    PipelineStepResultType,
    isDlqResult,
    isDropResult,
    isRedirectResult,
    isSuccessResult,
} from './event-pipeline/pipeline-step-result'
import { logDroppedMessage, redirectMessageToTopic, sendMessageToDLQ } from './pipeline-helpers'

export type PipelineConfig = {
    kafkaProducer: KafkaProducerWrapper
    dlqTopic: string
    consumerGroupId?: string
    promiseScheduler: PromiseScheduler
}

/**
 * Wrapper around ProcessingPipeline that automatically handles result types (DLQ, DROP, REDIRECT)
 * and cuts execution short when encountering non-success results.
 *
 * Requires a KafkaProducerWrapper for DLQ and redirect functionality.
 */
export class ResultHandlingPipeline<T> {
    private constructor(
        private pipeline: ProcessingPipeline<T>,
        private originalMessage: Message,
        private config: PipelineConfig
    ) {}

    pipe<U>(step: SyncPreprocessingStep<T, U>, _stepName?: string): ResultHandlingPipeline<U> {
        const newPipeline = this.pipeline.pipe(step)
        return new ResultHandlingPipeline(newPipeline, this.originalMessage, this.config)
    }

    pipeAsync<U>(step: AsyncPreprocessingStep<T, U>, _stepName?: string): AsyncResultHandlingPipeline<U> {
        const newPipeline = this.pipeline.pipeAsync(step)
        return new AsyncResultHandlingPipeline(newPipeline, this.originalMessage, this.config)
    }

    async unwrap(): Promise<T | null> {
        const result = this.pipeline.unwrap()

        if (isSuccessResult(result)) {
            return result.value
        }

        // Handle non-success results
        await this.handleNonSuccessResult(result)
        return null
    }

    private async handleNonSuccessResult(result: ProcessingResult<T>): Promise<void> {
        if (isDlqResult(result)) {
            await this.handleDlqResult(result)
        } else if (isDropResult(result)) {
            this.handleDropResult(result)
        } else if (isRedirectResult(result)) {
            await this.handleRedirectResult(result)
        }
    }

    private async handleDlqResult(result: { reason: string; error?: unknown }): Promise<void> {
        await sendMessageToDLQ(
            this.config.kafkaProducer,
            this.originalMessage,
            result.error || new Error(result.reason),
            'pipeline_result_handler',
            this.config.dlqTopic
        )
    }

    private handleDropResult(result: { reason: string }): void {
        logDroppedMessage(this.originalMessage, result.reason, 'pipeline_result_handler')
    }

    private async handleRedirectResult(result: {
        reason: string
        topic: string
        preserveKey?: boolean
        awaitAck?: boolean
    }): Promise<void> {
        await redirectMessageToTopic(
            this.config.kafkaProducer,
            this.config.promiseScheduler,
            this.originalMessage,
            result.topic,
            'pipeline_result_handler',
            result.preserveKey ?? true,
            result.awaitAck ?? true,
            this.config.consumerGroupId
        )
    }

    static of<T>(value: T, originalMessage: Message, config: PipelineConfig): ResultHandlingPipeline<T> {
        const pipeline = ProcessingPipeline.of(value)
        return new ResultHandlingPipeline(pipeline, originalMessage, config)
    }

    static fromPipeline<T>(
        pipeline: ProcessingPipeline<T>,
        originalMessage: Message,
        config: PipelineConfig
    ): ResultHandlingPipeline<T> {
        return new ResultHandlingPipeline(pipeline, originalMessage, config)
    }
}

/**
 * Wrapper around AsyncProcessingPipeline that automatically handles result types (DLQ, DROP, REDIRECT)
 * and cuts execution short when encountering non-success results.
 *
 * Requires a KafkaProducerWrapper for DLQ and redirect functionality.
 */
export class AsyncResultHandlingPipeline<T> {
    constructor(
        private pipeline: AsyncProcessingPipeline<T>,
        private originalMessage: Message,
        private config: PipelineConfig
    ) {}

    pipe<U>(step: SyncPreprocessingStep<T, U>, _stepName?: string): AsyncResultHandlingPipeline<U> {
        const newPipeline = this.pipeline.pipe(step)
        return new AsyncResultHandlingPipeline(newPipeline, this.originalMessage, this.config)
    }

    pipeAsync<U>(step: AsyncPreprocessingStep<T, U>, _stepName?: string): AsyncResultHandlingPipeline<U> {
        const newPipeline = this.pipeline.pipeAsync(step)
        return new AsyncResultHandlingPipeline(newPipeline, this.originalMessage, this.config)
    }

    async unwrap(): Promise<T | null> {
        const result = await this.pipeline.unwrap()

        if (isSuccessResult(result)) {
            return result.value
        }

        // Handle non-success results
        await this.handleNonSuccessResult(result)
        return null
    }

    private async handleNonSuccessResult(result: ProcessingResult<T>): Promise<void> {
        if (isDlqResult(result)) {
            await this.handleDlqResult(result)
        } else if (isDropResult(result)) {
            this.handleDropResult(result)
        } else if (isRedirectResult(result)) {
            await this.handleRedirectResult(result)
        }
    }

    private async handleDlqResult(result: { reason: string; error?: unknown }): Promise<void> {
        await sendMessageToDLQ(
            this.config.kafkaProducer,
            this.originalMessage,
            result.error || new Error(result.reason),
            'async_pipeline_result_handler',
            this.config.dlqTopic
        )
    }

    private handleDropResult(result: { reason: string }): void {
        logDroppedMessage(this.originalMessage, result.reason, 'async_pipeline_result_handler')
    }

    private async handleRedirectResult(result: {
        reason: string
        topic: string
        preserveKey?: boolean
        awaitAck?: boolean
    }): Promise<void> {
        await redirectMessageToTopic(
            this.config.kafkaProducer,
            this.config.promiseScheduler,
            this.originalMessage,
            result.topic,
            'async_pipeline_result_handler',
            result.preserveKey ?? true,
            result.awaitAck ?? true,
            this.config.consumerGroupId
        )
    }

    static of<T>(value: T, originalMessage: Message, config: PipelineConfig): AsyncResultHandlingPipeline<T> {
        const pipeline = ProcessingPipeline.of(value).pipeAsync((v) =>
            Promise.resolve({ type: PipelineStepResultType.OK, value: v })
        )
        return new AsyncResultHandlingPipeline(pipeline, originalMessage, config)
    }

    static fromPipeline<T>(
        pipeline: AsyncProcessingPipeline<T>,
        originalMessage: Message,
        config: PipelineConfig
    ): AsyncResultHandlingPipeline<T> {
        return new AsyncResultHandlingPipeline(pipeline, originalMessage, config)
    }
}
