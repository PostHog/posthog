import { Message } from 'node-rdkafka'

import { Team } from '../../types'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { DlqOutput, EVENTS_OUTPUT, EventOutput, IngestionWarningsOutput } from '../common/outputs'
import {
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateEventMetadataStep,
    createValidateEventPropertiesStep,
    createValidateHistoricalMigrationStep,
} from '../event-preprocessing'
import { createCreateEventStep } from '../event-processing/create-event-step'
import { createDropOldEventsStep } from '../event-processing/drop-old-events-step'
import { createEmitEventStep } from '../event-processing/emit-event-step'
import { createNormalizeEventStep } from '../event-processing/normalize-event-step'
import { createNormalizeProcessPersonFlagStep } from '../event-processing/normalize-process-person-flag-step'
import { createPrepareEventStep } from '../event-processing/prepare-event-step'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { newBatchingPipeline } from '../pipelines/builders'
import { OkResultWithContext } from '../pipelines/pipeline.interface'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'

export interface AnalyticsPipelineConfig {
    outputs: IngestionOutputs<EventOutput | DlqOutput | IngestionWarningsOutput>
    teamManager: TeamManager
    promiseScheduler: PromiseScheduler
    groupId: string
}

interface AnalyticsPipelineInput {
    message: Message
}

interface AnalyticsPipelineContext {
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

/**
 * Top-level analytics ingestion pipeline (prototype).
 *
 * Demonstrates the builder-driven analytics consumer. Compared to the production
 * `joined-ingestion-pipeline`, this prototype omits person processing, group
 * processing, hog transformations, overflow redirection, and split-AI handling.
 * Events are parsed, validated, normalized, prepared, created, and emitted to
 * `EVENTS_OUTPUT`. DLQ and ingestion warnings are wired through the standard
 * result handling.
 *
 * Wiring those subsystems into a builder-driven analytics consumer is intentionally
 * out of scope here — each requires registering more managed services (persons
 * store, group store, hog transformer, overflow redirect) and the existing
 * service classes need explicit lifecycle methods first.
 */
export function createAnalyticsPipeline<
    TInput extends AnalyticsPipelineInput,
    TContext extends AnalyticsPipelineContext,
>(config: AnalyticsPipelineConfig) {
    const { outputs, teamManager, promiseScheduler, groupId } = config

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
                                            .pipe(createNormalizeProcessPersonFlagStep())
                                            .pipe(createNormalizeEventStep())
                                            .pipe(createPrepareEventStep())
                                            .pipe(createCreateEventStep(EVENTS_OUTPUT))
                                            .pipe(createEmitEventStep({ outputs, groupId }))
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
