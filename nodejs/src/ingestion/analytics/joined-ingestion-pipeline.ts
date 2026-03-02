import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../../utils/event-schema-enforcement-manager'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { TeamManager } from '../../utils/team-manager'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { CookielessManager } from '../cookieless/cookieless-manager'
import { EventPipelineRunnerOptions } from '../event-processing/event-pipeline-options'
import {
    BatchStores,
    createFlushBatchStoresStep,
    createSetBatchStoresStep,
} from '../event-processing/flush-batch-stores-step'
import { newBatchingPipeline } from '../pipelines/builders'
import { TopHogRegistry, createTopHogWrapper } from '../pipelines/extensions/tophog'
import { OkResultWithContext } from '../pipelines/filter-map-batch-pipeline'
import { PipelineConfig } from '../pipelines/result-handling-pipeline'
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

export interface JoinedIngestionPipelineConfig {
    eventSchemaEnforcementEnabled: boolean
    overflowEnabled: boolean
    overflowTopic: string
    dlqTopic: string
    preservePartitionLocality: boolean
    personsPrefetchEnabled: boolean
    cdpHogWatcherSampleRate: number
    groupId: string
    perDistinctIdOptions: EventPipelineRunnerOptions & {
        CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: string
        CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: string
    }
}

export interface JoinedIngestionPipelineDeps {
    kafkaProducer: KafkaProducerWrapper
    personsStore: PersonsStore
    groupStore: BatchWritingGroupStore
    hogTransformer: HogTransformerService
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventSchemaEnforcementManager: EventSchemaEnforcementManager
    promiseScheduler: PromiseScheduler
    overflowRedirectService?: OverflowRedirectService
    overflowLaneTTLRefreshService?: OverflowRedirectService
    teamManager: TeamManager
    cookielessManager: CookielessManager
    groupTypeManager: GroupTypeManager
    topHog: TopHogRegistry
}

export interface JoinedIngestionPipelineInput {
    message: Message
}

export interface JoinedIngestionPipelineContext {
    message: Message
}

type PreprocessingOutput = PostTeamPreprocessingSubpipelineInput & BatchStores

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
): OkResultWithContext<PreprocessingOutput, C> {
    return element
}

export function createJoinedIngestionPipeline<
    TInput extends JoinedIngestionPipelineInput,
    TContext extends JoinedIngestionPipelineContext,
>(config: JoinedIngestionPipelineConfig, deps: JoinedIngestionPipelineDeps) {
    const {
        eventSchemaEnforcementEnabled,
        overflowEnabled,
        overflowTopic,
        dlqTopic,
        preservePartitionLocality,
        personsPrefetchEnabled,
        cdpHogWatcherSampleRate,
        groupId,
        perDistinctIdOptions,
    } = config

    const {
        kafkaProducer,
        personsStore,
        groupStore,
        hogTransformer,
        eventIngestionRestrictionManager,
        eventSchemaEnforcementManager,
        promiseScheduler,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        teamManager,
        cookielessManager,
        groupTypeManager,
        topHog,
    } = deps

    const topHogWrapper = createTopHogWrapper(topHog)

    const pipelineConfig: PipelineConfig = {
        kafkaProducer,
        dlqTopic,
        promiseScheduler,
    }

    const postTeamConfig: PostTeamPreprocessingSubpipelineConfig = {
        eventIngestionRestrictionManager,
        eventSchemaEnforcementManager,
        eventSchemaEnforcementEnabled,
        cookielessManager,
        overflowTopic,
        preservePartitionLocality,
        overflowRedirectService,
        overflowLaneTTLRefreshService,
        personsPrefetchEnabled,
        hogTransformer,
        cdpHogWatcherSampleRate,
    }

    const perEventConfig: PerDistinctIdPipelineConfig = {
        options: perDistinctIdOptions,
        teamManager,
        groupTypeManager,
        hogTransformer,
        groupId,
        topHog: topHogWrapper,
    }

    return newBatchingPipeline<TInput, void, TContext, BatchStores>(
        (beforeBatch) => beforeBatch.pipe(createSetBatchStoresStep({ personsStore, groupStore, kafkaProducer })),
        (batch) =>
            batch
                .messageAware((b) =>
                    b
                        .sequentially((b) =>
                            createPreTeamPreprocessingSubpipeline(b, {
                                teamManager,
                                eventIngestionRestrictionManager,
                                overflowEnabled,
                                overflowTopic,
                                preservePartitionLocality,
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
                                )
                                .handleIngestionWarnings(kafkaProducer)
                        )
                )
                .handleResults(pipelineConfig)
                .handleSideEffects(promiseScheduler, { await: false }),
        (afterBatch) => afterBatch.pipe(createFlushBatchStoresStep()),
        // Batch stores (personsStore, groupStore) are singletons that don't support
        // concurrent batches yet — they accumulate state across events and flush once.
        { concurrentBatches: 1 }
    )
}
