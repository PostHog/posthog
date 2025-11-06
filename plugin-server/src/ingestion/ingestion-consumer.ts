import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { MessageSizeTooLarge } from '~/utils/db/error'
import { captureIngestionWarning } from '~/worker/ingestion/utils'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { KafkaConsumer, parseKafkaHeaders } from '../kafka/consumer'
import { KafkaProducerWrapper } from '../kafka/producer'
import { ingestionOverflowingMessagesTotal } from '../main/ingestion-queues/batch-processing/metrics'
import { latestOffsetTimestampGauge, setUsageInNonPersonEventsCounter } from '../main/ingestion-queues/metrics'
import {
    EventHeaders,
    HealthCheckResult,
    HealthCheckResultError,
    Hub,
    IncomingEvent,
    IncomingEventWithTeam,
    JwtVerificationStatus,
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
import { FlushResult, PersonsStoreForBatch } from '../worker/ingestion/persons/persons-store-for-batch'
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
    createValidateJwtStep,
} from './event-preprocessing'
import { createEmitEventStep } from './event-processing/emit-event-step'
import { createEventPipelineRunnerV1Step } from './event-processing/event-pipeline-runner-v1-step'
import { createHandleClientIngestionWarningStep } from './event-processing/handle-client-ingestion-warning-step'
import { createNormalizeProcessPersonFlagStep } from './event-processing/normalize-process-person-flag-step'
import { BatchPipelineUnwrapper } from './pipelines/batch-pipeline-unwrapper'
import { BatchPipeline } from './pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from './pipelines/builders'
import { createBatch, createContext, createUnwrapper } from './pipelines/helpers'
import { PipelineConfig } from './pipelines/result-handling-pipeline'
import { ok } from './pipelines/results'
import { MemoryRateLimiter } from './utils/overflow-detector'

const ingestionEventOverflowed = new Counter({
    name: 'ingestion_event_overflowed',
    help: 'Indicates that a given event has overflowed capacity and been redirected to a different topic.',
})

const forcedOverflowEventsCounter = new Counter({
    name: 'ingestion_forced_overflow_events_total',
    help: 'Number of events that were routed to overflow because they matched the force overflow tokens list',
})

type EventsForDistinctId = {
    token: string
    distinctId: string
    events: (IncomingEventWithTeam & { verified: JwtVerificationStatus })[]
}

type IncomingEventsByDistinctId = {
    [key: string]: EventsForDistinctId
}

type PreprocessedEvent = {
    message: Message
    headers: EventHeaders
    event: IncomingEvent
    eventWithTeam: IncomingEventWithTeam
    verified: JwtVerificationStatus
}

export interface PerDistinctIdPipelineInput extends IncomingEventWithTeam {
    personsStoreForBatch: PersonsStoreForBatch
    groupStoreForBatch: GroupStoreForBatch
    verified: JwtVerificationStatus
}

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

export class IngestionConsumer {
    protected name = 'ingestion-consumer'
    protected groupId: string
    protected topic: string
    protected dlqTopic: string
    protected overflowTopic?: string
    protected testingTopic?: string
    protected kafkaConsumer: KafkaConsumer
    isStopping = false
    protected kafkaProducer?: KafkaProducerWrapper
    protected kafkaOverflowProducer?: KafkaProducerWrapper
    public hogTransformer: HogTransformerService
    private overflowRateLimiter: MemoryRateLimiter
    private ingestionWarningLimiter: MemoryRateLimiter
    private tokenDistinctIdsToDrop: string[] = []
    private tokenDistinctIdsToSkipPersons: string[] = []
    private tokenDistinctIdsToForceOverflow: string[] = []
    private personStore: BatchWritingPersonsStore
    public groupStore: BatchWritingGroupStore
    private eventIngestionRestrictionManager: EventIngestionRestrictionManager
    public readonly promiseScheduler = new PromiseScheduler()

    private preprocessingPipeline!: BatchPipelineUnwrapper<
        { message: Message },
        PreprocessedEvent,
        { message: Message }
    >
    private perDistinctIdPipeline!: BatchPipeline<PerDistinctIdPipelineInput, void, { message: Message; team: Team }>

