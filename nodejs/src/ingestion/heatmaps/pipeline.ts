import { Message } from 'node-rdkafka'

import { Team } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { HeatmapsOutput } from '../analytics/outputs'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import {
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { createCheckHeatmapOptInStep } from '../event-processing/check-heatmap-opt-in-step'
import { createDisablePersonProcessingStep } from '../event-processing/disable-person-processing-step'
import { createExtractHeatmapDataStep } from '../event-processing/extract-heatmap-data-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { createSkipEmitEventStep } from '../event-processing/skip-emit-event-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { OkResultWithContext } from '../pipelines/pipeline.interface'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'

export interface HeatmapsPipelineConfig {
    outputs: IngestionOutputs<HeatmapsOutput | DlqOutput | IngestionWarningsOutput>
    teamManager: TeamManager
    promiseScheduler: PromiseScheduler
}

interface HeatmapsPipelineInput {
    message: Message
}

interface HeatmapsPipelineContext {
    message: Message
}

function addTeamToContext<T extends { team: Team }, C>(
    element: OkResultWithContext<T, C>
): OkResultWithContext<T, C & { team: Team }> {
    return {
        result: element.result,
        context: {
            ...element.context,
            team: element.result.value.team,
        },
    }
}

export function createHeatmapsPipeline<TInput extends HeatmapsPipelineInput, TContext extends HeatmapsPipelineContext>(
    config: HeatmapsPipelineConfig
) {
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
                                            .pipe(createCheckHeatmapOptInStep())
                                            .pipe(createDisablePersonProcessingStep())
                                            .pipe(createNormalizeEventStep())
                                            .pipe(createPrepareEventStep())
                                            .pipe(createExtractHeatmapDataStep(outputs))
                                            .pipe(createSkipEmitEventStep())
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
