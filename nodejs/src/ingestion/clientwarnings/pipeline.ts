import { Message } from 'node-rdkafka'

import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import {
    EventFiltersBatchContext,
    createApplyEventFiltersStep,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '../common/steps/event-filters-steps'
import { addTeamToContext } from '../common/subpipelines/helpers'
import {
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { createApplyBasicEventRestrictionsStep } from '../event-preprocessing/apply-event-restrictions'
import { createDropOldEventsStep } from '../event-processing/drop-old-events-step'
import { createHandleClientIngestionWarningStep } from '../event-processing/handle-client-ingestion-warning-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'

export interface ClientWarningsPipelineConfig {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput | AppMetricsOutput>
    teamManager: TeamManager
    // The managers come from a started `Lifecycle`'s service map, where
    // `start` and `stop` are stripped from the type — the pipeline only
    // needs their business methods.
    eventIngestionRestrictionManager: Omit<EventIngestionRestrictionManager, 'start' | 'stop'>
    eventFilterManager: Omit<EventFilterManager, 'start' | 'stop'>
    promiseScheduler: PromiseScheduler
}

interface ClientWarningsPipelineInput {
    message: Message
}

interface ClientWarningsPipelineContext {
    message: Message
}

export function createClientWarningsPipeline<
    TInput extends ClientWarningsPipelineInput,
    TContext extends ClientWarningsPipelineContext,
>(config: ClientWarningsPipelineConfig) {
    const { outputs, teamManager, eventIngestionRestrictionManager, eventFilterManager, promiseScheduler } = config

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
                                .pipe(createApplyBasicEventRestrictionsStep(eventIngestionRestrictionManager))
                                .pipe(createParseKafkaMessageStep())
                                .pipe(createResolveTeamStep(teamManager))
                                .pipe(createValidateHistoricalMigrationStep())
                        )
                        .filterMap(addTeamToContext, (b) =>
                            b
                                .teamAware((b) =>
                                    b.sequentially((b) =>
                                        b
                                            .pipe(createValidateEventMetadataStep())
                                            .pipe(createValidateEventPropertiesStep())
                                            .pipe(createApplyEventFiltersStep(eventFilterManager))
                                            .pipe(createDropOldEventsStep())
                                            .pipe(createHandleClientIngestionWarningStep())
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
