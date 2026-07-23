import { Message } from 'node-rdkafka'

import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { newCommonIngestionPipeline } from '~/ingestion/common/common-ingestion-pipeline'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { createAllowEventsStep } from '~/ingestion/common/steps/allow-events'
import {
    createApplyEventFiltersStep,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '~/ingestion/common/steps/event-filters-steps'
import {
    createApplyCookielessProcessingStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateHistoricalMigrationStep,
} from '~/ingestion/common/steps/event-preprocessing'
import { createApplyBasicEventRestrictionsStep } from '~/ingestion/common/steps/event-preprocessing/apply-event-restrictions'
import { createDropOldEventsStep } from '~/ingestion/common/steps/event-processing/drop-old-events-step'
import { createNormalizeEventStep } from '~/ingestion/common/steps/event-processing/normalize-event-step'
import { createPrepareEventStep } from '~/ingestion/common/steps/event-processing/prepare-event-step'
import { createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'

import { createCheckHeatmapOptInStep } from './check-heatmap-opt-in-step'
import { createDisablePersonProcessingStep } from './disable-person-processing-step'
import { createExtractHeatmapDataStep } from './extract-heatmap-data-step'
import { HeatmapsOutput } from './outputs'

export interface HeatmapsPipelineConfig {
    outputs: IngestionOutputs<HeatmapsOutput | IngestionWarningsOutput | DlqOutput | AppMetricsOutput>
    teamManager: TeamManager
    // The managers come from a started `Lifecycle`'s service map, where
    // `start` and `stop` are stripped from the type — the pipeline only
    // needs their business methods.
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventFilterManager: EventFilterManager
    cookielessManager: CookielessManager
    promiseScheduler: PromiseScheduler
}

interface HeatmapsPipelineInput {
    message: Message
}

interface HeatmapsPipelineContext {
    message: Message
}

export function createHeatmapsPipeline<TInput extends HeatmapsPipelineInput, TContext extends HeatmapsPipelineContext>(
    config: HeatmapsPipelineConfig
) {
    const {
        outputs,
        teamManager,
        eventIngestionRestrictionManager,
        eventFilterManager,
        cookielessManager,
        promiseScheduler,
    } = config

    return (
        newCommonIngestionPipeline<TInput, TContext>({
            teamManager,
            outputs,
            promiseScheduler,
            concurrentBatches: 1,
        })
            .beforeBatch((b) => b.pipe(createEventFiltersBatchAppMetricsBeforeBatchStep(outputs)))
            .parseHeaders()
            .pipe(createAllowEventsStep(['$$heatmap']))
            .pipe(createApplyBasicEventRestrictionsStep(eventIngestionRestrictionManager))
            .parseMessage()
            .resolveTeam()
            .pipe(createValidateHistoricalMigrationStep())
            .pipe(createValidateEventMetadataStep())
            .pipe(createValidateEventPropertiesStep())
            .pipe(createApplyEventFiltersStep(eventFilterManager))
            .pipe(createDropOldEventsStep())
            // Cookieless events arrive with a sentinel distinct id; rewrite it to the
            // deterministic server-side hash (and derive the session) before extraction,
            // which keys heatmaps on distinct id and session id.
            .gather()
            .pipeChunk(createApplyCookielessProcessingStep(cookielessManager))
            .pipe(createCheckHeatmapOptInStep())
            .pipe(createDisablePersonProcessingStep())
            .pipe(createNormalizeEventStep())
            .pipe(createPrepareEventStep())
            .pipe(createExtractHeatmapDataStep(outputs))
            .pipe(createRecordIngestionLagStep())
            .afterBatch((b) => b.pipe(createFlushEventFiltersBatchAppMetricsStep()))
            .build()
    )
}
