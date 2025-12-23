/**
 * Multi-threaded ingestion pipeline.
 *
 * Similar to the joined pipeline, but uses worker threads for per-event processing.
 * Events are sharded across workers by token:distinctId, ensuring ordering within groups.
 *
 * Structure:
 * 1. Main thread: preprocessing (parse, team lookup, overflow, restrictions)
 * 2. Main thread: groupBy(token:distinctId) + sharding to workers
 * 3. Workers: per-event processing (event pipeline, persons, Kafka produces)
 * 4. Main thread: handle results, ingestion warnings
 */
import { Message } from 'node-rdkafka'
import * as path from 'path'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub, PipelineEvent } from '../../types'
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
import { AnalyticsWorkerConfig } from './analytics-worker'
import { PerEventProcessingInput } from './per-event-processing-subpipeline'
import { PostTeamPreprocessingSubpipelineInput } from './post-team-preprocessing-subpipeline'
import { PreprocessingPipelineConfig, createPreprocessingPipeline } from './preprocessing-pipeline'
import { SerializablePerEventInput } from './serializable-per-event-input'

export interface MultithreadedIngestionPipelineConfig {
    // Preprocessing config
    hub: Hub
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

    // Multi-threading config
    numWorkers: number
}

export interface MultithreadedIngestionPipelineInput {
    message: Message
    groupStoreForBatch: GroupStoreForBatch
}

export interface MultithreadedIngestionPipelineContext {
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

export function createMultithreadedIngestionPipeline<
    TInput extends MultithreadedIngestionPipelineInput,
    TContext extends MultithreadedIngestionPipelineContext,
>(builder: BatchPipelineBuilder<TInput, TInput, TContext, TContext>, config: MultithreadedIngestionPipelineConfig) {
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
        groupId,
        numWorkers,
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

    // Worker config - serializable configuration passed to workers
    // Workers have different cwd, so resolve paths to absolute
    const workerConfig: AnalyticsWorkerConfig = {
        kafkaConfig: {
            KAFKA_HOSTS: hub.KAFKA_HOSTS,
            KAFKA_SECURITY_PROTOCOL: hub.KAFKA_SECURITY_PROTOCOL ?? null,
            KAFKA_CLIENT_RACK: hub.KAFKA_CLIENT_RACK ?? null,
        },
        perEventOptions: perDistinctIdOptions,
        groupId,
        // Resolve MMDB path to absolute (workers have different cwd)
        mmdbFilePath: path.resolve(hub.MMDB_FILE_LOCATION),
    }

    const workerPath = require.resolve('./analytics-worker')

    return (
        createPreprocessingPipeline(builder, preprocessingConfig)
            // Filter to OK results only - preprocessing already handled DLQ, REDIRECT, etc.
            .filterOk()
            .map(mapToPerEventInput)
            .messageAware((b) =>
                b
                    .teamAware((b) =>
                        b
                            // Group by token:distinctId and dispatch to workers
                            .groupBy(getTokenAndDistinctId)
                            .multithreadedSharded<void>({
                                numWorkers,
                                workerPath,
                                workerConfig,
                                serializer: (input) => new SerializablePerEventInput(input),
                                // No deserializer needed - workers return void for OK results
                            })
                            .gather()
                    )
                    .handleIngestionWarnings(kafkaProducer)
            )
            .handleResults(pipelineConfig)
            // Side effects are handled in workers, so we don't need to await them here
            .handleSideEffects(promiseScheduler, { await: false })
            .gather()
    )
}
