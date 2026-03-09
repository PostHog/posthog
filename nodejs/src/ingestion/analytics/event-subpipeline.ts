import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createHogTransformEventStep } from '../event-processing/hog-transform-event-step'
import { EVENTS_OUTPUT, EventOutput, IngestionOutputs } from '../event-processing/ingestion-outputs'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '../event-processing/normalize-process-person-flag-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { createProcessGroupsStep } from '../event-processing/process-groups-step'
import { createProcessPersonlessStep } from '../event-processing/process-personless-step'
import { createProcessPersonsStep } from '../event-processing/process-persons-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { TopHogWrapper, sum, sumOk, sumResult, timer } from '../pipelines/extensions/tophog'
import { isDropResult } from '../pipelines/results'

export interface EventSubpipelineInput {
    message: Message
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

export interface EventSubpipelineConfig {
    options: EventPipelineRunnerOptions & {
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    outputs: IngestionOutputs<EventOutput>
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformerService
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    kafkaProducer: KafkaProducerWrapper
    groupId: string
    topHog: TopHogWrapper
}

export function createEventSubpipeline<TInput extends EventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: EventSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const {
        options,
        outputs,
        teamManager,
        groupTypeManager,
        hogTransformer,
        personsStore,
        groupStore,
        kafkaProducer,
        groupId,
        topHog,
    } = config

    return builder
        .pipe(createNormalizeProcessPersonFlagStep())
        .pipe(
            topHog(createHogTransformEventStep(hogTransformer), [
                sumOk(
                    'transformations_run',
                    (output) => ({ team_id: String(output.team.id) }),
                    (output) => output.transformationsRun
                ),
                sumOk(
                    'transformations_run_per_partition',
                    (output, input) => ({
                        team_id: String(output.team.id),
                        partition: String(input.message.partition),
                    }),
                    (output) => output.transformationsRun
                ),
                sumResult(
                    'events_dropped_by_transformation',
                    (_result, input) => ({ team_id: String(input.team.id) }),
                    (result) => (isDropResult(result) ? 1 : 0)
                ),
                sumResult(
                    'events_dropped_by_transformation_per_partition',
                    (_result, input) => ({
                        team_id: String(input.team.id),
                        partition: String(input.message.partition),
                    }),
                    (result) => (isDropResult(result) ? 1 : 0)
                ),
            ])
        )
        .pipe(createNormalizeEventStep())
        .pipe(createProcessPersonlessStep(personsStore))
        .pipe(
            topHog(createProcessPersonsStep(options, kafkaProducer, personsStore), [
                timer('process_persons_time', (input) => ({
                    team_id: String(input.team.id),
                    distinct_id: input.normalizedEvent.distinct_id,
                })),
            ])
        )
        .pipe(createPrepareEventStep())
        .pipe(createProcessGroupsStep(teamManager, groupTypeManager, groupStore, options))
        .pipe(
            createExtractHeatmapDataStep({
                kafkaProducer,
                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: options.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
            })
        )
        .pipe(createCreateEventStep(EVENTS_OUTPUT))
        .pipe(
            topHog(
                createEmitEventStep({
                    outputs,
                    groupId,
                }),
                [
                    sum(
                        'emitted_events',
                        (input) => ({ team_id: String(input.teamId) }),
                        (input) => input.eventsToEmit.length
                    ),
                    sum(
                        'emitted_events_per_distinct_id',
                        (input) => ({
                            team_id: String(input.teamId),
                            distinct_id: input.eventsToEmit[0]?.event.distinct_id ?? '',
                            partition: String(input.message.partition),
                        }),
                        (input) => input.eventsToEmit.length
                    ),
                    sum(
                        'emitted_events_per_partition',
                        (input) => ({
                            team_id: String(input.teamId),
                            partition: String(input.message.partition),
                        }),
                        (input) => input.eventsToEmit.length
                    ),
                ]
            )
        )
}
