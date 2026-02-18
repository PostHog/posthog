import { Message } from 'node-rdkafka'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { createEventPipelineRunnerV1Step } from '../event-processing/event-pipeline-runner-v1-step'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createHogTransformEventStep } from '../event-processing/hog-transform-event-step'
import { createNormalizeProcessPersonFlagStep } from '../event-processing/normalize-process-person-flag-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface EventSubpipelineInput {
    message: Message
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

export interface EventSubpipelineConfig {
    options: EventPipelineRunnerOptions & {
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: string
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
    groupId: string
}

export function createEventSubpipeline<TInput extends EventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: EventSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, teamManager, groupTypeManager, hogTransformer, personsStore, groupStore, kafkaProducer, groupId } =
        config

    return builder
        .pipe(createNormalizeProcessPersonFlagStep())
        .pipe(createHogTransformEventStep(hogTransformer))
        .pipe(
            createEventPipelineRunnerV1Step(
                options,
                kafkaProducer,
                teamManager,
                groupTypeManager,
                personsStore,
                groupStore
            )
        )
        .pipe(
            createExtractHeatmapDataStep({
                kafkaProducer,
                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: options.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
            })
        )
        .pipe(createCreateEventStep())
        .pipe(
            createEmitEventStep({
                kafkaProducer,
                clickhouseJsonEventsTopic: options.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                groupId,
            })
        )
}
