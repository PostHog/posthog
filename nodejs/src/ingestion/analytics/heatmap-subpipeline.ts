import { PluginEvent } from '~/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch'
import { createCheckHeatmapOptInStep } from '../event-processing/check-heatmap-opt-in-step'
import { createDisablePersonProcessingStep } from '../event-processing/disable-person-processing-step'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { createProcessGroupsStep } from '../event-processing/process-groups-step'
import { createSkipEmitEventStep } from '../event-processing/skip-emit-event-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'
import { HeatmapsOutput } from './outputs'

export interface HeatmapSubpipelineInput {
    event: PluginEvent
    team: Team
    headers: EventHeaders
    groupStoreForBatch: GroupStoreForBatch
}

export interface HeatmapSubpipelineConfig {
    options: EventPipelineRunnerOptions
    outputs: IngestionOutputs<HeatmapsOutput>
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
}

export function createHeatmapSubpipeline<TInput extends HeatmapSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: HeatmapSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, outputs, teamManager, groupTypeManager } = config

    return builder
        .pipe(createCheckHeatmapOptInStep())
        .pipe(createDisablePersonProcessingStep())
        .pipe(createNormalizeEventStep())
        .pipe(createPrepareEventStep())
        .pipe(createProcessGroupsStep(teamManager, groupTypeManager, options))
        .pipe(createExtractHeatmapDataStep(outputs))
        .pipe(createSkipEmitEventStep())
}
