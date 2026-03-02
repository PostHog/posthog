import { Message } from 'node-rdkafka'

import { PluginEvent } from '~/plugin-scaffold'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventHeaders, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { BatchStores } from '../event-processing/flush-batch-stores-step'
import { createHogTransformEventStep } from '../event-processing/hog-transform-event-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '../event-processing/normalize-process-person-flag-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { createProcessPersonlessStep } from '../event-processing/process-personless-step'
import { createProcessPersonsStep } from '../event-processing/process-persons-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { TopHogWrapper, count, timer } from '../pipelines/extensions/tophog'

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
    groupId: string
    topHog: TopHogWrapper
}

export function createEventSubpipeline<TInput extends EventSubpipelineInput & BatchStores, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: EventSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, teamManager, groupTypeManager, hogTransformer, groupId, topHog } = config

    return builder
        .pipe(createNormalizeProcessPersonFlagStep())
        .pipe(createHogTransformEventStep(hogTransformer))
        .pipe(createNormalizeEventStep())
        .pipe(createProcessPersonlessStep())
        .pipe(
            topHog(createProcessPersonsStep(options), [
                timer('process_persons_time', (input) => ({
                    team_id: String(input.team.id),
                    distinct_id: input.normalizedEvent.distinct_id,
                })),
            ])
        )
        .pipe(createPrepareEventStep(teamManager, groupTypeManager, options))
        .pipe(
            createExtractHeatmapDataStep({
                CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: options.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
            })
        )
        .pipe(createCreateEventStep())
        .pipe(
            topHog(
                createEmitEventStep({
                    clickhouseJsonEventsTopic: options.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                    groupId,
                }),
                [
                    count('emitted_events', (input) => ({ team_id: String(input.eventToEmit.team_id) })),
                    count('emitted_events_per_distinct_id', (input) => ({
                        team_id: String(input.eventToEmit.team_id),
                        distinct_id: input.eventToEmit.distinct_id,
                    })),
                ]
            )
        )
}
