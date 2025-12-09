import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub, Team } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import {
    ClientIngestionWarningSubpipelineInput,
    createClientIngestionWarningSubpipeline,
} from './client-ingestion-warning-subpipeline'
import { EventSubpipelineInput, createEventSubpipeline } from './event-subpipeline'
import { HeatmapSubpipelineInput, createHeatmapSubpipeline } from './heatmap-subpipeline'

export type PerDistinctIdPipelineInput = EventSubpipelineInput &
    HeatmapSubpipelineInput &
    ClientIngestionWarningSubpipelineInput

export interface PerDistinctIdPipelineConfig {
    hub: Hub
    hogTransformer: HogTransformerService
    personsStore: PersonsStore
    kafkaProducer: KafkaProducerWrapper
    groupId: string
    dlqTopic: string
    promiseScheduler: PromiseScheduler
}

type EventBranch = 'client_ingestion_warning' | 'heatmap' | 'event'

function classifyEvent<TInput extends PerDistinctIdPipelineInput>(input: TInput): EventBranch {
    switch (input.event.event) {
        case '$$client_ingestion_warning':
            return 'client_ingestion_warning'
        case '$$heatmap':
            return 'heatmap'
        default:
            return 'event'
    }
}

export function createPerDistinctIdPipeline<TInput extends PerDistinctIdPipelineInput>(
    builder: BatchPipelineBuilder<TInput, TInput, { message: Message; team: Team }, { message: Message; team: Team }>,
    config: PerDistinctIdPipelineConfig
) {
    const { hub, hogTransformer, personsStore, kafkaProducer, groupId, dlqTopic, promiseScheduler } = config

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    return (
        builder
            .messageAware((b) =>
                b
                    .teamAware((b) =>
                        // We process the events for the distinct id sequentially to provide ordering guarantees.
                        b.sequentially((event) =>
                            event.retry(
                                (e) =>
                                    e.branching<EventBranch, void>(classifyEvent, (branches) => {
                                        branches
                                            .branch('client_ingestion_warning', (b) =>
                                                createClientIngestionWarningSubpipeline(b)
                                            )
                                            .branch('heatmap', (b) =>
                                                createHeatmapSubpipeline(b, {
                                                    hub,
                                                    hogTransformer,
                                                    personsStore,
                                                    kafkaProducer,
                                                })
                                            )
                                            .branch('event', (b) =>
                                                createEventSubpipeline(b, {
                                                    hub,
                                                    hogTransformer,
                                                    personsStore,
                                                    kafkaProducer,
                                                    groupId,
                                                })
                                            )
                                    }),
                                {
                                    tries: 3,
                                    sleepMs: 100,
                                }
                            )
                        )
                    )
                    .handleIngestionWarnings(kafkaProducer)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: false })
            // We synchronize once again to ensure we return all events in one batch.
            .gather()
    )
}
