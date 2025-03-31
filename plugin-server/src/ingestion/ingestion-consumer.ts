import { Message, MessageHeader } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { HogWatcherService } from '../cdp/services/hog-watcher.service'
import { HogFunctionManagerService } from '../cdp/services/hog-function-manager.service'
import { createCdpRedisPool } from '../cdp/redis'
import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../kafka/config'
import { KafkaProducerWrapper } from '../kafka/producer'
import { IngestionOverflowMode } from '../main/ingestion-queues/batch-processing/each-batch-ingestion'
import { ingestionOverflowingMessagesTotal } from '../main/ingestion-queues/batch-processing/metrics'
import { addSentryBreadcrumbsEventListeners } from '../main/ingestion-queues/kafka-metrics'
import {
    eventDroppedCounter,
    ingestionPartitionKeyOverflowed,
    latestOffsetTimestampGauge,
    setUsageInNonPersonEventsCounter,
} from '../main/ingestion-queues/metrics'
import { runInstrumentedFunction } from '../main/utils'
import { Hub, PipelineEvent, PluginServerService, PluginsServerConfig } from '../types'
import { normalizeEvent } from '../utils/event'
import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { retryIfRetriable } from '../utils/retries'
import { EventPipelineResult, EventPipelineRunner } from '../worker/ingestion/event-pipeline/runner'
import { MemoryRateLimiter } from './utils/overflow-detector'
import { HogFunctionInvocationResult, HogFunctionType } from '../cdp/types'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

