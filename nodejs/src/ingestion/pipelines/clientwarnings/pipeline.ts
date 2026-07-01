import { Message } from 'node-rdkafka'

import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { EventFilterManager } from '~/ingestion/common/event-filters'
import { createAllowEventsStep } from '~/ingestion/common/steps/allow-events'
import {
    EventFiltersBatchContext,
    createApplyEventFiltersStep,
    createEventFiltersBatchAppMetricsBeforeBatchStep,
    createFlushEventFiltersBatchAppMetricsStep,
} from '~/ingestion/common/steps/event-filters-steps'
import {
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateHistoricalMigrationStep,
} from '~/ingestion/common/steps/event-preprocessing'
import { createApplyBasicEventRestrictionsStep } from '~/ingestion/common/steps/event-preprocessing/apply-event-restrictions'
import { createDropOldEventsStep } from '~/ingestion/common/steps/event-processing/drop-old-events-step'
import { EmitEventStepOutput } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { createHandleClientIngestionWarningStep } from '~/ingestion/common/steps/event-processing/handle-client-ingestion-warning-step'
import { createRecordIngestionLagStep } from '~/ingestion/common/steps/record-ingestion-lag'
import { addTeamToContext } from '~/ingestion/common/subpipelines/helpers'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'

export interface ClientWarningsPipelineConfig {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput | AppMetricsOutput>
    teamManager: TeamManager
    // The managers come from a started `Lifecycle`'s service map, where
    // `start` and `stop` are stripped from the type — the pipeline only
    // needs their business methods.
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventFilterManager: EventFilterManager
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

    return newBatchingPipeline<TInput, EmitEventStepOutput, TContext, EventFiltersBatchContext, TContext>(
        (beforeBatch) => beforeBatch.pipe(createEventFiltersBatchAppMetricsBeforeBatchStep(outputs)),
        (batch) =>
            batch
                .messageAware((b) =>
                    b
                        .sequentially((b) =>
                            b
                                .pipe(createParseHeadersStep())
                                .pipe(createAllowEventsStep(['$$client_ingestion_warning']))
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
                                            .pipe(createHandleClientIngestionWarningStep(outputs))
                                            .pipe(createRecordIngestionLagStep())
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
