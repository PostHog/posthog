import { Message, MessageHeader } from 'node-rdkafka'
import { Counter } from 'prom-client'
import { z } from 'zod'

import { PersonStoreManager } from '~/worker/ingestion/persons/person-store-manager'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { KafkaConsumer, parseKafkaHeaders } from '../kafka/consumer'
import { KafkaProducerWrapper } from '../kafka/producer'
import { ingestionOverflowingMessagesTotal } from '../main/ingestion-queues/batch-processing/metrics'
import {
    eventDroppedCounter,
    latestOffsetTimestampGauge,
    setUsageInNonPersonEventsCounter,
} from '../main/ingestion-queues/metrics'
import { runInstrumentedFunction } from '../main/utils'
import {
    Hub,
    IncomingEvent,
    IncomingEventWithTeam,
    KafkaConsumerBreadcrumb,
    KafkaConsumerBreadcrumbSchema,
    PipelineEvent,
    PluginServerService,
    PluginsServerConfig,
} from '../types'
import { normalizeEvent } from '../utils/event'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restriction-manager'
import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { retryIfRetriable } from '../utils/retries'
import { populateTeamDataStep } from '../worker/ingestion/event-pipeline/populateTeamDataStep'
import { EventPipelineResult, EventPipelineRunner } from '../worker/ingestion/event-pipeline/runner'
import { BatchWritingGroupStore } from '../worker/ingestion/groups/batch-writing-group-store'
import { GroupStoreForBatch } from '../worker/ingestion/groups/group-store-for-batch'
import { BatchWritingPersonsStore } from '../worker/ingestion/persons/batch-writing-person-store'
import { MeasuringPersonsStore } from '../worker/ingestion/persons/measuring-person-store'
import { PersonsStoreForBatch } from '../worker/ingestion/persons/persons-store-for-batch'
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
    events: IncomingEventWithTeam[]
}

type IncomingEventsByDistinctId = {
    [key: string]: EventsForDistinctId
}

