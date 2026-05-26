import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManagerHandle } from '../../utils/team-manager'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { addTeamToContext } from '../common/subpipelines/helpers'
import {
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { createDropOldEventsStep } from '../event-processing/drop-old-events-step'
import { createHandleClientIngestionWarningStep } from '../event-processing/handle-client-ingestion-warning-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'

export interface ClientWarningsPipelineConfig {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput>
    teamManager: TeamManagerHandle
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
    const { outputs, teamManager, promiseScheduler } = config

    const pipelineConfig: PipelineConfig = {
        outputs,
        promiseScheduler,
    }

    return newBatchingPipeline<TInput, void, TContext>(
        (beforeBatch) => beforeBatch.pipe(({ elements }) => Promise.resolve(ok({ elements, batchContext: {} }))),
        (batch) =>
            batch
                .messageAware((b) =>
                    b
                        .sequentially((b) =>
                            b
                                .pipe(createParseHeadersStep())
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
                                            .pipe(createDropOldEventsStep())
                                            .pipe(createHandleClientIngestionWarningStep())
                                    )
                                )
                                .handleIngestionWarnings(outputs)
                        )
                )
                .handleResults(pipelineConfig)
                .handleSideEffects(promiseScheduler, { await: false }),
        (afterBatch) => afterBatch.pipe(({ elements }) => Promise.resolve(ok({ elements, batchContext: {} }))),
        { concurrentBatches: 1 }
    )
}
