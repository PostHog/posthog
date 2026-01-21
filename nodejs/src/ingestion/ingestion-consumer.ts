import { Message } from 'node-rdkafka'
import { Counter, Gauge } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { MessageSizeTooLarge } from '~/utils/db/error'
import { captureIngestionWarning } from '~/worker/ingestion/utils'

import { HogTransformerHub, HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { KafkaConsumer } from '../kafka/consumer'
import { KafkaProducerWrapper } from '../kafka/producer'
import {
    EventHeaders,
    HealthCheckResult,
    HealthCheckResultError,
    Hub,
    IncomingEvent,
    IncomingEventWithTeam,
    IngestionConsumerConfig,
    PipelineEvent,
    PluginServerService,
    PluginsServerConfig,
    Team,
} from '../types'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restriction-manager'
import { logger } from '../utils/logger'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { BatchWritingGroupStore } from '../worker/ingestion/groups/batch-writing-group-store'
import { GroupStoreForBatch } from '../worker/ingestion/groups/group-store-for-batch.interface'
import { BatchWritingPersonsStore } from '../worker/ingestion/persons/batch-writing-person-store'
import { FlushResult, PersonsStore } from '../worker/ingestion/persons/persons-store'
import {
    JoinedIngestionPipelineConfig,
    JoinedIngestionPipelineContext,
    JoinedIngestionPipelineInput,
    PerDistinctIdPipelineInput,
    createJoinedIngestionPipeline,
    createPerDistinctIdPipeline,
    createPreprocessingPipeline,
} from './analytics'
import { BatchPipelineUnwrapper } from './pipelines/batch-pipeline-unwrapper'
import { BatchPipeline } from './pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from './pipelines/builders'
import { createBatch, createContext, createUnwrapper } from './pipelines/helpers'
import { ok } from './pipelines/results'
import { MemoryRateLimiter } from './utils/overflow-detector'

/**
 * Narrowed Hub type for IngestionConsumer.
 * This includes all fields needed by IngestionConsumer and its dependencies:
 * - HogTransformerService (via HogTransformerHub)
 * - BatchWritingGroupStore (via GroupHub)
 * - EventIngestionRestrictionManager
 * - KafkaProducerWrapper
 * - BatchWritingPersonsStore
 * - Preprocessing and ingestion pipelines
 */
export type IngestionConsumerHub = HogTransformerHub &
    IngestionConsumerConfig &
    Pick<
        Hub,
        // EventIngestionRestrictionManager
        | 'redisPool'
        // GroupHub (BatchWritingGroupStore)
        | 'groupRepository'
        | 'clickhouseGroupRepository'
        // KafkaProducerWrapper.create
        | 'KAFKA_CLIENT_RACK'
        // PreprocessingHub (additional fields not in HogTransformerHub)
        | 'cookielessManager'
        // BatchWritingPersonsStore
        | 'personRepository'
        // GroupTypeManager
        | 'groupTypeManager'
    >

type EventWithHeaders = IncomingEventWithTeam & { headers: EventHeaders }

type EventsForDistinctId = {
    token: string
    distinctId: string
    events: EventWithHeaders[]
}

type IncomingEventsByDistinctId = {
    [key: string]: EventsForDistinctId
}

type PreprocessedEvent = {
    message: Message
    headers: EventHeaders
    event: IncomingEvent
    eventWithTeam: IncomingEventWithTeam
}

// Re-export PerDistinctIdPipelineInput for backwards compatibility
export type { PerDistinctIdPipelineInput }

const PERSON_EVENTS = new Set(['$set', '$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])
const KNOWN_SET_EVENTS = new Set([
    '$feature_interaction',
    '$feature_enrollment_update',
    'survey dismissed',
    'survey sent',
])

const trackIfNonPersonEventUpdatesPersons = (event: PipelineEvent): void => {
    if (
        !PERSON_EVENTS.has(event.event) &&
        !KNOWN_SET_EVENTS.has(event.event) &&
        (event.properties?.$set || event.properties?.$set_once || event.properties?.$unset)
    ) {
        setUsageInNonPersonEventsCounter.inc()
    }
}

const latestOffsetTimestampGauge = new Gauge({
    name: 'latest_processed_timestamp_ms',
    help: 'Timestamp of the latest offset that has been committed.',
    labelNames: ['topic', 'partition', 'groupId'],
    aggregator: 'max',
})

const setUsageInNonPersonEventsCounter = new Counter({
    name: 'set_usage_in_non_person_events',
    help: 'Count of events where $set usage was found in non-person events',
})

export class IngestionConsumer {
    protected name = 'ingestion-consumer'
    protected groupId: string
    protected topic: string
    protected dlqTopic: string
    protected overflowTopic?: string
    protected kafkaConsumer: KafkaConsumer
    isStopping = false
    protected kafkaProducer?: KafkaProducerWrapper
    protected kafkaOverflowProducer?: KafkaProducerWrapper
    public hogTransformer: HogTransformerService
    private overflowRateLimiter: MemoryRateLimiter
    private tokenDistinctIdsToDrop: string[] = []
    private tokenDistinctIdsToSkipPersons: string[] = []
    private tokenDistinctIdsToForceOverflow: string[] = []
    private personsStore: PersonsStore
    public groupStore: BatchWritingGroupStore
    private eventIngestionRestrictionManager: EventIngestionRestrictionManager
    public readonly promiseScheduler = new PromiseScheduler()

    private preprocessingPipeline!: BatchPipelineUnwrapper<
        { message: Message },
        PreprocessedEvent,
        { message: Message }
    >
    private perDistinctIdPipeline!: BatchPipeline<PerDistinctIdPipelineInput, void, { message: Message; team: Team }>
    private joinedPipeline!: BatchPipeline<
        JoinedIngestionPipelineInput,
        void,
        JoinedIngestionPipelineContext,
        JoinedIngestionPipelineContext
    >

    constructor(
        private hub: IngestionConsumerHub,
        overrides: Partial<
            Pick<
                PluginsServerConfig,
                | 'INGESTION_CONSUMER_GROUP_ID'
                | 'INGESTION_CONSUMER_CONSUME_TOPIC'
                | 'INGESTION_CONSUMER_OVERFLOW_TOPIC'
                | 'INGESTION_CONSUMER_DLQ_TOPIC'
            >
        > = {}
    ) {
        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = overrides.INGESTION_CONSUMER_GROUP_ID ?? hub.INGESTION_CONSUMER_GROUP_ID
        this.topic = overrides.INGESTION_CONSUMER_CONSUME_TOPIC ?? hub.INGESTION_CONSUMER_CONSUME_TOPIC
        this.overflowTopic = overrides.INGESTION_CONSUMER_OVERFLOW_TOPIC ?? hub.INGESTION_CONSUMER_OVERFLOW_TOPIC
        this.dlqTopic = overrides.INGESTION_CONSUMER_DLQ_TOPIC ?? hub.INGESTION_CONSUMER_DLQ_TOPIC
        this.tokenDistinctIdsToDrop = hub.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)
        this.tokenDistinctIdsToSkipPersons = hub.SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID.split(',').filter(
            (x) => !!x
        )
        this.tokenDistinctIdsToForceOverflow = hub.INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID.split(',').filter(
            (x) => !!x
        )
        this.eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
            pipeline: 'analytics',
            staticDropEventTokens: this.tokenDistinctIdsToDrop,
            staticSkipPersonTokens: this.tokenDistinctIdsToSkipPersons,
            staticForceOverflowTokens: this.tokenDistinctIdsToForceOverflow,
        })

        this.name = `ingestion-consumer-${this.topic}`
        this.overflowRateLimiter = new MemoryRateLimiter(
            this.hub.EVENT_OVERFLOW_BUCKET_CAPACITY,
            this.hub.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE
        )
        this.hogTransformer = new HogTransformerService(hub)

        this.personsStore = new BatchWritingPersonsStore(this.hub.personRepository, this.hub.kafkaProducer, {
            dbWriteMode: this.hub.PERSON_BATCH_WRITING_DB_WRITE_MODE,
            useBatchUpdates: this.hub.PERSON_BATCH_WRITING_USE_BATCH_UPDATES,
            maxConcurrentUpdates: this.hub.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.hub.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.hub.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
            updateAllProperties: this.hub.PERSON_PROPERTIES_UPDATE_ALL,
        })

        this.groupStore = new BatchWritingGroupStore(this.hub, {
            maxConcurrentUpdates: this.hub.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.hub.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.hub.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        })

        this.kafkaConsumer = new KafkaConsumer({
            groupId: this.groupId,
            topic: this.topic,
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
        await Promise.all([
            this.hogTransformer.start(),
            KafkaProducerWrapper.create(this.hub.KAFKA_CLIENT_RACK).then((producer) => {
                this.kafkaProducer = producer
            }),
            // TRICKY: When we produce overflow events they are back to the kafka we are consuming from
            KafkaProducerWrapper.create(this.hub.KAFKA_CLIENT_RACK, 'CONSUMER').then((producer) => {
                this.kafkaOverflowProducer = producer
            }),
        ])

        // Initialize batch preprocessing pipeline after kafka producer is available
        this.preprocessingPipeline = createUnwrapper(
            createPreprocessingPipeline(newBatchPipelineBuilder<{ message: Message }, { message: Message }>(), {
                hub: this.hub,
                kafkaProducer: this.kafkaProducer!,
                personsStore: this.personsStore,
                hogTransformer: this.hogTransformer,
                eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
                overflowRateLimiter: this.overflowRateLimiter,
                overflowEnabled: this.overflowEnabled(),
                overflowTopic: this.overflowTopic || '',
                dlqTopic: this.dlqTopic,
                promiseScheduler: this.promiseScheduler,
            }).build()
        )

        const perDistinctIdOptions = {
            CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC: this.hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
            CLICKHOUSE_HEATMAPS_KAFKA_TOPIC: this.hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
            SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: this.hub.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP,
            TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: this.hub.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE,
            PIPELINE_STEP_STALLED_LOG_TIMEOUT: this.hub.PIPELINE_STEP_STALLED_LOG_TIMEOUT,
            PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: this.hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
            PERSON_MERGE_ASYNC_ENABLED: this.hub.PERSON_MERGE_ASYNC_ENABLED,
            PERSON_MERGE_ASYNC_TOPIC: this.hub.PERSON_MERGE_ASYNC_TOPIC,
            PERSON_MERGE_SYNC_BATCH_SIZE: this.hub.PERSON_MERGE_SYNC_BATCH_SIZE,
            PERSON_JSONB_SIZE_ESTIMATE_ENABLE: this.hub.PERSON_JSONB_SIZE_ESTIMATE_ENABLE,
            PERSON_PROPERTIES_UPDATE_ALL: this.hub.PERSON_PROPERTIES_UPDATE_ALL,
        }

        // Initialize main event pipeline
        this.perDistinctIdPipeline = createPerDistinctIdPipeline(
            newBatchPipelineBuilder<PerDistinctIdPipelineInput, { message: Message; team: Team }>(),
            {
                options: perDistinctIdOptions,
                teamManager: this.hub.teamManager,
                groupTypeManager: this.hub.groupTypeManager,
                hogTransformer: this.hogTransformer,
                personsStore: this.personsStore,
                kafkaProducer: this.kafkaProducer!,
                groupId: this.groupId,
                dlqTopic: this.dlqTopic,
                promiseScheduler: this.promiseScheduler,
            }
        ).build()

        // Initialize joined pipeline (combines preprocessing and per-distinct-id pipelines)
        const joinedPipelineConfig: JoinedIngestionPipelineConfig = {
            hub: this.hub,
            kafkaProducer: this.kafkaProducer!,
            personsStore: this.personsStore,
            hogTransformer: this.hogTransformer,
            eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
            overflowRateLimiter: this.overflowRateLimiter,
            overflowEnabled: this.overflowEnabled(),
            overflowTopic: this.overflowTopic || '',
            dlqTopic: this.dlqTopic,
            promiseScheduler: this.promiseScheduler,
            perDistinctIdOptions,
            teamManager: this.hub.teamManager,
            groupTypeManager: this.hub.groupTypeManager,
            groupId: this.groupId,
        }
        this.joinedPipeline = createJoinedIngestionPipeline(
            newBatchPipelineBuilder<JoinedIngestionPipelineInput, JoinedIngestionPipelineContext>(),
            joinedPipelineConfig
        ).build()

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
        logger.info('🔁', `${this.name} - stopping kafka producer`)
        await this.kafkaProducer?.disconnect()
        logger.info('🔁', `${this.name} - stopping kafka overflow producer`)
        await this.kafkaOverflowProducer?.disconnect()
        logger.info('🔁', `${this.name} - stopping hog transformer`)
        await this.hogTransformer.stop()
        logger.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        if (!this.kafkaConsumer) {
            return new HealthCheckResultError('Kafka consumer not initialized', {})
        }
        return this.kafkaConsumer.isHealthy()
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
        if (this.hub.KAFKA_BATCH_START_LOGGING_ENABLED) {
            this.logBatchStart(messages)
        }

        const groupStoreForBatch = this.groupStore.forBatch()

        if (this.hub.INGESTION_JOINED_PIPELINE) {
            await this.runJoinedIngestionPipeline(messages, groupStoreForBatch)
        } else {
            await this.runLegacyIngestionPipeline(messages, groupStoreForBatch)
        }

        const [_, personsStoreMessages] = await Promise.all([groupStoreForBatch.flush(), this.personsStore.flush()])

        if (this.kafkaProducer) {
            await this.producePersonsStoreMessages(personsStoreMessages)
        }

        this.personsStore.reportBatch()
        this.personsStore.reset()
        groupStoreForBatch.reportBatch()

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: this.groupId })
                    .set(message.timestamp)
            }
        }

        return {
            backgroundTask: this.runInstrumented('awaitScheduledWork', async () => {
                await Promise.all([this.promiseScheduler.waitForAll(), this.hogTransformer.processInvocationResults()])
            }),
        }
    }

    private async runLegacyIngestionPipeline(
        messages: Message[],
        groupStoreForBatch: GroupStoreForBatch
    ): Promise<void> {
        const preprocessedEvents = await this.runInstrumented('preprocessEvents', () => this.preprocessEvents(messages))
        const eventsPerDistinctId = this.groupEventsByDistinctId(preprocessedEvents)

        await this.runInstrumented('processBatch', async () => {
            await Promise.all(
                Object.values(eventsPerDistinctId).map(async (events) => {
                    return await this.runInstrumented('processEventsForDistinctId', () =>
                        this.processEventsForDistinctId(events, groupStoreForBatch)
                    )
                })
            )
        })
    }

    private async runJoinedIngestionPipeline(
        messages: Message[],
        groupStoreForBatch: GroupStoreForBatch
    ): Promise<void> {
        const batch = messages.map((message) => createContext(ok({ message, groupStoreForBatch }), { message }))

        this.joinedPipeline.feed(batch)

        // Drain the pipeline
        while ((await this.joinedPipeline.next()) !== null) {
            // Continue until all results are processed
        }
    }

    private async producePersonsStoreMessages(personsStoreMessages: FlushResult[]): Promise<void> {
        await Promise.all(
            personsStoreMessages.map((record) => {
                return Promise.all(
                    record.topicMessage.messages.map(async (message) => {
                        try {
                            return await this.kafkaProducer!.produce({
                                topic: record.topicMessage.topic,
                                key: message.key ? Buffer.from(message.key) : null,
                                value: message.value ? Buffer.from(message.value) : null,
                                headers: message.headers,
                            })
                        } catch (error) {
                            if (error instanceof MessageSizeTooLarge) {
                                await captureIngestionWarning(
                                    this.kafkaProducer!,
                                    record.teamId,
                                    'message_size_too_large',
                                    {
                                        eventUuid: record.uuid,
                                        distinctId: record.distinctId,
                                    }
                                )
                                logger.warn('🪣', `Message size too large`, {
                                    topic: record.topicMessage.topic,
                                    key: message.key,
                                    headers: message.headers,
                                })
                            } else {
                                throw error
                            }
                        }
                    })
                )
            })
        )
        await this.kafkaProducer!.flush()
    }

    private async processEventsForDistinctId(
        eventsForDistinctId: EventsForDistinctId,
        groupStoreForBatch: GroupStoreForBatch
    ): Promise<void> {
        const preprocessedEventsWithStores: PerDistinctIdPipelineInput[] = eventsForDistinctId.events.map(
            (incomingEvent) => {
                // Track $set usage in events that aren't known to use it, before ingestion adds anything there
                trackIfNonPersonEventUpdatesPersons(incomingEvent.event)
                return {
                    ...incomingEvent,
                    groupStoreForBatch,
                }
            }
        )

        // Feed the batch to the main event pipeline
        const eventsSequence = preprocessedEventsWithStores.map((event) =>
            createContext(ok(event), { message: event.message, team: event.team })
        )
        this.perDistinctIdPipeline.feed(eventsSequence)
        await this.perDistinctIdPipeline.next()
    }

    private async preprocessEvents(messages: Message[]): Promise<PreprocessedEvent[]> {
        // Create batch using the helper function
        const batch = createBatch(messages.map((message) => ({ message })))

        // Feed batch to the pipeline
        this.preprocessingPipeline.feed(batch)

        // Get all results from the gather pipeline (should return all results in one call)
        const result = await this.preprocessingPipeline.next()

        if (result === null) {
            return []
        }

        // Return the results (already filtered to successful ones by ResultHandlingPipeline)
        return result
    }

    private groupEventsByDistinctId(preprocessedEvents: PreprocessedEvent[]): IncomingEventsByDistinctId {
        const groupedEvents: IncomingEventsByDistinctId = {}

        for (const preprocessedEvent of preprocessedEvents) {
            const { eventWithTeam, headers } = preprocessedEvent
            const { message, event, team } = eventWithTeam
            const token = event.token ?? ''
            const distinctId = event.distinct_id ?? ''
            const eventKey = `${token}:${distinctId}`

            // We collect the events grouped by token and distinct_id so that we can process batches in parallel
            // whilst keeping the order of events for a given distinct_id.
            if (!groupedEvents[eventKey]) {
                groupedEvents[eventKey] = {
                    token: token,
                    distinctId,
                    events: [],
                }
            }

            groupedEvents[eventKey].events.push({ message, event, team, headers })
        }

        return groupedEvents
    }

    private overflowEnabled(): boolean {
        return !!this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC && this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC !== this.topic
    }
}
