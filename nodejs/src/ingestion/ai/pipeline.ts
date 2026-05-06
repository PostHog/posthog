import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { addTeamToContext } from '../common/subpipelines/helpers'
import {
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '../event-processing/normalize-process-person-flag-step'
import { createSkipEmitEventStep } from '../event-processing/skip-emit-event-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'
import { createProcessAiEventStep } from './pipelines/steps/process-ai-event-step'

export interface AiPipelineConfig {
    outputs: IngestionOutputs<DlqOutput | IngestionWarningsOutput>
    teamManager: TeamManager
    promiseScheduler: PromiseScheduler
}

interface AiPipelineInput {
    message: Message
}

interface AiPipelineContext {
    message: Message
}

/**
 * Top-level AI ingestion pipeline.
 *
 * This is the prototype consumer-facing pipeline. It does pre-team preprocessing,
 * runs `processAiEventStep` to enrich AI events (and DLQ non-AI events), and drops
 * the event at the end. A production AI consumer would replace `createSkipEmitEventStep`
 * with a real emit step into the AI events output topic, similar to
 * `ai-event-subpipeline.ts`.
 */
export function createAiPipeline<TInput extends AiPipelineInput, TContext extends AiPipelineContext>(
    config: AiPipelineConfig
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
                                            .pipe(createNormalizeProcessPersonFlagStep())
                                            .pipe(createNormalizeEventStep())
                                            .pipe(createProcessAiEventStep())
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
