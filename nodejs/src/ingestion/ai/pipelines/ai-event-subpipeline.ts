import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { HogTransformerService } from '../../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { EventHeaders, Team } from '../../../types'
import { TeamManager } from '../../../utils/team-manager'
import { GroupTypeManager } from '../../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../../worker/ingestion/persons/persons-store'
import { createCreateEventStep } from '../../event-processing/create-event-step'
import { createEmitEventStep } from '../../event-processing/emit-event-step'
import { EventPipelineRunnerOptions } from '../../event-processing/event-pipeline-options'
import { createHogTransformEventStep } from '../../event-processing/hog-transform-event-step'
import { EVENTS_OUTPUT, EventOutput, IngestionOutputs } from '../../event-processing/ingestion-outputs'
import { createNormalizeEventStep } from '../../event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '../../event-processing/normalize-process-person-flag-step'
import { createPrepareEventStep } from '../../event-processing/prepare-event-step'
import { createProcessPersonlessStep } from '../../event-processing/process-personless-step'
import { createProcessPersonsStep } from '../../event-processing/process-persons-step'
import { PipelineBuilder, StartPipelineBuilder } from '../../pipelines/builders/pipeline-builders'
import { TopHogWrapper, sum } from '../../pipelines/extensions/tophog'
import { createProcessAiEventStep } from './steps/process-ai-event-step'

export interface AiEventSubpipelineInput {
    message: Message
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

export interface AiEventSubpipelineConfig {
    options: EventPipelineRunnerOptions
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

export function createAiEventSubpipeline<TInput extends AiEventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: AiEventSubpipelineConfig
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
        .pipe(createHogTransformEventStep(hogTransformer))
        .pipe(createNormalizeEventStep())
        .pipe(createProcessAiEventStep())
        .pipe(createProcessPersonlessStep(personsStore))
        .pipe(createProcessPersonsStep(options, kafkaProducer, personsStore))
        .pipe(createPrepareEventStep(teamManager, groupTypeManager, groupStore, options))
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
                ]
            )
        )
}