    constructor(
        private hub: Hub,
        overrides: Partial<
            Pick<
                PluginsServerConfig,
                | 'INGESTION_CONSUMER_GROUP_ID'
                | 'INGESTION_CONSUMER_CONSUME_TOPIC'
                | 'INGESTION_CONSUMER_OVERFLOW_TOPIC'
                | 'INGESTION_CONSUMER_DLQ_TOPIC'
                | 'INGESTION_CONSUMER_TESTING_TOPIC'
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
        this.eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub, {
            pipeline: 'analytics',
            staticDropEventTokens: this.tokenDistinctIdsToDrop,
            staticSkipPersonTokens: this.tokenDistinctIdsToSkipPersons,
            staticForceOverflowTokens: this.tokenDistinctIdsToForceOverflow,
        })
        this.testingTopic = overrides.INGESTION_CONSUMER_TESTING_TOPIC ?? hub.INGESTION_CONSUMER_TESTING_TOPIC

        this.name = `ingestion-consumer-${this.topic}`
        this.overflowRateLimiter = new MemoryRateLimiter(
            this.hub.EVENT_OVERFLOW_BUCKET_CAPACITY,
            this.hub.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE
        )

        this.ingestionWarningLimiter = new MemoryRateLimiter(1, 1.0 / 3600)
        this.hogTransformer = new HogTransformerService(hub)

        this.personStore = new BatchWritingPersonsStore(this.hub.personRepository, this.hub.db.kafkaProducer, {
            dbWriteMode: this.hub.PERSON_BATCH_WRITING_DB_WRITE_MODE,
            maxConcurrentUpdates: this.hub.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.hub.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.hub.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
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
            KafkaProducerWrapper.create(this.hub).then((producer) => {
                this.kafkaProducer = producer
            }),
            // TRICKY: When we produce overflow events they are back to the kafka we are consuming from
            KafkaProducerWrapper.create(this.hub, 'CONSUMER').then((producer) => {
                this.kafkaOverflowProducer = producer
            }),
        ])

        // Initialize batch preprocessing pipeline after kafka producer is available
        this.initializePreprocessingPipeline()

        // Initialize main event pipeline
        this.initializePerDistinctIdPipeline()

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

