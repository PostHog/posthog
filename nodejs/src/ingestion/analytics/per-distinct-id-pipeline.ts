import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { BatchStores } from '../event-processing/flush-batch-stores-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { TopHogWrapper } from '../pipelines/extensions/tophog'
import {
    ClientIngestionWarningSubpipelineInput,
    createClientIngestionWarningSubpipeline,
} from './client-ingestion-warning-subpipeline'
import { EventSubpipelineInput, createEventSubpipeline } from './event-subpipeline'
import { HeatmapSubpipelineInput, createHeatmapSubpipeline } from './heatmap-subpipeline'

export type PerDistinctIdPipelineInput = EventSubpipelineInput &
    HeatmapSubpipelineInput &
    ClientIngestionWarningSubpipelineInput

export interface PerDistinctIdPipelineConfig {
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

export interface PerDistinctIdPipelineContext {
    message: Message
    team: Team
}

type EventBranch = 'client_ingestion_warning' | 'heatmap' | 'event'

function classifyEvent(input: PerDistinctIdPipelineInput): EventBranch {
    switch (input.event.event) {
        case '$$client_ingestion_warning':
            return 'client_ingestion_warning'
        case '$$heatmap':
            return 'heatmap'
        default:
            return 'event'
    }
}

export function createPerDistinctIdPipeline<TInput extends PerDistinctIdPipelineInput & BatchStores, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: PerDistinctIdPipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, teamManager, groupTypeManager, hogTransformer, groupId, topHog } = config

    return builder.retry(
        (e) =>
            e.branching<EventBranch, void>(classifyEvent, (branches) => {
                branches
                    .branch('client_ingestion_warning', (b) => createClientIngestionWarningSubpipeline(b))
                    .branch('heatmap', (b) =>
                        createHeatmapSubpipeline(b, {
                            options,
                            teamManager,
                            groupTypeManager,
                        })
                    )
                    .branch('event', (b) =>
                        createEventSubpipeline(b, {
                            options,
                            teamManager,
                            groupTypeManager,
                            hogTransformer,
                            groupId,
                            topHog,
                        })
                    )
            }),
        { tries: 3, sleepMs: 100 }
    )
}
