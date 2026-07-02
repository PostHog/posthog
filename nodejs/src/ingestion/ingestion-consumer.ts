import { Message } from 'node-rdkafka'
import { Gauge, Histogram } from 'prom-client'

import { CommonConfig } from '~/common/config'
import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { ClickhouseGroupRepository } from '~/common/groups/repositories/clickhouse-group-repository'
import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import {
    AppMetricsOutput,
    DlqOutput,
    GroupsOutput,
    IngestionWarningsOutput,
    OverflowOutput,
    TophogOutput,
} from '~/common/outputs'
import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    PersonDistinctIdsOutput,
    PersonMergeEventsOutput,
    PersonsOutput,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PersonRepository } from '~/common/persons/repositories/person-repository'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresRouter } from '~/common/utils/db/postgres'
import {
    EventIngestionRestrictionManager,
    EventIngestionRestrictionManagerComponent,
} from '~/common/utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { logger } from '~/common/utils/logger'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { BatchWritingGroupStore } from '~/ingestion/common/groups/batch-writing-group-store'
import { BatchWritingPersonsStore } from '~/ingestion/common/persons/batch-writing-person-store'
import { PersonsStore } from '~/ingestion/common/persons/persons-store'
import { createOkContext } from '~/ingestion/framework/helpers'
import { TopHog } from '~/ingestion/framework/tophog'
import {
    JoinedIngestionPipelineConfig,
    JoinedIngestionPipelineContext,
    JoinedIngestionPipelineDeps,
    JoinedIngestionPipelineInput,
    createJoinedIngestionPipeline,
} from '~/ingestion/pipelines/analytics'
import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginServerService, RedisPool } from '~/types'

import { EventFilterManager, EventFilterManagerComponent } from './common/event-filters'
import {
    FeatureFlagCalledDedupService,
    createFeatureFlagCalledDedupService,
} from './common/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { MainLaneOverflowRedirect } from './common/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirect } from './common/overflow-redirect/overflow-lane-overflow-redirect'
import { OverflowRedirectService } from './common/overflow-redirect/overflow-redirect-service'
import { RedisOverflowRepository } from './common/overflow-redirect/overflow-redis-repository'
import { AiEventSubpipelineFactory } from './common/subpipelines/ai-subpipeline.contract'
import { IngestionConsumerConfig } from './config'

export type IngestionConsumerFullConfig = IngestionConsumerConfig &
    Pick<CommonConfig, 'KAFKA_CLIENT_RACK' | 'CDP_HOG_WATCHER_SAMPLE_RATE'>

export interface IngestionConsumerDeps {
    postgres: PostgresRouter
    redisPool: RedisPool
    /** Dedicated pool for $feature_flag_called dedup claims; reuses redisPool when unset */
    featureFlagCalledDedupRedisPool?: RedisPool
    outputs: IngestionOutputs<
        | EventOutput
        | AiEventOutput
        | IngestionWarningsOutput
        | DlqOutput
        | OverflowOutput
        | AsyncOutput
        | GroupsOutput
        | PersonsOutput
        | PersonDistinctIdsOutput
        | PersonMergeEventsOutput
        | AppMetricsOutput
        | TophogOutput
    >
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    groupRepository: GroupRepository
    clickhouseGroupRepository: ClickhouseGroupRepository
    personRepository: PersonRepository
    cookielessManager: CookielessManager
    hogTransformer: HogTransformer
    aiSubpipelineFactory: AiEventSubpipelineFactory
}

export const latestOffsetTimestampGauge = new Gauge({
    name: 'latest_processed_timestamp_ms',
    help: 'Timestamp of the latest offset that has been committed.',
    labelNames: ['topic', 'partition', 'groupId'],
    aggregator: 'max',
})

const backgroundTaskProducesDuration = new Histogram({
    name: 'ingestion_background_task_produces_duration_seconds',
    help: 'Time waiting for scheduled Kafka produces in the background task',
    labelNames: ['groupId'],
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
})