const histogramKafkaBatchSize = new Histogram({
    name: 'ingestion_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

const histogramKafkaBatchSizeKb = new Histogram({
    name: 'ingestion_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity],
})

const forcedOverflowEventsCounter = new Counter({
    name: 'ingestion_forced_overflow_events_total',
    help: 'Number of events that were routed to overflow because they matched the force overflow tokens list',
})

// Add metrics for hogwatcher batch operations
const transformEventBatchWatcherLatency = new Histogram({
    name: 'transform_event_batch_watcher_latency_seconds',
    help: 'Time spent in HogWatcher batch operations in seconds for batch transformEvent',
    labelNames: ['operation'],
})

type IncomingEvent = { message: Message; event: PipelineEvent }

type IncomingEventsByDistinctId = {
    [key: string]: IncomingEvent[]
}

const PERSON_EVENTS = new Set(['$set', '$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])
const KNOWN_SET_EVENTS = new Set([
    '$feature_interaction',
    '$feature_enrollment_update',
    'survey dismissed',
    'survey sent',
])

export class IngestionConsumer {
    protected name = 'ingestion-consumer'
    protected groupId: string
    protected topic: string
    protected dlqTopic: string
    protected overflowTopic?: string
    protected testingTopic?: string

    batchConsumer?: BatchConsumer
    isStopping = false
    protected heartbeat = () => {}
    protected promises: Set<Promise<any>> = new Set()
    protected kafkaProducer?: KafkaProducerWrapper
    protected kafkaOverflowProducer?: KafkaProducerWrapper
    public hogTransformer: HogTransformerService
    private overflowRateLimiter: MemoryRateLimiter
    private ingestionWarningLimiter: MemoryRateLimiter
    private tokensToDrop: string[] = []
    private tokenDistinctIdsToDrop: string[] = []
    private tokensToForceOverflow: string[] = []

    // Track batch invocation results
    private batchInvocationResults: HogFunctionInvocationResult[] = []
    private hogWatcher: HogWatcherService
    private hogFunctionManager: HogFunctionManagerService

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
        this.tokensToDrop = hub.DROP_EVENTS_BY_TOKEN.split(',').filter((x) => !!x)
        this.tokenDistinctIdsToDrop = hub.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)
        this.tokensToForceOverflow = hub.INGESTION_FORCE_OVERFLOW_TOKENS.split(',').filter((x) => !!x)
        this.testingTopic = overrides.INGESTION_CONSUMER_TESTING_TOPIC ?? hub.INGESTION_CONSUMER_TESTING_TOPIC

        this.name = `ingestion-consumer-${this.topic}`
        this.overflowRateLimiter = new MemoryRateLimiter(
            this.hub.EVENT_OVERFLOW_BUCKET_CAPACITY,
            this.hub.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE
        )

        this.ingestionWarningLimiter = new MemoryRateLimiter(1, 1.0 / 3600)
        this.hogTransformer = new HogTransformerService(hub)
        this.hogWatcher = new HogWatcherService(hub, createCdpRedisPool(hub))
        this.hogFunctionManager = new HogFunctionManagerService(hub)
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
            batchConsumer: this.batchConsumer,
        }
    }

    public async start(): Promise<void> {
        await Promise.all([
            this.hogTransformer.start(),
            this.hogFunctionManager.start(),
            KafkaProducerWrapper.create(this.hub).then((producer) => {
                this.kafkaProducer = producer
                this.kafkaProducer.producer.connect()
            }),
            // TRICKY: When we produce overflow events they are back to the kafka we are consuming from
            KafkaProducerWrapper.create(this.hub, 'consumer').then((producer) => {
                this.kafkaOverflowProducer = producer
                this.kafkaOverflowProducer.producer.connect()
            }),
            this.startKafkaConsumer({
                topic: this.topic,
                groupId: this.groupId,
                handleBatch: async (messages) => this.handleKafkaBatch(messages),
            }),
        ])
    }

    public async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        logger.info('🔁', `${this.name} - stopping batch consumer`)
        await this.batchConsumer?.stop()
        logger.info('🔁', `${this.name} - stopping kafka producer`)
        await this.kafkaProducer?.disconnect()
        logger.info('🔁', `${this.name} - stopping kafka overflow producer`)
        await this.kafkaOverflowProducer?.disconnect()
        logger.info('🔁', `${this.name} - stopping hog function manager`)
        await this.hogFunctionManager.stop()
        logger.info('🔁', `${this.name} - stopping hog transformer`)
        await this.hogTransformer.stop()
        logger.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy() {
        return this.batchConsumer?.isHealthy()
    }

    private scheduleWork<T>(promise: Promise<T>): Promise<T> {
        this.promises.add(promise)
        void promise.finally(() => this.promises.delete(promise))
        return promise
    }

    private runInstrumented<T>(name: string, func: () => Promise<T>): Promise<T> {
        return runInstrumentedFunction<T>({ statsKey: `ingestionConsumer.${name}`, func })
    }

    public async handleKafkaBatch(messages: Message[]) {
        const parsedMessages = await this.runInstrumented('parseKafkaMessages', () => this.parseKafkaBatch(messages))

        // Extract team IDs from the batch for gathering team hog functions
        const teamIds = new Set<number>()
        Object.values(parsedMessages).forEach(events => {
            events.forEach(({ event }) => {
                if (event.team_id) {
                    teamIds.add(event.team_id)
                }
            })
        })

        // Fetch all transformation functions and their states for all teams in the batch
        const filteredTeamHogFunctionsMap: Record<number, HogFunctionType[]> = {}
        
        await this.runInstrumented('fetchAndFilterTransformationFunctions', async () => {
            // Get all function IDs across all teams first
            const teamToFunctionsMap: Record<number, HogFunctionType[]> = {}
            const allFunctionIds: string[] = []
            
            // Step 1: Fetch all functions for all teams
            await Promise.all(
                [...teamIds].map(async (teamId) => {
                    const teamHogFunctions = await this.hogFunctionManager.getHogFunctionsForTeam(
                        teamId, 
                        ['transformation']
                    )
                    teamToFunctionsMap[teamId] = teamHogFunctions
                    teamHogFunctions.forEach(fn => allFunctionIds.push(fn.id))
                })
            )
            
            // Step 2: Get all function states in one batch
            const functionStates = allFunctionIds.length > 0 
                ? await this.getHogWatcherStates(allFunctionIds) 
                : {}
            
            // Step 3: Filter out disabled functions for each team
            for (const teamId of teamIds) {
                const teamFunctions = teamToFunctionsMap[teamId] || []
                const enabledFunctions = teamFunctions.filter(fn => {
                    const state = functionStates[fn.id]?.state
                    const isEnabled = !state || state < 2 // Not disabled if state is undefined or < 2
                    
                    if (!isEnabled) {
                        logger.info('🧪', 'Skipping disabled transformation', {
                            function_id: fn.id,
                            function_name: fn.name,
                            team_id: teamId,
                            state
                        })
                    }
                    
                    return isEnabled
                })
                
                filteredTeamHogFunctionsMap[teamId] = enabledFunctions
            }
        })

        await this.runInstrumented('processBatch', async () => {
            await Promise.all(
                Object.values(parsedMessages).map(async (x) => {
                    return await this.runInstrumented('processEventsForDistinctId', () => 
                        this.processEventsForDistinctId(x, filteredTeamHogFunctionsMap)
                    )
                })
            )
        })

        logger.debug('🔁', `Waiting for promises`, { promises: this.promises.size })
        await this.runInstrumented('awaitScheduledWork', () => Promise.all(this.promises))
        logger.debug('🔁', `Processed batch`)

        // Process hogwatcher observations in batch after all events are processed
        await this.runInstrumented('processHogWatcherObservations', async () => {
            await this.processHogWatcherObservationsBatch()
        })

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: this.groupId })
                    .set(message.timestamp)
            }
        }
    }

    private async processEventsForDistinctId(
        incomingEvents: IncomingEvent[], 
        teamHogFunctionsMap: Record<number, HogFunctionType[]>
    ): Promise<void> {
        // Process every message sequentially, stash promises to await on later
        for (const { message, event } of incomingEvents) {
            // Track $set usage in events that aren't known to use it, before ingestion adds anything there
            if (
                event.properties &&
                !PERSON_EVENTS.has(event.event) &&
                !KNOWN_SET_EVENTS.has(event.event) &&
                ('$set' in event.properties || '$set_once' in event.properties || '$unset' in event.properties)
            ) {
                setUsageInNonPersonEventsCounter.inc()
            }

            try {
                logger.debug('🔁', `Processing event`, {
                    event,
                })

                if (this.testingTopic) {
                    void this.scheduleWork(this.emitToTestingTopic([message]))
                    continue
                }

                const eventKey = `${event.token}:${event.distinct_id}`
                // Check if this token is in the force overflow list
                const shouldForceOverflow = event.token && this.tokensToForceOverflow.includes(event.token)

                // Check the rate limiter and emit to overflow if necessary
                const isBelowRateLimit = this.overflowRateLimiter.consume(eventKey, 1, message.timestamp)

                if (this.overflowEnabled() && (shouldForceOverflow || !isBelowRateLimit)) {
                    logger.debug('🔁', `Sending to overflow`, {
                        event,
                        reason: shouldForceOverflow ? 'force_overflow_token' : 'rate_limit',
                    })
                    ingestionPartitionKeyOverflowed.labels(`${event.team_id ?? event.token}`).inc()

                    if (shouldForceOverflow) {
                        forcedOverflowEventsCounter.inc()
                    } else if (this.ingestionWarningLimiter.consume(eventKey, 1)) {
                        logger.warn('🪣', `Local overflow detection triggered on key ${eventKey}`)
                    }

                    void this.scheduleWork(this.emitToOverflow([message], shouldForceOverflow ? true : undefined))
                    continue
                }

                // Get team hog functions (already pre-filtered in handleKafkaBatch)
                const teamHogFunctions = teamHogFunctionsMap[event.team_id || -1] || []
                
                // Pass the pre-fetched and filtered team hog functions to the event pipeline
                const result = await this.runInstrumented('runEventPipeline', () => 
                    this.runEventPipeline(event, teamHogFunctions)
                )

                logger.debug('🔁', `Processed event`, {
                    event,
                })

                // This contains the Kafka producer ACKs & message promises, to avoid blocking after every message.
                result.ackPromises?.forEach((promise) => {
                    void this.scheduleWork(
                        promise.catch(async (error) => {
                            await this.handleProcessingError(error, message, event)
                        })
                    )
                })
            } catch (error) {
                await this.handleProcessingError(error, message, event)
            }
        }
    }

    private async runEventPipeline(
        event: PipelineEvent, 
        teamHogFunctions: HogFunctionType[] = []
    ): Promise<EventPipelineResult> {
        return await retryIfRetriable(async () => {
            const runner = new EventPipelineRunner(this.hub, event, this.hogTransformer)
            
            // Just pass the pre-filtered hog functions directly to runEventPipeline
            const result = await runner.runEventPipeline(event, teamHogFunctions);
            
            // Extract any invocation results from the transformation that need to be observed
            const { invocationResults } = await this.extractInvocationResults(result);
            if (invocationResults && invocationResults.length > 0) {
                this.addToBatchObservations(invocationResults);
            }
            
            return result;
        })
    }
    
    // Helper method to extract invocation results from pipeline result
    private async extractInvocationResults(result: EventPipelineResult): Promise<{ invocationResults: HogFunctionInvocationResult[] }> {
        // Return invocation results from the pipeline result if they exist
        return { 
            invocationResults: result.invocationResults || [] 
        };
    }

    private parseKafkaBatch(messages: Message[]): Promise<IncomingEventsByDistinctId> {
        const batches: IncomingEventsByDistinctId = {}

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

            const eventKey = `${event.token}:${event.distinct_id}`

            // We collect the events grouped by token and distinct_id so that we can process batches in parallel whilst keeping the order of events
            // for a given distinct_id
            if (!batches[eventKey]) {
                batches[eventKey] = []
            }

            batches[eventKey].push({ message, event })
        }

        return Promise.resolve(batches)
    }

    private async startKafkaConsumer(options: {
        topic: string
        groupId: string
        handleBatch: (messages: Message[]) => Promise<void>
    }): Promise<void> {
        this.batchConsumer = await startBatchConsumer({
            ...options,
            connectionConfig: createRdConnectionConfigFromEnvVars(this.hub, 'consumer'),
            autoCommit: true,
            sessionTimeout: this.hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
            maxPollIntervalMs: this.hub.KAFKA_CONSUMPTION_MAX_POLL_INTERVAL_MS,
            consumerMaxBytes: this.hub.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.hub.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            consumerMaxWaitMs: this.hub.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: this.hub.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            fetchBatchSize: this.hub.INGESTION_BATCH_SIZE,
            batchingTimeoutMs: this.hub.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicCreationTimeoutMs: this.hub.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            topicMetadataRefreshInterval: this.hub.KAFKA_TOPIC_METADATA_REFRESH_INTERVAL_MS,
            eachBatch: async (messages, { heartbeat }) => {
                logger.info('🔁', `${this.name} - handling batch`, {
                    size: messages.length,
                })

                this.heartbeat = heartbeat

                histogramKafkaBatchSize.observe(messages.length)
                histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                return await runInstrumentedFunction({
                    statsKey: `ingestionConsumer.handleEachBatch`,
                    sendTimeoutGuardToSentry: false,
                    func: async () => {
                        await options.handleBatch(messages)
                    },
                })
            },
            callEachBatchWhenEmpty: false,
        })

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            if (this.isStopping) {
                return
            }
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            logger.info('🔁', `${this.name} batch consumer disconnected, cleaning up`, { err })
            await this.stop()
        })
    }

    private async handleProcessingError(error: any, message: Message, event: PipelineEvent) {
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
        // some metadata to the message e.g. in the header or reference e.g. the sentry event id.
        //
        // TODO: property abstract out this `isRetriable` error logic. This is currently relying on the
        // fact that node-rdkafka adheres to the `isRetriable` interface.

        if (error?.isRetriable === false) {
            const sentryEventId = captureException(error)
            const headers: MessageHeader[] = message.headers ?? []
            headers.push({ ['sentry-event-id']: sentryEventId })
            headers.push({ ['event-id']: event.uuid })
            try {
                await this.kafkaProducer!.produce({
                    topic: this.dlqTopic,
                    value: message.value,
                    key: message.key ?? null, // avoid undefined, just to be safe
                    headers: headers,
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
        return (
            (token && this.tokensToDrop.includes(token)) ||
            (token && distinctId && this.tokenDistinctIdsToDrop.includes(`${token}:${distinctId}`))
        )
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
        const overflowMode = preservePartitionLocality
            ? IngestionOverflowMode.Reroute
            : IngestionOverflowMode.RerouteRandomly

        const useRandomPartitioning = overflowMode === IngestionOverflowMode.RerouteRandomly

        await Promise.all(
            kafkaMessages.map((message) =>
                this.kafkaOverflowProducer!.produce({
                    topic: this.overflowTopic!,
                    value: message.value,
                    // ``message.key`` should not be undefined here, but in the
                    // (extremely) unlikely event that it is, set it to ``null``
                    // instead as that behavior is safer.
                    key: useRandomPartitioning ? null : message.key ?? null,
                    headers: message.headers,
                })
            )
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
                    headers: message.headers,
                })
            )
        )
    }

    /**
     * Gets HogWatcher states for multiple function IDs at once
     * @param functionIds Array of function IDs to get states for
     * @returns Record of function ID to watcher state
     */
    private async getHogWatcherStates(functionIds: string[]): Promise<Record<string, { state: number }>> {
        if (!functionIds.length) {
            return {}
        }
        
        const timer = transformEventBatchWatcherLatency.startTimer({ operation: 'getStates' })
        try {
            // Access hogWatcher directly
            return await this.hogWatcher.getStates(functionIds)
        } catch (error) {
            logger.warn('⚠️', 'HogWatcher getStates failed', { error })
            return {}
        } finally {
            timer()
        }
    }
    
    /**
     * Adds invocation results to the batch for later processing by hogwatcher
     * @param results Invocation results to add to the batch
     */
    public addToBatchObservations(results: HogFunctionInvocationResult[]): void {
        if (results.length > 0) {
            this.batchInvocationResults.push(...results)
        }
    }
    
    /**
     * Processes all accumulated batch observations in a single hogwatcher operation
     */
    private async processHogWatcherObservationsBatch(): Promise<void> {
        if (!this.batchInvocationResults.length) {
            return
        }
        
        const timer = transformEventBatchWatcherLatency.startTimer({ operation: 'observeResults' })
        try {
            // Access hogWatcher directly
            await this.hogWatcher.observeResults(this.batchInvocationResults)
        } catch (error) {
            logger.warn('⚠️', 'HogWatcher batch observeResults failed', { error })
        } finally {
            timer()
            // Clear the batch after processing
            this.batchInvocationResults = []
        }
    }
}
