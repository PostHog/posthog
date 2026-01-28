import { Message } from 'node-rdkafka'

import { Team } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import {
    PerEventProcessingConfig,
    PerEventProcessingInput,
    createPerEventProcessingSubpipeline,
} from './per-event-processing-subpipeline'

export type PerDistinctIdPipelineInput = PerEventProcessingInput

export interface PerDistinctIdPipelineConfig extends PerEventProcessingConfig {
    dlqTopic: string
    promiseScheduler: PromiseScheduler
}

export interface PerDistinctIdPipelineContext {
    message: Message
    team: Team
}

export function createPerDistinctIdPipeline<
    TInput extends PerDistinctIdPipelineInput,
    TContext extends PerDistinctIdPipelineContext,
>(builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>, config: PerDistinctIdPipelineConfig) {
    const { kafkaProducer, dlqTopic, promiseScheduler } = config

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    return (
        builder
            .messageAware((b) =>
                b
                    .teamAware((b) => b.sequentially((e) => createPerEventProcessingSubpipeline(e, config)))
                    .handleIngestionWarnings(kafkaProducer)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: false })
            // We synchronize once again to ensure we return all events in one batch.
            .gather()
    )
}