export class IngestionConsumer {
    protected name = 'ingestion-consumer'
    protected groupId: string
    protected topic: string
    protected kafkaConsumer: KafkaConsumerInterface
    isStopping = false
    public hogTransformer: HogTransformer
    private overflowRedirectService?: OverflowRedirectService
    private overflowLaneTTLRefreshService?: OverflowRedirectService
    private featureFlagCalledDedupService?: FeatureFlagCalledDedupService
    private tokenDistinctIdsToDrop: string[] = []
    private tokenDistinctIdsToSkipPersons: string[] = []
    private tokenDistinctIdsToForceOverflow: string[] = []
    private personsStore: PersonsStore
    public groupStore: BatchWritingGroupStore
    private eventFilterManagerComponent: EventFilterManagerComponent
    private eventFilterManager!: EventFilterManager
    private stopEventFilterManager?: () => Promise<void>
    private eventIngestionRestrictionManagerComponent: EventIngestionRestrictionManagerComponent
    private eventIngestionRestrictionManager!: EventIngestionRestrictionManager
    private stopEventIngestionRestrictionManager?: () => Promise<void>
    private eventSchemaEnforcementManager: EventSchemaEnforcementManager
    public readonly promiseScheduler = new PromiseScheduler()
    private topHog!: TopHog

    private joinedPipeline!: ReturnType<
        typeof createJoinedIngestionPipeline<JoinedIngestionPipelineInput, JoinedIngestionPipelineContext>
    >

    constructor(
        private config: IngestionConsumerFullConfig,
        private deps: IngestionConsumerDeps,
        overrides: Partial<
            Pick<
                IngestionConsumerConfig,
                | 'INGESTION_CONSUMER_GROUP_ID'
                | 'INGESTION_CONSUMER_CONSUME_TOPIC'
                | 'INGESTION_CONSUMER_OVERFLOW_TOPIC'
                | 'INGESTION_CONSUMER_DLQ_TOPIC'
            >
        > = {}
    ) {
        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = overrides.INGESTION_CONSUMER_GROUP_ID ?? config.INGESTION_CONSUMER_GROUP_ID
        this.topic = overrides.INGESTION_CONSUMER_CONSUME_TOPIC ?? config.INGESTION_CONSUMER_CONSUME_TOPIC
        this.tokenDistinctIdsToDrop = config.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)
        this.tokenDistinctIdsToSkipPersons = config.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID.split(',').filter(
            (x) => !!x
        )
        this.tokenDistinctIdsToForceOverflow = config.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID.split(',').filter(
            (x) => !!x
        )
        this.eventIngestionRestrictionManagerComponent = new EventIngestionRestrictionManagerComponent(deps.redisPool, {
            pipeline: 'analytics',
            staticDropEventTokens: this.tokenDistinctIdsToDrop,
            staticSkipPersonTokens: this.tokenDistinctIdsToSkipPersons,
            staticForceOverflowTokens: this.tokenDistinctIdsToForceOverflow,
        })
        this.eventFilterManagerComponent = new EventFilterManagerComponent(deps.postgres)
        this.eventSchemaEnforcementManager = new EventSchemaEnforcementManager(deps.postgres)

        this.name = `ingestion-consumer-${this.topic}`

        // Create shared Redis repository for overflow redirect services
        const overflowRedisRepository = new RedisOverflowRepository({
            redisPool: this.deps.redisPool,
            redisTTLSeconds: this.config.INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS,
        })

