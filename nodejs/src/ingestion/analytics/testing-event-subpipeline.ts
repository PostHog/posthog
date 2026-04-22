import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { IngestionWarningsOutput } from '../common/outputs'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createDisablePersonProcessingWithFakePersonStep } from '../event-processing/disable-person-processing-with-fake-person-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { EVENTS_OUTPUT, EventOutput, HeatmapsOutput } from './outputs'

export interface TestingEventSubpipelineInput {
    message: Message
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

export interface TestingEventSubpipelineConfig {
    outputs: IngestionOutputs<EventOutput | HeatmapsOutput | IngestionWarningsOutput>
    groupId: string
}

export function createTestingEventSubpipeline<TInput extends TestingEventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: TestingEventSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { outputs, groupId } = config

    // Compared to event-subpipeline.ts:
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
        .pipe(createPrepareEventStep())
        .pipe(createExtractHeatmapDataStep(outputs))
        .pipe(createCreateEventStep(EVENTS_OUTPUT))
        .pipe(
            createEmitEventStep({
                outputs,
                groupId,
            })
        )
}
