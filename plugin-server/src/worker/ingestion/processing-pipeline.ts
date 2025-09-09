import { Message } from 'node-rdkafka'

import {
    AsyncPreprocessingPipeline,
    AsyncPreprocessingStep,
    PreprocessingPipeline,
    PreprocessingResult,
    SyncPreprocessingStep,
} from '../../ingestion/preprocessing-pipeline'
import { KafkaProducerWrapper } from '../../kafka/producer'
import {
    PipelineStepResult,
    PipelineStepResultType,
    isDlqResult,
    isDropResult,
    isRedirectResult,
    isSuccessResult,
} from './event-pipeline/pipeline-step-result'
import { logDroppedMessage, redirectMessageToTopic, sendMessageToDLQ } from './pipeline-helpers'

export type ProcessingResult<T> = PipelineStepResult<T>

/**
 * Wrapper around PreprocessingPipeline that automatically handles result types (DLQ, DROP, REDIRECT)
 * and cuts execution short when encountering non-success results.
 *
 * Requires a KafkaProducerWrapper for DLQ and redirect functionality.
 */
export class PipelineResultHandler<T> {
    private constructor(
        private pipeline: PreprocessingPipeline<T>,
        private kafkaProducer: KafkaProducerWrapper,
        private originalMessage: Message,
        private dlqTopic: string
    ) {}

    pipe<U>(step: SyncPreprocessingStep<T, U>, _stepName?: string): PipelineResultHandler<U> {
        const newPipeline = this.pipeline.pipe(step)
        return new PipelineResultHandler(newPipeline, this.kafkaProducer, this.originalMessage, this.dlqTopic)
    }

    pipeAsync<U>(step: AsyncPreprocessingStep<T, U>, _stepName?: string): AsyncPipelineResultHandler<U> {
        const newPipeline = this.pipeline.pipeAsync(step)
        return new AsyncPipelineResultHandler(newPipeline, this.kafkaProducer, this.originalMessage, this.dlqTopic)
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

    private async handleNonSuccessResult(result: PreprocessingResult<T>): Promise<void> {
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
            this.kafkaProducer,
            this.originalMessage,
            result.error || new Error(result.reason),
            'pipeline_result_handler',
            this.dlqTopic
        )
    }

    private handleDropResult(result: { reason: string }): void {
        logDroppedMessage(this.originalMessage, result.reason, 'pipeline_result_handler')
    }

    private async handleRedirectResult(result: { reason: string; topic: string }): Promise<void> {
        await redirectMessageToTopic(this.kafkaProducer, this.originalMessage, result.topic, 'pipeline_result_handler')
    }

    static of<T>(
        value: T,
        kafkaProducer: KafkaProducerWrapper,
        originalMessage: Message,
        dlqTopic: string
    ): PipelineResultHandler<T> {
        const pipeline = PreprocessingPipeline.of(value)
        return new PipelineResultHandler(pipeline, kafkaProducer, originalMessage, dlqTopic)
    }

    static fromPipeline<T>(
        pipeline: PreprocessingPipeline<T>,
        kafkaProducer: KafkaProducerWrapper,
        originalMessage: Message,
        dlqTopic: string
    ): PipelineResultHandler<T> {
        return new PipelineResultHandler(pipeline, kafkaProducer, originalMessage, dlqTopic)
    }
}

/**
 * Wrapper around AsyncPreprocessingPipeline that automatically handles result types (DLQ, DROP, REDIRECT)
 * and cuts execution short when encountering non-success results.
 *
 * Requires a KafkaProducerWrapper for DLQ and redirect functionality.
 */
export class AsyncPipelineResultHandler<T> {
    constructor(
        private pipeline: AsyncPreprocessingPipeline<T>,
        private kafkaProducer: KafkaProducerWrapper,
        private originalMessage: Message,
        private dlqTopic: string
    ) {}

    pipe<U>(step: SyncPreprocessingStep<T, U>, _stepName?: string): AsyncPipelineResultHandler<U> {
        const newPipeline = this.pipeline.pipe(step)
        return new AsyncPipelineResultHandler(newPipeline, this.kafkaProducer, this.originalMessage, this.dlqTopic)
    }

    pipeAsync<U>(step: AsyncPreprocessingStep<T, U>, _stepName?: string): AsyncPipelineResultHandler<U> {
        const newPipeline = this.pipeline.pipeAsync(step)
        return new AsyncPipelineResultHandler(newPipeline, this.kafkaProducer, this.originalMessage, this.dlqTopic)
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

    private async handleNonSuccessResult(result: PreprocessingResult<T>): Promise<void> {
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
            this.kafkaProducer,
            this.originalMessage,
            result.error || new Error(result.reason),
            'async_pipeline_result_handler',
            this.dlqTopic
        )
    }

    private handleDropResult(result: { reason: string }): void {
        logDroppedMessage(this.originalMessage, result.reason, 'async_pipeline_result_handler')
    }

    private async handleRedirectResult(result: { reason: string; topic: string }): Promise<void> {
        await redirectMessageToTopic(
            this.kafkaProducer,
            this.originalMessage,
            result.topic,
            'async_pipeline_result_handler'
        )
    }

    static of<T>(
        value: T,
        kafkaProducer: KafkaProducerWrapper,
        originalMessage: Message,
        dlqTopic: string
    ): AsyncPipelineResultHandler<T> {
        const pipeline = PreprocessingPipeline.of(value).pipeAsync((v) =>
            Promise.resolve({ type: PipelineStepResultType.OK, value: v })
        )
        return new AsyncPipelineResultHandler(pipeline, kafkaProducer, originalMessage, dlqTopic)
    }

    static fromPipeline<T>(
        pipeline: AsyncPreprocessingPipeline<T>,
        kafkaProducer: KafkaProducerWrapper,
        originalMessage: Message,
        dlqTopic: string
    ): AsyncPipelineResultHandler<T> {
        return new AsyncPipelineResultHandler(pipeline, kafkaProducer, originalMessage, dlqTopic)
    }
}