        // Create overflow redirect service only when overflow is enabled (main lane)
        if (this.overflowEnabled()) {
            this.overflowRedirectService = new MainLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
                localCacheTTLSeconds: this.config.INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
                bucketCapacity: this.config.EVENT_OVERFLOW_BUCKET_CAPACITY,
                replenishRate: this.config.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE,
                statefulEnabled: this.config.INGESTION_STATEFUL_OVERFLOW_ENABLED,
                overflowType: 'events',
            })
        }

        // Create TTL refresh service when consuming from overflow topic (overflow lane)
        if (this.config.INGESTION_LANE === 'overflow' && this.config.INGESTION_STATEFUL_OVERFLOW_ENABLED) {
            this.overflowLaneTTLRefreshService = new OverflowLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
                overflowType: 'events',
            })
        }

        this.featureFlagCalledDedupService = createFeatureFlagCalledDedupService(
            this.deps.featureFlagCalledDedupRedisPool ?? this.deps.redisPool,
            this.config
        )

        this.hogTransformer = deps.hogTransformer

        this.personsStore = new BatchWritingPersonsStore(this.deps.personRepository, this.deps.outputs, {
            dbWriteMode: this.config.PERSON_BATCH_WRITING_DB_WRITE_MODE,
            useBatchUpdates: this.config.PERSON_BATCH_WRITING_USE_BATCH_UPDATES,
            maxConcurrentUpdates: this.config.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.config.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.config.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
            updateAllProperties: this.config.PERSON_PROPERTIES_UPDATE_ALL,
        })

        this.groupStore = new BatchWritingGroupStore(
            this.deps.outputs,
            this.deps.groupRepository,
            this.deps.clickhouseGroupRepository,
            {
                maxConcurrentUpdates: this.config.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
                maxOptimisticUpdateRetries: this.config.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
                optimisticUpdateRetryInterval: this.config.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
            }
        )

        this.kafkaConsumer = createKafkaConsumer({
            groupId: this.groupId,
            topic: this.topic,
        })

        this.topHog = new TopHog({
            outputs: this.deps.outputs,
            pipeline: this.config.INGESTION_PIPELINE ?? 'unknown',
            lane: this.config.INGESTION_LANE ?? 'unknown',
        })
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    public async start(): Promise<void> {
        const startedRestrictions = await this.eventIngestionRestrictionManagerComponent.start()
        this.eventIngestionRestrictionManager = startedRestrictions.value
        this.stopEventIngestionRestrictionManager = startedRestrictions.stop
        const startedFilters = await this.eventFilterManagerComponent.start()
        this.eventFilterManager = startedFilters.value
        this.stopEventFilterManager = startedFilters.stop
        await this.hogTransformer.start()

        this.topHog.start()

        const outputs = this.deps.outputs

        // Verify all output topics exist. When auto_create_topics_enabled=true
        // (hobby/dev), this ensures topics are created before first produce.
        // When auto-create is off (production), this catches misconfigurations early.
        const topicFailures = await outputs.checkTopics()
        if (topicFailures.length > 0) {
            throw new Error(`Output topic verification failed for: ${topicFailures.join(', ')}`)
        }

        const joinedPipelineConfig: JoinedIngestionPipelineConfig = {
            eventSchemaEnforcementEnabled: this.config.EVENT_SCHEMA_ENFORCEMENT_ENABLED,
            overflowEnabled: this.overflowEnabled(),
            preservePartitionLocality: this.config.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
            personsPrefetchEnabled: this.config.PERSONS_PREFETCH_ENABLED,
            cdpHogWatcherSampleRate: this.config.CDP_HOG_WATCHER_SAMPLE_RATE,
            outputs,
            perDistinctIdOptions: {
                SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: this.config.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
                PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: this.config.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
                PERSON_MERGE_ASYNC_ENABLED: this.config.PERSON_MERGE_ASYNC_ENABLED,
                PERSON_MERGE_SYNC_BATCH_SIZE: this.config.PERSON_MERGE_SYNC_BATCH_SIZE,
                PERSON_MERGE_EVENTS_ENABLED: this.config.PERSON_MERGE_EVENTS_ENABLED,
                PERSON_MERGE_EVENTS_PARTITION_COUNT: this.config.PERSON_MERGE_EVENTS_PARTITION_COUNT,
                PERSON_JSONB_SIZE_ESTIMATE_ENABLE: this.config.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
                PERSON_PROPERTIES_UPDATE_ALL: this.config.PERSON_PROPERTIES_UPDATE_ALL,
                FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS: this.config.FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS,
            },
            concurrentBatches: this.config.INGESTION_WORKER_CONCURRENT_BATCHES,
        }
        const joinedPipelineDeps: JoinedIngestionPipelineDeps = {
            personsStore: this.personsStore,
            groupStore: this.groupStore,
            hogTransformer: this.hogTransformer,
            aiSubpipelineFactory: this.deps.aiSubpipelineFactory,
            eventFilterManager: this.eventFilterManager,
            eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
            eventSchemaEnforcementManager: this.eventSchemaEnforcementManager,
            promiseScheduler: this.promiseScheduler,
            overflowRedirectService: this.overflowRedirectService,
            overflowLaneTTLRefreshService: this.overflowLaneTTLRefreshService,
            featureFlagCalledDedupService: this.featureFlagCalledDedupService,
            teamManager: this.deps.teamManager,
            cookielessManager: this.deps.cookielessManager,
            groupTypeManager: this.deps.groupTypeManager,
            topHog: this.topHog!,
        }
        this.joinedPipeline = createJoinedIngestionPipeline(joinedPipelineConfig, joinedPipelineDeps)

        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn(
                {
                    key: `ingestionConsumer.handleEachBatch`,
                    sendException: false,
                },
                async () => await this.handleKafkaBatch(messages)
            )
        })
    }

    public async stop(): Promise<void> {
        if (this.isStopping) {
            return
        }
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        logger.info('🔁', `${this.name} - stopping batch consumer`)
        await this.kafkaConsumer?.disconnect()
        logger.info('🔁', `${this.name} - stopping tophog`)
        await this.topHog.stop()
        logger.info('🔁', `${this.name} - stopping hog transformer`)
        await this.hogTransformer.stop()
        await this.stopEventFilterManager?.()
        await this.stopEventIngestionRestrictionManager?.()
        // Stores must be clean by now — flushBatchStoresStep runs after every
        // batch as part of the pipeline. After disconnect, we cannot commit
        // offsets, so writing dirty data here would produce duplicates on
        // partition rebalance. shutdown() will throw if anything is dirty,
        // which surfaces the drain-ordering bug without masking it.
        try {
            await this.personsStore.shutdown()
        } catch (error) {
            logger.error('🚨', `${this.name} - personsStore.shutdown() failed`, { error })
        }
        try {
            await this.groupStore.shutdown()
        } catch (error) {
            logger.error('🚨', `${this.name} - groupStore.shutdown() failed`, { error })
        }
        logger.info('👍', `${this.name} - stopped!`)
    }

    public async isHealthy(): Promise<HealthCheckResult> {
        if (!this.kafkaConsumer) {
            return new HealthCheckResultError('Kafka consumer not initialized', {})
        }

        const consumerHealth = this.kafkaConsumer.isHealthy()
        if (consumerHealth.isError()) {
            return consumerHealth
        }

        if (process.env.INGESTION_OUTPUTS_PRODUCER_HEALTHCHECK === 'true') {
            const failures = await this.deps.outputs.checkHealth()
            if (failures.length > 0) {
                return new HealthCheckResultError('Kafka producer(s) unhealthy', { failedProducers: failures })
            }
        }

        return new HealthCheckResultOk()
    }

    private runInstrumented<T>(name: string, func: () => Promise<T>): Promise<T> {
        return instrumentFn<T>(`ingestionConsumer.${name}`, func)
    }

    private logBatchStart(messages: Message[]): void {
        // Log earliest message from each partition to detect duplicate processing across pods
        const podName = process.env.HOSTNAME || 'unknown'
        const partitionEarliestMessages = new Map<number, Message>()
        const partitionBatchSizes = new Map<number, number>()

        messages.forEach((message) => {
            const existing = partitionEarliestMessages.get(message.partition)
            if (!existing || message.offset < existing.offset) {
                partitionEarliestMessages.set(message.partition, message)
            }
            partitionBatchSizes.set(message.partition, (partitionBatchSizes.get(message.partition) || 0) + 1)
        })

        // Create partition data array for single log entry
        const partitionData = Array.from(partitionEarliestMessages.entries()).map(([partition, message]) => ({
            partition,
            offset: message.offset,
            batchSize: partitionBatchSizes.get(partition) || 0,
        }))

        logger.info('📖', `KAFKA_BATCH_START: ${this.name}`, {
            pod: podName,
            totalMessages: messages.length,
            partitions: partitionData,
        })
    }

    public async handleKafkaBatch(messages: Message[]): Promise<{ backgroundTask?: Promise<any> }> {
        if (this.config.KAFKA_BATCH_START_LOGGING_ENABLED) {
            this.logBatchStart(messages)
        }

        await this.runIngestionPipeline(messages)

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: this.groupId })
                    .set(message.timestamp)
            }
        }

        return {
            backgroundTask: this.runInstrumented('awaitScheduledWork', async () => {
                const labels = { groupId: this.groupId }
                // Drains scheduled produces and the hog transformer invocation results, which
                // the pipeline's afterBatch flush step schedules as a side effect.
                await timedHistogram(backgroundTaskProducesDuration, labels, () => this.promiseScheduler.waitForAll())
            }),
        }
    }

    private async runIngestionPipeline(messages: Message[]): Promise<void> {
        const batch = messages.map((message) => createOkContext({ message }, { message }))

        const feedResult = await this.joinedPipeline.feed(batch)
        if (!feedResult.ok) {
            throw new Error(`Pipeline rejected batch: ${feedResult.reason}`)
        }

        // Drain the pipeline, scheduling batch-level side effects
        let result = await this.joinedPipeline.next()
        while (result !== null) {
            for (const sideEffect of result.sideEffects ?? []) {
                void this.promiseScheduler.schedule(sideEffect)
            }
            result = await this.joinedPipeline.next()
        }
    }

    private overflowEnabled(): boolean {
        return (
            !!this.config.INGESTION_CONSUMER_OVERFLOW_TOPIC &&
            this.config.INGESTION_CONSUMER_OVERFLOW_TOPIC !== this.topic
        )
    }
}

async function timedHistogram<T>(
    histogram: Histogram,
    labels: Record<string, string>,
    fn: () => Promise<T>
): Promise<T> {
    const end = histogram.startTimer(labels)
    try {
        return await fn()
    } finally {
        end()
    }
}
