import { Message } from 'node-rdkafka'

import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { createAllowEventsStep } from '../common/steps/allow-events'
import {
    EventFiltersBatchContext,
    createApplyEventFiltersStep,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '../common/steps/event-filters-steps'
import { addTeamToContext } from '../common/subpipelines/helpers'
import { CookielessManager } from '../cookieless/cookieless-manager'
import {
    createApplyCookielessProcessingStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { createApplyBasicEventRestrictionsStep } from '../event-preprocessing/apply-event-restrictions'
import { createDropOldEventsStep } from '../event-processing/drop-old-events-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
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

    const pipelineConfig: PipelineConfig = {
        outputs,
        promiseScheduler,
    }

    return newBatchingPipeline<TInput, void, TContext, EventFiltersBatchContext, TContext>(
        (beforeBatch) => beforeBatch.pipe(createEventFiltersBatchAppMetricsBeforeBatchStep(outputs)),
        (batch) =>
            batch
                .messageAware((b) =>
                    b
                        .sequentially((b) =>
                            b
                                .pipe(createParseHeadersStep())
                                .pipe(createAllowEventsStep(['$$heatmap']))
                                .pipe(createApplyBasicEventRestrictionsStep(eventIngestionRestrictionManager))
                                .pipe(createParseKafkaMessageStep())
                                .pipe(createResolveTeamStep(teamManager))
                                .pipe(createValidateHistoricalMigrationStep())
                        )
                        .filterMap(addTeamToContext, (b) =>
                            b
                                .teamAware((b) =>
                                    b
                                        .sequentially((b) =>
                                            b
                                                .pipe(createValidateEventMetadataStep())
                                                .pipe(createValidateEventPropertiesStep())
                                                .pipe(createApplyEventFiltersStep(eventFilterManager))
                                                .pipe(createDropOldEventsStep())
                                        )
                                        // Cookieless events arrive with a sentinel distinct id; rewrite it to the
                                        // deterministic server-side hash (and derive the session) before extraction,
                                        // which keys heatmaps on distinct id and session id.
                                        .gather()
                                        .pipeBatch(createApplyCookielessProcessingStep(cookielessManager))
                                        .sequentially((b) =>
                                            b
                                                .pipe(createCheckHeatmapOptInStep())
                                                .pipe(createDisablePersonProcessingStep())
                                                .pipe(createNormalizeEventStep())
                                                .pipe(createPrepareEventStep())
                                                .pipe(createExtractHeatmapDataStep(outputs))
                                        )
                                )
                                .handleIngestionWarnings(outputs)
                        )
                )
                .handleResults(pipelineConfig)
                .handleSideEffects(promiseScheduler, { await: false }),
        (afterBatch) => afterBatch.pipe(createFlushEventFiltersBatchAppMetricsStep()),
        { concurrentBatches: 1 }
    )
}
