import { AsyncOutput, EVENTS_OUTPUT } from '~/common/outputs'
import type { AiEventSubpipelineConfig, AiEventSubpipelineInput } from '~/ingestion/common/ai-subpipeline.contract'
import { createProcessGroupsStep } from '~/ingestion/event-processing/process-groups-step'

import { createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'
import { createCreateEventStep } from '~/ingestion/event-processing/create-event-step'
import { EmitEventStepOutput, createEmitEventStep } from '~/ingestion/event-processing/emit-event-step'
import { createHogTransformEventStep } from '~/ingestion/event-processing/hog-transform-event-step'
import { createNormalizeEventStep } from '~/ingestion/event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '~/ingestion/event-processing/normalize-process-person-flag-step'
import { createPrepareEventStep } from '~/ingestion/event-processing/prepare-event-step'
import { createProcessPersonlessStep } from '~/ingestion/event-processing/process-personless-step'
import { createProcessPersonsStep } from '~/ingestion/event-processing/process-persons-step'
import { createSplitAiEventsStep } from '~/ingestion/event-processing/split-ai-events-step'
import { PipelineBuilder, StartPipelineBuilder } from '~/ingestion/pipelines/builders/pipeline-builders'
import { sum, sumOk, sumResult, timer } from '~/ingestion/pipelines/extensions/tophog'
import { isDropResult } from '~/ingestion/pipelines/results'
import { createProcessAiEventStep } from './steps/process-ai-event-step'

export type { AiEventSubpipelineConfig, AiEventSubpipelineInput } from '~/ingestion/common/ai-subpipeline.contract'

export function createAiEventSubpipeline<TInput extends AiEventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: AiEventSubpipelineConfig
): PipelineBuilder<TInput, EmitEventStepOutput, TContext, AsyncOutput> {
    const { options, outputs, teamManager, groupTypeManager, hogTransformer, splitAiEventsConfig, topHog } = config

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
        .pipe(createProcessAiEventStep())
        .pipe(createProcessPersonlessStep(options.FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS))
        .pipe(
            topHog(createProcessPersonsStep(options, outputs), [
                timer('process_persons_time', (input) => ({
                    team_id: String(input.team.id),
                    distinct_id: input.normalizedEvent.distinct_id,
                })),
            ])
        )
        .pipe(createPrepareEventStep())
        .pipe(createProcessGroupsStep(teamManager, groupTypeManager, options))
        .pipe(createCreateEventStep(EVENTS_OUTPUT))
        .pipe(createSplitAiEventsStep(splitAiEventsConfig))
        .pipe(
            topHog(
                createEmitEventStep({
                    outputs,
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
        .pipe(createRecordIngestionLagStep())
}
