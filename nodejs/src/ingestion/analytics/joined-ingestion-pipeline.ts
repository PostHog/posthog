import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub, Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { EventPipelineRunnerOptions } from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { createFlushBatchStoresStep } from '../event-processing/flush-batch-stores-step'
import { BatchPipelineBuilder } from '../pipelines/builders/batch-pipeline-builders'
import { OkResultWithContext } from '../pipelines/filter-map-batch-pipeline'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
import { ok } from '../pipelines/results'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import {
    PerDistinctIdPipelineConfig,
    PerDistinctIdPipelineInput,
    createPerDistinctIdPipeline,
} from './per-distinct-id-pipeline'
import {
    PostTeamPreprocessingSubpipelineConfig,
    PostTeamPreprocessingSubpipelineInput,
    createPostTeamPreprocessingSubpipeline,
} from './post-team-preprocessing-subpipeline'
import { createPreTeamPreprocessingSubpipeline } from './pre-team-preprocessing-subpipeline'

export type PreprocessingHub = Pick<
    Hub,
    | 'teamManager'
    | 'cookielessManager'
    | 'INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY'
    | 'PERSONS_PREFETCH_ENABLED'
    | 'CDP_HOG_WATCHER_SAMPLE_RATE'
>

export interface JoinedIngestionPipelineConfig {
    hub: PreprocessingHub
    kafkaProducer: KafkaProducerWrapper
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    hogTransformer: HogTransformerService
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    overflowEnabled: boolean
    overflowTopic: string
    dlqTopic: string
    promiseScheduler: PromiseScheduler
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService

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
}

export interface JoinedIngestionPipelineContext {
    message: Message
}

type PreprocessingOutput = PostTeamPreprocessingSubpipelineInput

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

function getTokenAndDistinctId(input: PerDistinctIdPipelineInput): string {
    const token = input.headers.token ?? ''
    const distinctId = input.event.distinct_id ?? ''
    return `${token}:${distinctId}`
}

function mapToPerEventInput<C>(
    element: OkResultWithContext<PreprocessingOutput, C>
): OkResultWithContext<PerDistinctIdPipelineInput, C> {
    const input = element.result.value
    return {
        result: ok({
            message: input.message,
            event: input.event,
            team: input.team,
            headers: input.headers,
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
        groupStore,
        hogTransformer,
        eventIngestionRestrictionManager,
        overflowEnabled,
        overflowTopic,
        dlqTopic,
        promiseScheduler,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        perDistinctIdOptions,
        teamManager,
        groupTypeManager,
        groupId,
    } = config

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    const postTeamConfig: PostTeamPreprocessingSubpipelineConfig = {
        eventIngestionRestrictionManager,
        cookielessManager: hub.cookielessManager,
        overflowTopic,
        preservePartitionLocality: hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        personsStore,
        personsPrefetchEnabled: hub.PERSONS_PREFETCH_ENABLED,
        hogTransformer,
        cdpHogWatcherSampleRate: hub.CDP_HOG_WATCHER_SAMPLE_RATE,
    }

    const perEventConfig: PerDistinctIdPipelineConfig = {
        options: perDistinctIdOptions,
        teamManager,
        groupTypeManager,
        hogTransformer,
        personsStore,
        groupStore,
        kafkaProducer,
        groupId,
    }

    return builder
        .messageAware((b) =>
            b
                .sequentially((b) =>
                    createPreTeamPreprocessingSubpipeline(b, {
                        teamManager: hub.teamManager,
                        eventIngestionRestrictionManager,
                        overflowEnabled,
                        overflowTopic,
                        preservePartitionLocality: hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
                    })
                )
                .filterMap(addTeamToContext, (b) =>
                    b
                        .teamAware((b) =>
                            createPostTeamPreprocessingSubpipeline(b, postTeamConfig)
                                // Group by token:distinctId and process each group concurrently
                                // Events within each group are processed sequentially
                                .filterMap(mapToPerEventInput, (b) =>
                                    b
                                        .groupBy(getTokenAndDistinctId)
                                        .concurrently((eventsForDistinctId) =>
                                            eventsForDistinctId.sequentially((event) =>
                                                createPerDistinctIdPipeline(event, perEventConfig)
                                            )
                                        )
                                )
                                .gather()
                                // Flush person and group stores after all events processed
                                .pipeBatch(
                                    createFlushBatchStoresStep({
                                        personsStore,
                                        groupStore,
                                        kafkaProducer,
                                    })
                                )
                        )
                        .handleIngestionWarnings(kafkaProducer)
                )
        )
        .handleResults(pipelineConfig)
        .handleSideEffects(promiseScheduler, { await: false })
}
