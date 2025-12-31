import { Message } from 'node-rdkafka'

import { processPersonlessDistinctIdsBatchStep } from '~/worker/ingestion/event-pipeline/processPersonlessDistinctIdsBatchStep'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { prefetchPersonsStep } from '../../worker/ingestion/event-pipeline/prefetchPersonsStep'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { createApplyCookielessProcessingStep, createRateLimitToOverflowStep } from '../event-preprocessing'
import { createPrefetchHogFunctionsStep } from '../event-processing/prefetch-hog-functions-step'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { MemoryRateLimiter } from '../utils/overflow-detector'
import { createPostTeamPreprocessingSubpipeline } from './post-team-preprocessing-subpipeline'
import { createPreTeamPreprocessingSubpipeline } from './pre-team-preprocessing-subpipeline'

export type PreprocessingHub = Pick<
    Hub,
    | 'teamManager'
    | 'cookielessManager'
    | 'INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY'
    | 'PERSONS_PREFETCH_ENABLED'
    | 'CDP_HOG_WATCHER_SAMPLE_RATE'
>

export interface PreprocessingPipelineConfig {
    hub: PreprocessingHub
    kafkaProducer: KafkaProducerWrapper
    personsStore: PersonsStore
    hogTransformer: HogTransformerService
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowRateLimiter: MemoryRateLimiter
    overflowEnabled: boolean
    overflowTopic: string
    dlqTopic: string
    promiseScheduler: PromiseScheduler
}

export interface PreprocessingPipelineInput {
    message: Message
}

export interface PreprocessingPipelineContext {
    message: Message
}

export function createPreprocessingPipeline<
    TInput extends PreprocessingPipelineInput,
    TContext extends PreprocessingPipelineContext,
>(builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>, config: PreprocessingPipelineConfig) {
    const {
        hub,
        kafkaProducer,
        personsStore,
        hogTransformer,
        eventIngestionRestrictionManager,
        overflowRateLimiter,
        overflowEnabled,
        overflowTopic,
        dlqTopic,
        promiseScheduler,
    } = config

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    return (
        builder
            .messageAware((b) =>
                // All of these steps are synchronous, so we can process the messages sequentially
                // to avoid buffering due to reordering.
                b.sequentially((b) =>
                    createPreTeamPreprocessingSubpipeline(b, {
                        teamManager: hub.teamManager,
                        eventIngestionRestrictionManager,
                        overflowEnabled,
                        overflowTopic,
                        preservePartitionLocality: hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
                    })
                )
            )
            // We want to handle the first batch of rejected events, so that the remaining ones
            // can be processed in the team context.
            .handleResults(pipelineConfig)
            // We don't need to block the pipeline with side effects at this stage.
            .handleSideEffects(promiseScheduler, { await: false })
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
                    team: element.result.value.team,
                },
            }))
            .messageAware((b) =>
                b
                    .teamAware((b) =>
                        // These steps are also synchronous, so we can process events sequentially.
                        b
                            .sequentially((b) =>
                                createPostTeamPreprocessingSubpipeline(b, {
                                    eventIngestionRestrictionManager,
                                })
                            )
                            // We want to call cookieless with the whole batch at once.
                            // IMPORTANT: Cookieless processing changes distinct IDs (cookieless events
                            // are captured with $posthog_cookieless distinct ID and rewritten here).
                            // Any steps that depend on the final distinct ID must run after this step.
                            .gather()
                            .pipeBatch(createApplyCookielessProcessingStep(hub.cookielessManager))
                            // Rate limit to overflow must run after cookieless, as it uses the final distinct ID
                            .pipeBatch(
                                createRateLimitToOverflowStep(
                                    overflowRateLimiter,
                                    overflowEnabled,
                                    overflowTopic,
                                    hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY
                                )
                            )
                            // Prefetch must run after cookieless, as cookieless changes distinct IDs
                            .pipeBatch(prefetchPersonsStep(personsStore, hub.PERSONS_PREFETCH_ENABLED))
                            // Batch insert personless distinct IDs after prefetch (uses prefetch cache)
                            .pipeBatch(
                                processPersonlessDistinctIdsBatchStep(personsStore, hub.PERSONS_PREFETCH_ENABLED)
                            )
                            // Prefetch hog functions for all teams in the batch
                            .pipeBatch(createPrefetchHogFunctionsStep(hogTransformer, hub.CDP_HOG_WATCHER_SAMPLE_RATE))
                    )
                    .handleIngestionWarnings(kafkaProducer)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: false })
            // We synchronize once again to ensure we return all events in one batch.
            .gather()
    )
}
