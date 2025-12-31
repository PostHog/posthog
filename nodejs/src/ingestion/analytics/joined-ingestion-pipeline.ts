import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { PipelineEvent } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'
import { OkResultWithContext } from '../pipelines/filter-ok-batch-pipeline'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'
import { MemoryRateLimiter } from '../utils/overflow-detector'
import { PerEventProcessingConfig, PerEventProcessingInput } from './per-event-processing-subpipeline'
import { createPerEventProcessingSubpipeline } from './per-event-processing-subpipeline'
import { PostTeamPreprocessingSubpipelineInput } from './post-team-preprocessing-subpipeline'
import { PreprocessingHub, PreprocessingPipelineConfig, createPreprocessingPipeline } from './preprocessing-pipeline'

export interface JoinedIngestionPipelineConfig {
    // Preprocessing config
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

    // Per-distinct-id config
    perDistinctIdOptions: EventPipelineRunnerOptions & {
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: string
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    groupId: string
}

export interface JoinedIngestionPipelineInput {
    message: Message
    groupStoreForBatch: GroupStoreForBatch
}

export interface JoinedIngestionPipelineContext {
    message: Message
}

type PreprocessedEventWithGroupStore = PostTeamPreprocessingSubpipelineInput & {
    groupStoreForBatch: GroupStoreForBatch
}

function getTokenAndDistinctId(input: PerEventProcessingInput): string {
    const token = input.event.token ?? ''
    const distinctId = input.event.distinct_id ?? ''
    return `${token}:${distinctId}`
}

function mapToPerEventInput<C>(
    element: OkResultWithContext<PreprocessedEventWithGroupStore, C>
): OkResultWithContext<PerEventProcessingInput, C> {
    const input = element.result.value
    return {
        result: ok({
            message: input.eventWithTeam.message,
            event: input.eventWithTeam.event as PipelineEvent,
            team: input.team,
            headers: input.headers,
            groupStoreForBatch: input.groupStoreForBatch,
        }),
        context: element.context,
    }
}

export function createJoinedIngestionPipeline<
    TInput extends JoinedIngestionPipelineInput,
    TContext extends JoinedIngestionPipelineContext,
>(builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>, config: JoinedIngestionPipelineConfig) {
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
        perDistinctIdOptions,
        teamManager,
        groupTypeManager,
        groupId,
    } = config

    const preprocessingConfig: PreprocessingPipelineConfig = {
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
    }

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    const perEventConfig: PerEventProcessingConfig = {
        options: perDistinctIdOptions,
        teamManager,
        groupTypeManager,
        hogTransformer,
        personsStore,
        kafkaProducer,
        groupId,
    }

    return (
        createPreprocessingPipeline(builder, preprocessingConfig)
            // Filter to OK results only - preprocessing already handled DLQ, REDIRECT, etc.
            .filterOk()
            .map(mapToPerEventInput)
            .messageAware((b) =>
                b
                    .teamAware((b) =>
                        b
                            // Group by token:distinctId and process each group concurrently
                            // Events within each group are processed sequentially
                            .groupBy(getTokenAndDistinctId)
                            .concurrently((eventsForDistinctId) =>
                                eventsForDistinctId.sequentially((event) =>
                                    createPerEventProcessingSubpipeline(event, perEventConfig)
                                )
                            )
                            .gather()
                    )
                    .handleIngestionWarnings(kafkaProducer)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(promiseScheduler, { await: false })
            .gather()
    )
}
