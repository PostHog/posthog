import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, Team } from '../../types'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { EVENTS_OUTPUT, EventOutput, IngestionOutputs } from '../event-processing/ingestion-outputs'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '../event-processing/normalize-process-person-flag-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { createProcessPersonlessStep } from '../event-processing/process-personless-step'
import { createReadonlyProcessPersonsStep } from '../event-processing/readonly-process-persons-step'
import { createTestingPublishPersonUpdateStep } from '../event-processing/testing-publish-person-update-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface TestingEventSubpipelineInput {
    message: Message
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

export interface TestingEventSubpipelineConfig {
    options: {
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    outputs: IngestionOutputs<EventOutput>
    personsStore: PersonsStore
    kafkaProducer: KafkaProducerWrapper
    groupId: string
}

export function createTestingEventSubpipeline<TInput extends TestingEventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: TestingEventSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, outputs, personsStore, kafkaProducer, groupId } = config

    // Compared to event-subpipeline.ts:
    // CHANGED: createProcessPersonsStep → createReadonlyProcessPersonsStep + createPublishPersonUpdateStep
    //   (reads person from DB, computes property diff, publishes Kafka update — never writes to Postgres)
    // REMOVED: createProcessGroupsStep (creates/updates group records, enriches with group properties)
    // REMOVED: createHogTransformEventStep (no hog transformations — avoids Redis writes)
    // REMOVED: topHog metrics wrapping (no TopHog in this pipeline)
    return builder
        .pipe(createNormalizeProcessPersonFlagStep())
        .pipe(createNormalizeEventStep())
        .pipe(createProcessPersonlessStep(personsStore))
        .pipe(createReadonlyProcessPersonsStep(personsStore))
        .pipe(createTestingPublishPersonUpdateStep(kafkaProducer))
        .pipe(createPrepareEventStep())
        .pipe(
            createExtractHeatmapDataStep({
                kafkaProducer,
                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: options.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
            })
        )
        .pipe(createCreateEventStep(EVENTS_OUTPUT))
        .pipe(
            createEmitEventStep({
                outputs,
                groupId,
            })
        )
}
