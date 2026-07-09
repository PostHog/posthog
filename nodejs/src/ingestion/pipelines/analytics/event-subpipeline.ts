import { Message } from 'node-rdkafka'

import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { TeamManager } from '~/common/utils/team-manager'
import { GroupStoreForBatch } from '~/ingestion/common/groups/group-store-for-batch'
import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { createCreateEventStep } from '~/ingestion/common/steps/event-processing/create-event-step'
import { EmitEventStepOutput, createEmitEventStep } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { EventPipelineRunnerOptions } from '~/ingestion/common/steps/event-processing/event-pipeline-options'
import { createHogTransformEventStep } from '~/ingestion/common/steps/event-processing/hog-transform-event-step'
import { createNormalizeEventStep } from '~/ingestion/common/steps/event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '~/ingestion/common/steps/event-processing/normalize-process-person-flag-step'
import { createPrepareEventStep } from '~/ingestion/common/steps/event-processing/prepare-event-step'
import { createProcessGroupsStep } from '~/ingestion/common/steps/event-processing/process-groups-step'
import { createProcessPersonlessStep } from '~/ingestion/common/steps/event-processing/process-personless-step'
import { createProcessPersonsStep } from '~/ingestion/common/steps/event-processing/process-persons-step'
import { createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'
import { PipelineBuilder, StartPipelineBuilder } from '~/ingestion/framework/builders/pipeline-builders'
import { TopHogWrapper, sum, sumOk, sumResult, timer } from '~/ingestion/framework/extensions/tophog'
import { isDropResult } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, Team } from '~/types'

import {
    AsyncOutput,
    EVENTS_OUTPUT,
    EventOutput,
    PersonDistinctIdsOutput,
    PersonMergeEventsOutput,
    PersonsOutput,
} from './outputs'

// Mirrors the merge condition in PersonMergeService.handleIdentifyOrAlias: an event asks for a person
// merge when it's $create_alias/$merge_dangerously with an `alias`, or $identify with $anon_distinct_id.
// Kept in the metrics layer so counting merge-intent events doesn't reach into person processing logic.
function isMergeIntentEvent(event: PluginEvent): boolean {
    const properties = event.properties ?? {}
    if (['$create_alias', '$merge_dangerously'].includes(event.event) && properties['alias']) {
        return true
    }
    return event.event === '$identify' && '$anon_distinct_id' in properties
}

export interface EventSubpipelineInput {
    message: Message
    event: PluginEvent
    team: Team
    headers: EventHeaders
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
}

export interface EventSubpipelineConfig {
    options: EventPipelineRunnerOptions
    outputs: IngestionOutputs<
        EventOutput | IngestionWarningsOutput | PersonsOutput | PersonDistinctIdsOutput | PersonMergeEventsOutput
    >
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    hogTransformer: HogTransformer
    topHog: TopHogWrapper
}

export function createEventSubpipeline<TInput extends EventSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: EventSubpipelineConfig
): PipelineBuilder<TInput, EmitEventStepOutput, TContext, AsyncOutput> {
    const { options, outputs, teamManager, groupTypeManager, hogTransformer, topHog } = config

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
            ]),
            { retry: { tries: 5, sleepMs: 100, name: 'hog_transform_event' } }
        )
        .pipe(createNormalizeEventStep())
        .pipe(createProcessPersonlessStep(options.FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS), {
            retry: { tries: 5, sleepMs: 100, name: 'process_personless' },
        })
        .pipe(
            topHog(createProcessPersonsStep(options, outputs), [
                timer('process_persons_time', (input) => ({
                    team_id: String(input.team.id),
                    distinct_id: input.normalizedEvent.distinct_id,
                    partition: String(input.message.partition),
                })),
                sum(
                    'merge_events_per_distinct_id',
                    (input) => ({
                        team_id: String(input.team.id),
                        distinct_id: input.normalizedEvent.distinct_id,
                        partition: String(input.message.partition),
                    }),
                    (input) => (isMergeIntentEvent(input.normalizedEvent) ? 1 : 0)
                ),
                sum(
                    'group_identify_events_per_distinct_id',
                    (input) => ({
                        team_id: String(input.team.id),
                        distinct_id: input.normalizedEvent.distinct_id,
                        partition: String(input.message.partition),
                    }),
                    (input) => (input.normalizedEvent.event === '$groupidentify' ? 1 : 0)
                ),
            ]),
            { retry: { tries: 5, sleepMs: 100, name: 'process_persons' } }
        )
        .pipe(createPrepareEventStep())
        .pipe(createProcessGroupsStep(teamManager, groupTypeManager, options), {
            retry: { tries: 5, sleepMs: 100, name: 'process_groups' },
        })
        .pipe(createCreateEventStep(EVENTS_OUTPUT))
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
            ),
            { retry: { tries: 5, sleepMs: 100, name: 'emit_event' } }
        )
        .pipe(createRecordIngestionLagStep())
}