    private initializePreprocessingPipeline(): void {
        const pipelineConfig: PipelineConfig = {
            kafkaProducer: this.kafkaProducer!,
            dlqTopic: this.dlqTopic,
            promiseScheduler: this.promiseScheduler,
        }

        const pipeline = newBatchPipelineBuilder<{ message: Message }, { message: Message }>()
            .messageAware((builder) =>
                // All of these steps are synchronous, so we can process the messages sequentially
                // to avoid buffering due to reordering.
                builder.sequentially((b) =>
                    b
                        .pipe(createParseHeadersStep())
                        .pipe(createApplyDropRestrictionsStep(this.eventIngestionRestrictionManager))
                        .pipe(
                            createApplyForceOverflowRestrictionsStep(this.eventIngestionRestrictionManager, {
                                overflowEnabled: this.overflowEnabled(),
                                overflowTopic: this.overflowTopic || '',
                                preservePartitionLocality: this.hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY,
                            })
                        )
                        .pipe(createParseKafkaMessageStep())
                        .pipe(createDropExceptionEventsStep())
                        .pipe(createResolveTeamStep(this.hub))
                        .pipe(createValidateJwtStep(this.hub.teamSecretKeysManager))
                )
            )
            // We want to handle the first batch of rejected events, so that the remaining ones
            // can be processed in the team context.
            .handleResults(pipelineConfig)
            // We don't need to block the pipeline with side effects at this stage.
            .handleSideEffects(this.promiseScheduler, { await: false })
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
            .messageAware((builder) =>
                builder
                    .teamAware((b) =>
                        // These steps are also synchronous, so we can process events sequentially.
                        b
                            .sequentially((c) =>
                                c
                                    .pipe(createValidateEventPropertiesStep())
                                    .pipe(
                                        createApplyPersonProcessingRestrictionsStep(
                                            this.eventIngestionRestrictionManager
                                        )
                                    )
                                    .pipe(createValidateEventUuidStep())
                            )
                            // We want to call cookieless with the whole batch at once.
                            .gather()
                            .pipeBatch(createApplyCookielessProcessingStep(this.hub))
                    )
                    .handleIngestionWarnings(this.kafkaProducer!)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(this.promiseScheduler, { await: false })
            // We synchronize once again to ensure we return all events in one batch.
            .gather()
            .build()

        this.preprocessingPipeline = createUnwrapper(pipeline)
    }

    private initializePerDistinctIdPipeline(): void {
        const pipelineConfig: PipelineConfig = {
            kafkaProducer: this.kafkaProducer!,
            dlqTopic: this.dlqTopic,
            promiseScheduler: this.promiseScheduler,
        }

        this.perDistinctIdPipeline = newBatchPipelineBuilder<
            PerDistinctIdPipelineInput,
            { message: Message; team: Team }
        >()
            .messageAware((builder) =>
                builder
                    .teamAware((b) =>
                        // We process the events for the distinct id sequentially to provide ordering guarantees.
                        b.sequentially((seq) =>
                            seq.retry(
                                (retry) =>
                                    retry
                                        .pipe(createNormalizeProcessPersonFlagStep())
                                        .pipe(createHandleClientIngestionWarningStep())
                                        .pipe(createEventPipelineRunnerV1Step(this.hub, this.hogTransformer))
                                        .pipe(
                                            createEmitEventStep({
                                                kafkaProducer: this.kafkaProducer!,
                                                clickhouseJsonEventsTopic: this.hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                                            })
                                        ),
                                {
                                    tries: 3,
                                    sleepMs: 100,
                                }
                            )
                        )
                    )
                    .handleIngestionWarnings(this.kafkaProducer!)
            )
            .handleResults(pipelineConfig)
            .handleSideEffects(this.promiseScheduler, { await: false })
            // We synchronize once again to ensure we return all events in one batch.
            .gather()
            .build()
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

        const preprocessedEvents = await this.runInstrumented('preprocessEvents', () => this.preprocessEvents(messages))
        const eventsPerDistinctId = this.groupEventsByDistinctId(
            preprocessedEvents.map((x) => ({ ...x.eventWithTeam, verified: x.verified }))
        )

        // Check if hogwatcher should be used (using the same sampling logic as in the transformer)
        const shouldRunHogWatcher = Math.random() < this.hub.CDP_HOG_WATCHER_SAMPLE_RATE
        if (shouldRunHogWatcher) {
            await this.fetchAndCacheHogFunctionStates(eventsPerDistinctId)
        }

        const personsStoreForBatch = this.personStore.forBatch()
        const groupStoreForBatch = this.groupStore.forBatch()
        await this.runInstrumented('processBatch', async () => {
            await Promise.all(
                Object.values(eventsPerDistinctId).map(async (events) => {
                    const eventsToProcess = this.redirectEvents(events)

                    return await this.runInstrumented('processEventsForDistinctId', () =>
                        this.processEventsForDistinctId(eventsToProcess, personsStoreForBatch, groupStoreForBatch)
                    )
                })
            )
        })

        const [_, personsStoreMessages] = await Promise.all([groupStoreForBatch.flush(), personsStoreForBatch.flush()])

        if (this.kafkaProducer) {
            await this.producePersonsStoreMessages(personsStoreMessages)
        }

        personsStoreForBatch.reportBatch()
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

    /**
     * Redirect events to overflow or testing topic based on their configuration
     * returning events that have not been redirected
     */
    private redirectEvents(eventsForDistinctId: EventsForDistinctId): EventsForDistinctId {
        if (!eventsForDistinctId.events.length) {
            return eventsForDistinctId
        }

        if (this.testingTopic) {
            void this.promiseScheduler.schedule(
                this.emitToTestingTopic(eventsForDistinctId.events.map((x) => x.message))
            )
            return {
                ...eventsForDistinctId,
                events: [],
            }
        }

        // NOTE: We know at this point that all these events are the same token distinct_id
        const token = eventsForDistinctId.token
        const distinctId = eventsForDistinctId.distinctId
        const kafkaTimestamp = eventsForDistinctId.events[0].message.timestamp
        const eventKey = `${token}:${distinctId}`

        // Check if this token is in the force overflow static/dynamic config list
        const shouldForceOverflow = this.shouldForceOverflow(token, distinctId)

        // Check the rate limiter and emit to overflow if necessary
        const isBelowRateLimit = this.overflowRateLimiter.consume(
            eventKey,
            eventsForDistinctId.events.length,
            kafkaTimestamp
        )

        if (this.overflowEnabled() && (shouldForceOverflow || !isBelowRateLimit)) {
            ingestionEventOverflowed.inc(eventsForDistinctId.events.length)

            if (shouldForceOverflow) {
                forcedOverflowEventsCounter.inc()
            } else if (this.ingestionWarningLimiter.consume(eventKey, eventsForDistinctId.events.length)) {
                logger.warn('🪣', `Local overflow detection triggered on key ${eventKey}`)
            }

            // NOTE: If we are forcing to overflow we typically want to keep the partition key
            // If the event is marked for skipping persons however locality doesn't matter so we would rather have the higher throughput
            // of random partitioning.
            const preserveLocality = shouldForceOverflow && !this.shouldSkipPerson(token, distinctId) ? true : undefined

            void this.promiseScheduler.schedule(
                this.emitToOverflow(
                    eventsForDistinctId.events.map((x) => x.message),
                    preserveLocality
                )
            )

            return {
                ...eventsForDistinctId,
                events: [],
            }
        }

        return eventsForDistinctId
    }

    /**
     * Fetches and caches hog function states for all teams in the batch
     */
    private async fetchAndCacheHogFunctionStates(parsedMessages: IncomingEventsByDistinctId): Promise<void> {
        await this.runInstrumented('fetchAndCacheHogFunctionStates', async () => {
            // Clear cached hog function states before fetching new ones
            this.hogTransformer.clearHogFunctionStates()

            const tokensToFetch = new Set<string>()
            Object.values(parsedMessages).forEach((eventsForDistinctId) => tokensToFetch.add(eventsForDistinctId.token))

            if (tokensToFetch.size === 0) {
                return // No teams to process
            }

            const teams = await this.hub.teamManager.getTeamsByTokens(Array.from(tokensToFetch))

            const teamIdsArray = Object.values(teams)
                .map((x) => x?.id)
                .filter(Boolean) as number[]

            // Get hog function IDs for transformations
            const teamHogFunctionIds = await this.hogTransformer['hogFunctionManager'].getHogFunctionIdsForTeams(
                teamIdsArray,
                ['transformation']
            )

            // Flatten all hog function IDs into a single array
            const allHogFunctionIds = Object.values(teamHogFunctionIds).flat()

            if (allHogFunctionIds.length > 0) {
                // Cache the hog function states
                await this.hogTransformer.fetchAndCacheHogFunctionStates(allHogFunctionIds)
            }
        })
    }

    private async processEventsForDistinctId(
        eventsForDistinctId: EventsForDistinctId,
        personsStoreForBatch: PersonsStoreForBatch,
        groupStoreForBatch: GroupStoreForBatch
    ): Promise<void> {
        const preprocessedEventsWithStores: PerDistinctIdPipelineInput[] = eventsForDistinctId.events.map(
            (incomingEvent) => {
                // Track $set usage in events that aren't known to use it, before ingestion adds anything there
                trackIfNonPersonEventUpdatesPersons(incomingEvent.event)
                return {
                    ...incomingEvent,
                    personsStoreForBatch,
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

    private groupEventsByDistinctId(
        messages: (IncomingEventWithTeam & { verified: JwtVerificationStatus })[]
    ): IncomingEventsByDistinctId {
        const groupedEvents: IncomingEventsByDistinctId = {}

        for (const eventWithTeam of messages) {
            const { message, event, team, headers, verified } = eventWithTeam
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

            groupedEvents[eventKey].events.push({ message, event, team, headers, verified })
        }

        return groupedEvents
    }

    private shouldSkipPerson(token?: string, distinctId?: string): boolean {
        if (!token) {
            return false
        }
        return this.eventIngestionRestrictionManager.shouldSkipPerson(token, distinctId)
    }

    private shouldForceOverflow(token?: string, distinctId?: string): boolean {
        if (!token) {
            return false
        }
        return this.eventIngestionRestrictionManager.shouldForceOverflow(token, distinctId)
    }

    private overflowEnabled(): boolean {
        return (
            !!this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC &&
            this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC !== this.topic &&
            !this.testingTopic
        )
    }

    private async emitToOverflow(kafkaMessages: Message[], preservePartitionLocalityOverride?: boolean): Promise<void> {
        const overflowTopic = this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC
        if (!overflowTopic) {
            throw new Error('No overflow topic configured')
        }

        ingestionOverflowingMessagesTotal.inc(kafkaMessages.length)

        const preservePartitionLocality =
            preservePartitionLocalityOverride !== undefined
                ? preservePartitionLocalityOverride
                : this.hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY

        await Promise.all(
            kafkaMessages.map((message) => {
                return this.kafkaOverflowProducer!.produce({
                    topic: this.overflowTopic!,
                    value: message.value,
                    // ``message.key`` should not be undefined here, but in the
                    // (extremely) unlikely event that it is, set it to ``null``
                    // instead as that behavior is safer.
                    key: preservePartitionLocality ? (message.key ?? null) : null,
                    headers: parseKafkaHeaders(message.headers),
                })
            })
        )
    }

    private async emitToTestingTopic(kafkaMessages: Message[]): Promise<void> {
        const testingTopic = this.testingTopic
        if (!testingTopic) {
            throw new Error('No testing topic configured')
        }

        await Promise.all(
            kafkaMessages.map((message) =>
                this.kafkaOverflowProducer!.produce({
                    topic: this.testingTopic!,
                    value: message.value,
                    key: message.key ?? null,
                    headers: parseKafkaHeaders(message.headers),
                })
            )
        )
    }
}
