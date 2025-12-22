import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Team } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
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
    options: EventPipelineRunnerOptions & {
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: string
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
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

export interface PerDistinctIdPipelineContext {
    message: Message
    team: Team
}

export function createPerDistinctIdPipeline<
    TInput extends PerDistinctIdPipelineInput,
    TContext extends PerDistinctIdPipelineContext,
>(builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>, config: PerDistinctIdPipelineConfig) {
    const {
        options,
        teamManager,
        groupTypeManager,
        hogTransformer,
        personsStore,
        kafkaProducer,
        groupId,
        dlqTopic,
        promiseScheduler,
    } = config

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
                                                    options,
                                                    teamManager,
                                                    groupTypeManager,
                                                    hogTransformer,
                                                    personsStore,
                                                    kafkaProducer,
                                                })
                                            )
                                            .branch('event', (b) =>
                                                createEventSubpipeline(b, {
                                                    options,
                                                    teamManager,
                                                    groupTypeManager,
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
