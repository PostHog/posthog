import { PluginEvent } from '~/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { HeatmapsOutput } from '../analytics/outputs'
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

export interface HeatmapSubpipelineInput {
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

/**
 * The subset of event pipeline options the heatmap chain reads. Only
 * `processGroupsStep` consults `SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP`;
 * `processPersonsStep` (which uses the full options shape) doesn't run here.
 */
export type HeatmapEventOptions = Pick<EventPipelineRunnerOptions, 'SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP'>

export interface HeatmapSubpipelineConfig {
    options: HeatmapEventOptions
    outputs: IngestionOutputs<HeatmapsOutput>
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    groupStore: BatchWritingGroupStore
}

export function createHeatmapSubpipeline<TInput extends HeatmapSubpipelineInput, TContext>(
    builder: StartPipelineBuilder<TInput, TContext>,
    config: HeatmapSubpipelineConfig
): PipelineBuilder<TInput, void, TContext> {
    const { options, outputs, teamManager, groupTypeManager, groupStore } = config

    return builder
        .pipe(createCheckHeatmapOptInStep())
        .pipe(createDisablePersonProcessingStep())
        .pipe(createNormalizeEventStep())
        .pipe(createPrepareEventStep())
        .pipe(createProcessGroupsStep(teamManager, groupTypeManager, groupStore, options))
        .pipe(createExtractHeatmapDataStep(outputs))
        .pipe(createSkipEmitEventStep())
}
