import { Message } from 'node-rdkafka'

import {
    createApplyCookielessProcessingStep,
    createApplyDropRestrictionsStep,
    createApplyForceOverflowRestrictionsStep,
    createApplyPersonProcessingRestrictionsStep,
    createDropExceptionEventsStep,
    createParseHeadersStep,
    createParseKafkaMessageStep,
    createResolveTeamStep,
    createValidateEventPropertiesStep,
    createValidateEventUuidStep,
} from '../ingestion/event-preprocessing'
import { createMapToPipelineEventStep } from '../ingestion/event-processing/map-to-pipeline-event-step'
import { BatchPipelineBuilder } from '../ingestion/pipelines/builders'
import { PipelineConfig } from '../ingestion/pipelines/result-handling-pipeline'
import { KafkaProducerWrapper } from '../kafka/producer'
import { Hub, IncomingEventWithTeam, Team } from '../types'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restriction-manager'
import { PromiseScheduler } from '../utils/promise-scheduler'

export type PreprocessingSubpipelineInput = { message: Message }
export type PreprocessingSubpipelineOutput = IncomingEventWithTeam
export type PreprocessingSubpipelineInputContext = { message: Message }
export type PreprocessingSubpipelineOutputContext = { message: Message; team: Team }

/**
 * Output type of the preprocessing subpipeline.
 * After all preprocessing steps, we output IncomingEventWithTeam.
 */
export type PreprocessedEvent = PreprocessingSubpipelineOutput

export interface PreprocessingSubpipelineConfig {
    hub: Hub
    kafkaProducer: KafkaProducerWrapper
    dlqTopic: string
    promiseScheduler: PromiseScheduler
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    preservePartitionLocality: boolean
}

/**
 * Adds preprocessing steps to a pipeline builder.
 * This subpipeline handles initial event validation and enrichment:
 * - Parses headers and kafka messages
 * - Applies drop restrictions
 * - Applies overflow restrictions
 * - Resolves team information
 * - Validates event properties and UUIDs
 * - Applies person processing restrictions
 * - Applies cookieless processing
 *
 * This is a composable subpipeline that can be reused across different ingestion pipelines.
 *
 * @param builder - The pipeline builder to add preprocessing steps to
 * @param config - Configuration for the preprocessing subpipeline
 * @returns A batch pipeline builder with preprocessing steps applied, outputting PreprocessedEvent with team in context
 */
export function applyPreprocessingSubpipeline<TContext extends PreprocessingSubpipelineInputContext>(
    builder: BatchPipelineBuilder<PreprocessingSubpipelineInput, PreprocessingSubpipelineInput, TContext, TContext>,
    config: PreprocessingSubpipelineConfig
): BatchPipelineBuilder<
    PreprocessingSubpipelineInput,
    PreprocessingSubpipelineOutput,
    TContext & { team: Team },
    TContext & { team: Team }
> {
    const pipelineConfig: PipelineConfig = {
        kafkaProducer: config.kafkaProducer,
        dlqTopic: config.dlqTopic,
        promiseScheduler: config.promiseScheduler,
    }

    return (
        builder
            .messageAware((b) =>
                // All of these steps are synchronous, so we can process the messages sequentially
                // to avoid buffering due to reordering.
                b.sequentially((seq) =>
                    seq
                        .pipe(createParseHeadersStep())
                        .pipe(createApplyDropRestrictionsStep(config.eventIngestionRestrictionManager))
                        .pipe(
                            createApplyForceOverflowRestrictionsStep(config.eventIngestionRestrictionManager, {
                                overflowEnabled: config.overflowEnabled,
                                overflowTopic: config.overflowTopic,
                                preservePartitionLocality: config.preservePartitionLocality,
                            })
                        )
                        .pipe(createParseKafkaMessageStep())
                        .pipe(createDropExceptionEventsStep())
                        .pipe(createResolveTeamStep(config.hub))
                )
            )
            // We want to handle the first batch of rejected events, so that the remaining ones
            // can be processed in the team context.
            .handleResults(pipelineConfig)
            // We don't need to block the pipeline with side effects at this stage.
            .handleSideEffects(config.promiseScheduler, { await: false })
            // This is the first synchronization point, where we gather all events.
            // We need to gather here because the pipeline consumer only calls next once.
            // Once we transition to a continuous consumer, we can remove this gather.
            .gather()
            .filterOk()
            // Now we know all messages are in the team context.
            .map((element) => ({
                result: element.result,
                context: {
                    ...element.context,
                    team: element.result.value.eventWithTeam.team,
                },
            }))
            .messageAware((b) =>
                b
                    .teamAware((team) =>
                        // These steps are also synchronous, so we can process events sequentially.
                        team
                            .sequentially((seq) =>
                                seq
                                    .pipe(createValidateEventPropertiesStep())
                                    .pipe(
                                        createApplyPersonProcessingRestrictionsStep(
                                            config.eventIngestionRestrictionManager
                                        )
                                    )
                                    .pipe(createValidateEventUuidStep())
                            )
                            // We want to call cookieless with the whole batch at once.
                            .gather()
                            .pipeBatch(createApplyCookielessProcessingStep(config.hub))
                            // Map to extract the eventWithTeam (which contains the PipelineEvent)
                            .sequentially((seq) => seq.pipe(createMapToPipelineEventStep()))
                    )
                    .handleIngestionWarnings(config.kafkaProducer)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(config.promiseScheduler, { await: false })
            // We synchronize once again to ensure we return all events in one batch.
            .gather()
    )
}
