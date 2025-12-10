import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, Hub, PipelineEvent, Team } from '../../types'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { createEventPipelineRunnerV1Step } from '../event-processing/event-pipeline-runner-v1-step'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createNormalizeProcessPersonFlagStep } from '../event-processing/normalize-process-person-flag-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface EventSubpipelineInput {
    message: Message
    event: PipelineEvent
    team: Team
    headers: EventHeaders
    groupStoreForBatch: GroupStoreForBatch
}

export interface EventSubpipelineConfig {
    hub: Hub
    hogTransformer: HogTransformerService
    personsStore: PersonsStore
    kafkaProducer: KafkaProducerWrapper
    groupId: string
}

export function createEventSubpipeline<TInput extends EventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: EventSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { hub, hogTransformer, personsStore, kafkaProducer, groupId } = config

    return builder
        .pipe(createNormalizeProcessPersonFlagStep())
        .pipe(createEventPipelineRunnerV1Step(hub, hogTransformer, personsStore))
        .pipe(
            createExtractHeatmapDataStep({
                kafkaProducer,
                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
            })
        )
        .pipe(createCreateEventStep())
        .pipe(
            createEmitEventStep({
                kafkaProducer,
                clickhouseJsonEventsTopic: hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                groupId,
            })
        )
}