const PERSON_EVENTS = new Set(['$set', '$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])
const KNOWN_SET_EVENTS = new Set([
    '$feature_interaction',
    '$feature_enrollment_update',
    'survey dismissed',
    'survey sent',
])

const trackIfNonPersonEventUpdatesPersons = (event: PipelineEvent) => {
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
    private personStoreManager: PersonStoreManager
    public groupStore: BatchWritingGroupStore
    private eventIngestionRestrictionManager: EventIngestionRestrictionManager
    public readonly promiseScheduler = new PromiseScheduler()

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

        const batchWritingPersonStore = new BatchWritingPersonsStore(this.hub.db, {
            dbWriteMode: this.hub.PERSON_BATCH_WRITING_DB_WRITE_MODE,
            maxConcurrentUpdates: this.hub.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.hub.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.hub.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        })
        const measuringPersonStore = new MeasuringPersonsStore(this.hub.db, {
            personCacheEnabledForUpdates: this.hub.PERSON_CACHE_ENABLED_FOR_UPDATES,
            personCacheEnabledForChecks: this.hub.PERSON_CACHE_ENABLED_FOR_CHECKS,
        })
        this.personStoreManager = new PersonStoreManager(this.hub, measuringPersonStore, batchWritingPersonStore)

        this.groupStore = new BatchWritingGroupStore(this.hub.db, {
            maxConcurrentUpdates: this.hub.GROUP_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
            maxOptimisticUpdateRetries: this.hub.GROUP_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
            optimisticUpdateRetryInterval: this.hub.GROUP_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        })

        this.kafkaConsumer = new KafkaConsumer({ groupId: this.groupId, topic: this.topic })
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

        await this.kafkaConsumer.connect(async (messages) => {
            return await runInstrumentedFunction({
                statsKey: `ingestionConsumer.handleEachBatch`,
                sendException: false,
                func: async () => await this.handleKafkaBatch(messages),
            })
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

    public isHealthy() {
        return this.kafkaConsumer?.isHealthy()
    }

    private runInstrumented<T>(name: string, func: () => Promise<T>): Promise<T> {
        return runInstrumentedFunction<T>({ statsKey: `ingestionConsumer.${name}`, func })
    }

    private createBreadcrumb(message: Message): KafkaConsumerBreadcrumb {
        return {
            topic: message.topic,
            partition: message.partition,
            offset: message.offset,
            processed_at: new Date().toISOString(),
            consumer_id: this.groupId,
        }
    }

    private getExistingBreadcrumbsFromHeaders(message: Message): KafkaConsumerBreadcrumb[] {
        const existingBreadcrumbs: KafkaConsumerBreadcrumb[] = []
        if (message.headers) {
            for (const header of message.headers) {
                if ('kafka-consumer-breadcrumbs' in header) {
                    try {
                        const headerValue = header['kafka-consumer-breadcrumbs']
                        const valueString = headerValue instanceof Buffer ? headerValue.toString() : headerValue
                        const parsedValue = parseJSON(valueString)
                        if (Array.isArray(parsedValue)) {
                            const validatedBreadcrumbs = z.array(KafkaConsumerBreadcrumbSchema).safeParse(parsedValue)
                            if (validatedBreadcrumbs.success) {
                                existingBreadcrumbs.push(...validatedBreadcrumbs.data)
                            } else {
                                logger.warn('Failed to validated breadcrumbs array from header', {
                                    error: validatedBreadcrumbs.error.format(),
                                })
                            }
                        } else {
                            const validatedBreadcrumb = KafkaConsumerBreadcrumbSchema.safeParse(parsedValue)
                            if (validatedBreadcrumb.success) {
                                existingBreadcrumbs.push(validatedBreadcrumb.data)
                            } else {
                                logger.warn('Failed to validate breadcrumb from header', {
                                    error: validatedBreadcrumb.error.format(),
                                })
                            }
                        }
                    } catch (e) {
                        logger.warn('Failed to parse breadcrumb from header', { error: e })
                    }
                }
            }
        }

        return existingBreadcrumbs
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

        const parsedMessages = await this.runInstrumented('parseKafkaMessages', () => this.parseKafkaBatch(messages))

        const eventsWithTeams = await this.runInstrumented('resolveTeams', async () => {
            return this.resolveTeams(parsedMessages)
        })

        const postCookielessMessages = await this.hub.cookielessManager.doBatch(eventsWithTeams)

        const groupedMessages = this.groupEventsByDistinctId(postCookielessMessages)

        // Check if hogwatcher should be used (using the same sampling logic as in the transformer)
        const shouldRunHogWatcher = Math.random() < this.hub.CDP_HOG_WATCHER_SAMPLE_RATE

        // Get hog function IDs for all teams and cache function states only if hogwatcher is enabled
        if (shouldRunHogWatcher) {
            await this.fetchAndCacheHogFunctionStates(groupedMessages)
        }

        const personsStoreForBatch = this.personStoreManager.forBatch()
        const groupStoreForBatch = this.groupStore.forBatch()
        await this.runInstrumented('processBatch', async () => {
            await Promise.all(
                Object.values(groupedMessages).map(async (events) => {
                    const eventsToProcess = this.redirectEvents(events)

                    return await this.runInstrumented('processEventsForDistinctId', () =>
                        this.processEventsForDistinctId(eventsToProcess, personsStoreForBatch, groupStoreForBatch)
                    )
                })
            )
        })

        const [_, personsStoreMessages] = await Promise.all([groupStoreForBatch.flush(), personsStoreForBatch.flush()])

        if (personsStoreMessages.length > 0 && this.kafkaProducer) {
            await this.kafkaProducer.queueMessages(personsStoreMessages)
            await this.kafkaProducer.flush()
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
        // Process every message sequentially, stash promises to await on later
        for (const incomingEvent of eventsForDistinctId.events) {
            // Track $set usage in events that aren't known to use it, before ingestion adds anything there
            trackIfNonPersonEventUpdatesPersons(incomingEvent.event)
            await this.runEventRunnerV1(incomingEvent, personsStoreForBatch, groupStoreForBatch)
        }
    }

    private async runEventRunnerV1(
        incomingEvent: IncomingEventWithTeam,
        personsStoreForBatch: PersonsStoreForBatch,
        groupStoreForBatch: GroupStoreForBatch
    ): Promise<EventPipelineResult | undefined> {
        const { event, message, team } = incomingEvent

        const existingBreadcrumbs = this.getExistingBreadcrumbsFromHeaders(message)
        const currentBreadcrumb = this.createBreadcrumb(message)
        const allBreadcrumbs = existingBreadcrumbs.concat(currentBreadcrumb)

        try {
            const result = await this.runInstrumented('runEventPipeline', () =>
                retryIfRetriable(async () => {
                    const runner = this.getEventPipelineRunnerV1(
                        event,
                        allBreadcrumbs,
                        personsStoreForBatch,
                        groupStoreForBatch
                    )
                    return await runner.runEventPipeline(event, team)
                })
            )

            // This contains the Kafka producer ACKs & message promises, to avoid blocking after every message.
            result.ackPromises?.forEach((promise) => {
                void this.promiseScheduler.schedule(
                    promise.catch(async (error) => {
                        await this.handleProcessingErrorV1(error, message, event)
                    })
                )
            })

            return result
        } catch (error) {
            await this.handleProcessingErrorV1(error, message, event)
        }
    }

    private async handleProcessingErrorV1(error: any, message: Message, event: PipelineEvent) {
        logger.error('🔥', `Error processing message`, {
            stack: error.stack,
            error: error,
        })

        // If the error is a non-retriable error, push to the dlq and commit the offset. Else raise the
        // error.
        //
        // NOTE: there is behavior to push to a DLQ at the moment within EventPipelineRunner. This
        // doesn't work so well with e.g. messages that when sent to the DLQ is it's self too large.
        // Here we explicitly do _not_ add any additional metadata to the message. We might want to add
        // some metadata to the message e.g. in the header or reference e.g. the event id.
        //
        // TODO: properly abstract out this `isRetriable` error logic. This is currently relying on the
        // fact that node-rdkafka adheres to the `isRetriable` interface.

        if (error?.isRetriable === false) {
            captureException(error)
            try {
                await this.kafkaProducer!.produce({
                    topic: this.dlqTopic,
                    value: message.value,
                    key: message.key ?? null, // avoid undefined, just to be safe
                    headers: {
                        'event-id': event.uuid,
                    },
                })
            } catch (error) {
                // If we can't send to the DLQ and it's not retriable, just continue. We'll commit the
                // offset and move on.
                if (error?.isRetriable === false) {
                    logger.error('🔥', `Error pushing to DLQ`, {
                        stack: error.stack,
                        error: error,
                    })
                    return
                }

                // If we can't send to the DLQ and it is retriable, raise the error.
                throw error
            }
        } else {
            throw error
        }
    }

    private getEventPipelineRunnerV1(
        event: PipelineEvent,
        breadcrumbs: KafkaConsumerBreadcrumb[] = [],
        personsStoreForBatch: PersonsStoreForBatch,
        groupStoreForBatch: GroupStoreForBatch
    ): EventPipelineRunner {
        return new EventPipelineRunner(
            this.hub,
            event,
            this.hogTransformer,
            breadcrumbs,
            personsStoreForBatch,
            groupStoreForBatch
        )
    }

    private parseKafkaBatch(messages: Message[]): Promise<IncomingEvent[]> {
        const batch: IncomingEvent[] = []

        for (const message of messages) {
            let distinctId: string | undefined
            let token: string | undefined

            // Parse the headers so we can early exit if found and should be dropped
            message.headers?.forEach((header) => {
                if (header.key === 'distinct_id') {
                    distinctId = header.value.toString()
                }
                if (header.key === 'token') {
                    token = header.value.toString()
                }
            })

            if (this.shouldDropEvent(token, distinctId)) {
                this.logDroppedEvent(token, distinctId)
                continue
            }

            // Parse the message payload into the event object
            const { data: dataStr, ...rawEvent } = parseJSON(message.value!.toString())
            const combinedEvent: PipelineEvent = { ...parseJSON(dataStr), ...rawEvent }
            const event: PipelineEvent = normalizeEvent({
                ...combinedEvent,
            })

            // In case the headers were not set we check the parsed message now
            if (this.shouldDropEvent(combinedEvent.token, combinedEvent.distinct_id)) {
                this.logDroppedEvent(combinedEvent.token, combinedEvent.distinct_id)
                continue
            }

            if (this.shouldSkipPerson(event.token, event.distinct_id)) {
                event.properties = {
                    ...(event.properties ?? {}),
                    $process_person_profile: false,
                }
            }

            batch.push({ message, event })
        }

        return Promise.resolve(batch)
    }

    private groupEventsByDistinctId(messages: IncomingEventWithTeam[]) {
        const batches: IncomingEventsByDistinctId = {}
        for (const { event, message, team } of messages) {
            const token = event.token ?? ''
            const distinctId = event.distinct_id ?? ''
            const eventKey = `${token}:${distinctId}`

            // We collect the events grouped by token and distinct_id so that we can process batches in parallel whilst keeping the order of events
            // for a given distinct_id
            if (!batches[eventKey]) {
                batches[eventKey] = {
                    token: token,
                    distinctId,
                    events: [],
                }
            }

            batches[eventKey].events.push({ message, event, team })
        }
        return batches
    }

    private async resolveTeams(messages: IncomingEvent[]): Promise<IncomingEventWithTeam[]> {
        const resolvedMessages: IncomingEventWithTeam[] = []
        for (const { event, message } of messages) {
            const result = await populateTeamDataStep(this.hub, event)
            if (!result) {
                continue
            }
            resolvedMessages.push({
                event: result.event,
                team: result.team,
                message,
            })
        }
        return resolvedMessages
    }

    private logDroppedEvent(token?: string, distinctId?: string) {
        logger.debug('🔁', `Dropped event`, {
            token,
            distinctId,
        })
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'blocked_token',
            })
            .inc()
    }

    private shouldDropEvent(token?: string, distinctId?: string) {
        if (!token) {
            return false
        }
        return this.eventIngestionRestrictionManager.shouldDropEvent(token, distinctId)
    }

    private shouldSkipPerson(token?: string, distinctId?: string) {
        if (!token) {
            return false
        }
        return this.eventIngestionRestrictionManager.shouldSkipPerson(token, distinctId)
    }

    private shouldForceOverflow(token?: string, distinctId?: string) {
        if (!token) {
            return false
        }
        return this.eventIngestionRestrictionManager.shouldForceOverflow(token, distinctId)
    }

    private overflowEnabled() {
        return (
            !!this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC &&
            this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC !== this.topic &&
            !this.testingTopic
        )
    }

    private async emitToOverflow(kafkaMessages: Message[], preservePartitionLocalityOverride?: boolean) {
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
                const headers: MessageHeader[] = message.headers ?? []
                const existingBreadcrumbs = this.getExistingBreadcrumbsFromHeaders(message)
                const breadcrumb = this.createBreadcrumb(message)
                const allBreadcrumbs = [...existingBreadcrumbs, breadcrumb]
                headers.push({
                    'kafka-consumer-breadcrumbs': Buffer.from(JSON.stringify(allBreadcrumbs)),
                })
                return this.kafkaOverflowProducer!.produce({
                    topic: this.overflowTopic!,
                    value: message.value,
                    // ``message.key`` should not be undefined here, but in the
                    // (extremely) unlikely event that it is, set it to ``null``
                    // instead as that behavior is safer.
                    key: preservePartitionLocality ? message.key ?? null : null,
                    headers: parseKafkaHeaders(headers),
                })
            })
        )
    }

    private async emitToTestingTopic(kafkaMessages: Message[]) {
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
