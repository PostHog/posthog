import { Message } from 'node-rdkafka'
import { Gauge, Histogram } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { CommonConfig } from '../common/config'
import { KafkaConsumer } from '../kafka/consumer'
import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    RedisPool,
} from '../types'
import { PostgresRouter } from '../utils/db/postgres'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restrictions'
import { EventSchemaEnforcementManager } from '../utils/event-schema-enforcement-manager'
import { logger } from '../utils/logger'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { TeamManager } from '../utils/team-manager'
import { GroupTypeManager } from '../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../worker/ingestion/groups/batch-writing-group-store'
import { ClickhouseGroupRepository } from '../worker/ingestion/groups/repositories/clickhouse-group-repository'
import { GroupRepository } from '../worker/ingestion/groups/repositories/group-repository.interface'
import { BatchWritingPersonsStore } from '../worker/ingestion/persons/batch-writing-person-store'
import { PersonsStore } from '../worker/ingestion/persons/persons-store'
import { PersonRepository } from '../worker/ingestion/persons/repositories/person-repository'
import {
    JoinedIngestionPipelineConfig,
    JoinedIngestionPipelineContext,
    JoinedIngestionPipelineDeps,
    JoinedIngestionPipelineInput,
    createJoinedIngestionPipeline,
} from './analytics'
import {
    AiEventOutput,
    AsyncOutput,
    EventOutput,
    HeatmapsOutput,
    PersonDistinctIdsOutput,
    PersonsOutput,
} from './analytics/outputs'
import { EventFilterManager } from './common/event-filters'
import {
    AppMetricsOutput,
    DlqOutput,
    GroupsOutput,
    IngestionWarningsOutput,
    OverflowOutput,
    TophogOutput,
} from './common/outputs'
import { IngestionConsumerConfig } from './config'
import { CookielessManager } from './cookieless/cookieless-manager'
import { parseSplitAiEventsConfig } from './event-processing/split-ai-events-step'
import { IngestionOutputs } from './outputs/ingestion-outputs'
import { createOkContext } from './pipelines/helpers'
import { TopHog } from './tophog'
import { MainLaneOverflowRedirect } from './utils/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirect } from './utils/overflow-redirect/overflow-lane-overflow-redirect'
import { OverflowRedirectService } from './utils/overflow-redirect/overflow-redirect-service'
import { RedisOverflowRepository } from './utils/overflow-redirect/overflow-redis-repository'

export type IngestionConsumerFullConfig = IngestionConsumerConfig &
    Pick<CommonConfig, 'KAFKA_CLIENT_RACK' | 'CDP_HOG_WATCHER_SAMPLE_RATE'>

export interface IngestionConsumerDeps {
    postgres: PostgresRouter
    redisPool: RedisPool
    outputs: IngestionOutputs<
        | EventOutput
        | AiEventOutput
        | HeatmapsOutput
        | IngestionWarningsOutput
        | DlqOutput
        | OverflowOutput
        | AsyncOutput
        | GroupsOutput
        | PersonsOutput
        | PersonDistinctIdsOutput
        | AppMetricsOutput
        | TophogOutput
    >
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    groupRepository: GroupRepository
    clickhouseGroupRepository: ClickhouseGroupRepository
    personRepository: PersonRepository
    cookielessManager: CookielessManager
    hogTransformer: HogTransformerService
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

const backgroundTaskHogTransformerDuration = new Histogram({
    name: 'ingestion_background_task_hog_transformer_duration_seconds',
    help: 'Time waiting for hog transformer invocation results in the background task',
    labelNames: ['groupId'],
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
})

export class IngestionConsumer {
    protected name = 'ingestion-consumer'
    protected groupId: string
    protected topic: string
    protected kafkaConsumer: KafkaConsumer
    isStopping = false
    public hogTransformer: HogTransformerService
    private overflowRedirectService?: OverflowRedirectService
    private overflowLaneTTLRefreshService?: OverflowRedirectService
    private tokenDistinctIdsToDrop: string[] = []
    private tokenDistinctIdsToSkipPersons: string[] = []
    private tokenDistinctIdsToForceOverflow: string[] = []
    private personsStore: PersonsStore
    public groupStore: BatchWritingGroupStore
    private eventFilterManager: EventFilterManager
    private eventIngestionRestrictionManager: EventIngestionRestrictionManager
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
        this.eventIngestionRestrictionManager = new EventIngestionRestrictionManager(deps.redisPool, {
            pipeline: 'analytics',
            staticDropEventTokens: this.tokenDistinctIdsToDrop,
            staticSkipPersonTokens: this.tokenDistinctIdsToSkipPersons,
            staticForceOverflowTokens: this.tokenDistinctIdsToForceOverflow,
        })
        this.eventFilterManager = new EventFilterManager(deps.postgres)
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
            })
        }

        // Create TTL refresh service when consuming from overflow topic (overflow lane)
        if (this.config.INGESTION_LANE === 'overflow' && this.config.INGESTION_STATEFUL_OVERFLOW_ENABLED) {
            this.overflowLaneTTLRefreshService = new OverflowLaneOverflowRedirect({
                redisRepository: overflowRedisRepository,
            })
        }

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

        this.kafkaConsumer = new KafkaConsumer({
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
            groupId: this.groupId,
            outputs,
            splitAiEventsConfig: parseSplitAiEventsConfig(
                this.config.INGESTION_AI_EVENT_SPLITTING_ENABLED,
                this.config.INGESTION_AI_EVENT_SPLITTING_TEAMS,
                this.config.INGESTION_AI_EVENT_SPLITTING_STRIP_HEAVY
            ),
            perDistinctIdOptions: {
                SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: this.config.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
                PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: this.config.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
                PERSON_MERGE_ASYNC_ENABLED: this.config.PERSON_MERGE_ASYNC_ENABLED,
                PERSON_MERGE_SYNC_BATCH_SIZE: this.config.PERSON_MERGE_SYNC_BATCH_SIZE,
                PERSON_JSONB_SIZE_ESTIMATE_ENABLE: this.config.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
                PERSON_PROPERTIES_UPDATE_ALL: this.config.PERSON_PROPERTIES_UPDATE_ALL,
            },
        }
        const joinedPipelineDeps: JoinedIngestionPipelineDeps = {
            personsStore: this.personsStore,
            groupStore: this.groupStore,
            hogTransformer: this.hogTransformer,
            eventFilterManager: this.eventFilterManager,
            eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
            eventSchemaEnforcementManager: this.eventSchemaEnforcementManager,
            promiseScheduler: this.promiseScheduler,
            overflowRedirectService: this.overflowRedirectService,
            overflowLaneTTLRefreshService: this.overflowLaneTTLRefreshService,
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
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        logger.info('🔁', `${this.name} - stopping batch consumer`)
        await this.kafkaConsumer?.disconnect()
        logger.info('🔁', `${this.name} - stopping tophog`)
        await this.topHog.stop()
        logger.info('🔁', `${this.name} - stopping hog transformer`)
        await this.hogTransformer.stop()
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
                await Promise.all([
                    timedHistogram(backgroundTaskProducesDuration, labels, () => this.promiseScheduler.waitForAll()),
                    timedHistogram(backgroundTaskHogTransformerDuration, labels, () =>
                        this.hogTransformer.processInvocationResults()
                    ),
                ])
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
