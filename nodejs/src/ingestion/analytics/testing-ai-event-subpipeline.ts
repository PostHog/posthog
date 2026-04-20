import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { createProcessAiEventStep } from '../ai/pipelines/steps/process-ai-event-step'
import { IngestionWarningsOutput } from '../common/outputs'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createDisablePersonProcessingWithFakePersonStep } from '../event-processing/disable-person-processing-with-fake-person-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { EVENTS_OUTPUT, EventOutput } from './outputs'

export interface TestingAiEventSubpipelineInput {
    message: Message
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

export interface TestingAiEventSubpipelineConfig {
    outputs: IngestionOutputs<EventOutput | IngestionWarningsOutput>
    groupId: string
}

export function createTestingAiEventSubpipeline<TInput extends TestingAiEventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: TestingAiEventSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { outputs, groupId } = config

    // Compared to ai-event-subpipeline.ts:
    // CHANGED: createNormalizeProcessPersonFlagStep → createDisablePersonProcessingWithFakePersonStep
    //   (always disables person processing and provides a deterministic fake person)
    // REMOVED: createProcessPersonlessStep (fetches/creates personless persons from cache)
    // REMOVED: createProcessPersonsStep (creates/updates real person records, handles merges)
    // REMOVED: createProcessGroupsStep (creates/updates group records, enriches with group properties)
    // REMOVED: createHogTransformEventStep (no hog transformations — avoids Redis writes)
    // REMOVED: topHog metrics wrapping (no TopHog in this pipeline)
    return builder
        .pipe(createDisablePersonProcessingWithFakePersonStep())
        .pipe(createNormalizeEventStep())
        .pipe(createProcessAiEventStep())
        .pipe(createPrepareEventStep())
        .pipe(createCreateEventStep(EVENTS_OUTPUT))
        .pipe(createEmitEventStep({ outputs, groupId }))
}
