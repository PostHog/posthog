import { cloneDeep } from 'lodash'
import { Message, MessageHeader } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'
import { z } from 'zod'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../kafka/config'
import { KafkaProducerWrapper } from '../kafka/producer'
import { ingestionOverflowingMessagesTotal } from '../main/ingestion-queues/batch-processing/metrics'
import { addSentryBreadcrumbsEventListeners } from '../main/ingestion-queues/kafka-metrics'
import {
    eventDroppedCounter,
    latestOffsetTimestampGauge,
    setUsageInNonPersonEventsCounter,
} from '../main/ingestion-queues/metrics'
import { runInstrumentedFunction } from '../main/utils'
import {
    Hub,
    KafkaConsumerBreadcrumb,
    KafkaConsumerBreadcrumbSchema,
    PipelineEvent,
    PluginServerService,
    PluginsServerConfig,
    RawKafkaEvent,
} from '../types'
import { normalizeEvent } from '../utils/event'
import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { retryIfRetriable } from '../utils/retries'
import { UUIDT } from '../utils/utils'
import { EventPipelineResult, EventPipelineRunner } from '../worker/ingestion/event-pipeline/runner'
import { EventDroppedError, EventPipelineRunnerV2 } from './event-pipeline-runner/event-pipeline-runner'
import { MemoryRateLimiter } from './utils/overflow-detector'
// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

const ingestionEventOverflowed = new Counter({
    name: 'ingestion_event_overflowed',
    help: 'Indicates that a given event has overflowed capacity and been redirected to a different topic.',
})

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

const eventProcessorComparison = new Counter({
    name: 'event_processor_comparison',
    help: 'Count of compared events for the new ingester',
    labelNames: ['outcome'],
})

type IncomingEvent = { message: Message; event: PipelineEvent }

type EventsForDistinctId = {
    token: string
    distinctId: string
    events: IncomingEvent[]
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

    batchConsumer?: BatchConsumer
    isStopping = false
    protected heartbeat = () => {}
    protected promises: Set<Promise<any>> = new Set()
    protected kafkaProducer?: KafkaProducerWrapper
    protected kafkaOverflowProducer?: KafkaProducerWrapper
    public hogTransformer: HogTransformerService
    private overflowRateLimiter: MemoryRateLimiter
    private ingestionWarningLimiter: MemoryRateLimiter
    private tokenDistinctIdsToDrop: string[] = []
    private tokenDistinctIdsToSkipPersons: string[] = []
    private tokenDistinctIdsToForceOverflow: string[] = []
    private comparisonV2Percentage: number

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
        this.testingTopic = overrides.INGESTION_CONSUMER_TESTING_TOPIC ?? hub.INGESTION_CONSUMER_TESTING_TOPIC

        this.name = `ingestion-consumer-${this.topic}`
        this.overflowRateLimiter = new MemoryRateLimiter(
            this.hub.EVENT_OVERFLOW_BUCKET_CAPACITY,
            this.hub.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE
        )

        this.ingestionWarningLimiter = new MemoryRateLimiter(1, 1.0 / 3600)
        this.hogTransformer = new HogTransformerService(hub)

        this.comparisonV2Percentage = hub.INGESTION_CONSUMER_V2_COMPARISON_PERCENTAGE ?? 0

        if (this.comparisonV2Percentage < 0 || this.comparisonV2Percentage > 1) {
            throw new Error('Invalid value for INGESTION_CONSUMER_V2_COMPARISON_PERCENTAGE - must be between 0 and 1')
        }
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

    public async handleKafkaBatch(messages: Message[]) {
        const parsedMessages = await this.runInstrumented('parseKafkaMessages', () => this.parseKafkaBatch(messages))

        // Check if hogwatcher should be used (using the same sampling logic as in the transformer)
        const shouldRunHogWatcher = Math.random() < this.hub.CDP_HOG_WATCHER_SAMPLE_RATE

        // Get hog function IDs for all teams and cache function states only if hogwatcher is enabled
        if (shouldRunHogWatcher) {
            await this.fetchAndCacheHogFunctionStates(parsedMessages)
        }

        await this.runInstrumented('processBatch', async () => {
            await Promise.all(
                Object.values(parsedMessages).map(async (events) => {
                    const eventsToProcess = this.redirectEvents(events)

                    return await this.runInstrumented('processEventsForDistinctId', () =>
                        this.processEventsForDistinctId(eventsToProcess)
                    )
                })
            )
        })

        logger.debug('🔁', `Waiting for promises`, { promises: this.promises.size })
        await this.runInstrumented('awaitScheduledWork', () => Promise.all(this.promises))
        logger.debug('🔁', `Processed batch`)

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: this.groupId })
                    .set(message.timestamp)
            }
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
            void this.scheduleWork(this.emitToTestingTopic(eventsForDistinctId.events.map((x) => x.message)))
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

        // Check if this token is in the force overflow list
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

            void this.scheduleWork(
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

            const teams = await this.hub.teamManagerLazy.getTeamsByTokens(Array.from(tokensToFetch))

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

    private async processEventsForDistinctId(eventsForDistinctId: EventsForDistinctId): Promise<void> {
        // Process every message sequentially, stash promises to await on later
        for (const incomingEvent of eventsForDistinctId.events) {
            // Track $set usage in events that aren't known to use it, before ingestion adds anything there
            trackIfNonPersonEventUpdatesPersons(incomingEvent.event)

            if (this.comparisonV2Percentage && Math.random() < this.comparisonV2Percentage) {
                let v1Result: RawKafkaEvent | undefined
                let v2Result: RawKafkaEvent | undefined
                let v1Error: unknown | undefined
                let v2Error: unknown | undefined

                try {
                    // NOTE: This is not ideal but we are cloning the event to ensure we don't accidentally modify it
                    const clonedEvent = cloneDeep(incomingEvent.event)
                    v2Result = await this.runEventRunnerV2({
                        event: clonedEvent,
                        message: incomingEvent.message,
                    })
                } catch (e) {
                    v2Error = e
                }

                try {
                    const result = await this.runEventRunnerV1(incomingEvent)

                    if (result?.lastStep === 'emitEventStep') {
                        // TRICKY: The rawKafkaEvent is passed here. The API is weird but given we are replacing it we're not changing anything here
                        v1Result = result.args[0] as any
                    }
                } catch (e) {
                    v1Error = e
                }

                try {
                    this.compareResults(v1Result, v2Result, v1Error, v2Error)
                } catch (e) {
                    logger.warn('[IngestionConsumer] comparison failed')
                }

                if (v1Error) {
                    // We want to rethrow the error of the existing processor if it errored here
                    throw v1Error
                }

                continue
            }

            // If not comparing we just run it
            await this.runEventRunnerV1(incomingEvent)
        }
    }

    private compareResults(v1Result?: RawKafkaEvent, v2Result?: RawKafkaEvent, v1Error?: unknown, v2Error?: unknown) {
        // NOTE: Here we will do a simple comparison to start with just checking that the number of properties are the same
        const logDiff = (outcome: string, details: Record<string, any> = {}) => {
            eventProcessorComparison.inc({
                outcome,
            })

            logger.warn('[IngestionConsumer] comparison diff', {
                outcome,
                details,
            })
        }

        if (!!v1Error !== !!v2Error) {
            return logDiff(v1Error ? 'v1_error_but_not_v2' : 'v2_error_but_not_v1')
        }

        if (!!v1Result !== !!v2Result) {
            return logDiff(v1Result ? 'v1_result_but_not_v2' : 'v2_result_but_not_v1')
        }

        // Iterate over each properties and compare. If the value is an object, then count the keys

        if (v1Result && v2Result) {
            const diff: Record<string, string> = {}

            Object.keys(v1Result).forEach((key) => {
                const v1Value = (v1Result as any)[key]
                const v2Value = (v2Result as any)[key]

                if (v1Value !== v2Value) {
                    diff[key] = 'diff'
                }
            })

            if (Object.keys(diff).length > 0) {
                return logDiff('diff', diff)
            }
        }

        eventProcessorComparison.inc({ outcome: 'same' })
    }

    private async runEventRunnerV1(incomingEvent: IncomingEvent): Promise<EventPipelineResult | undefined> {
        const { event, message } = incomingEvent

        const existingBreadcrumbs = this.getExistingBreadcrumbsFromHeaders(message)
        const currentBreadcrumb = this.createBreadcrumb(message)
        const allBreadcrumbs = existingBreadcrumbs.concat(currentBreadcrumb)

        try {
            const result = await this.runInstrumented('runEventPipeline', () =>
                retryIfRetriable(async () => {
                    const runner = this.getEventPipelineRunnerV1(event, allBreadcrumbs)
                    return await runner.runEventPipeline(event)
                })
            )

            // This contains the Kafka producer ACKs & message promises, to avoid blocking after every message.
            result.ackPromises?.forEach((promise) => {
                void this.scheduleWork(
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
        // some metadata to the message e.g. in the header or reference e.g. the sentry event id.
        //
        // TODO: properly abstract out this `isRetriable` error logic. This is currently relying on the
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

    private async runEventRunnerV2(incomingEvent: IncomingEvent): Promise<RawKafkaEvent | undefined> {
        const runner = this.getEventPipelineRunnerV2(incomingEvent.event)

        try {
            return await runner.run()
        } catch (error) {
            // NOTE: If we error at this point we want to handle it gracefully and continue to process the scheduled promises
            await this.handleProcessingErrorV2(error, incomingEvent.message, incomingEvent.event)
        }

        runner?.getPromises().forEach((promise) => {
            // Schedule each promise with their own error handling
            // That way if all fail with ignoreable errors we continue but if any one fails with an unexpected error we can crash out
            this.scheduleWork(promise).catch((error) => {
                return this.handleProcessingErrorV2(error, incomingEvent.message, incomingEvent.event)
            })
        })
    }

    private async handleProcessingErrorV2(error: any, message: Message, event: PipelineEvent) {
        if (error instanceof EventDroppedError) {
            // In the case of an EventDroppedError we know that the error was expected and as such we should
            // send it to the DLQ unless the doNotSendToDLQ flag is set
            // We then return as there is nothing else to do

            if (error.doNotSendToDLQ) {
                return
            }

            try {
                const sentryEventId = captureException(error)
                const headers: MessageHeader[] = message.headers ?? []
                headers.push({ ['sentry-event-id']: sentryEventId })
                headers.push({ ['event-id']: event.uuid })

                // NOTE: Whilst we are comparing we don't want to send to the DLQ
                // This is mostly a flag to remind us to remove this once we roll it out
                if (!this.comparisonV2Percentage) {
                    await this.kafkaProducer!.produce({
                        topic: this.dlqTopic,
                        value: message.value,
                        key: message.key ?? null, // avoid undefined, just to be safe
                        headers: headers,
                    })
                }
            } catch (error) {
                logger.error('🔥', `Error pushing to DLQ`, {
                    stack: error.stack,
                    error: error,
                })
                throw error
            }

            return // EventDroppedError is handled
        }

        // All other errors indicate that something went wrong and we crash out
        captureException(error, {
            tags: { team_id: event.team_id },
            extra: { originalEvent: event },
        })

        throw error
    }

    private getEventPipelineRunnerV1(
        event: PipelineEvent,
        breadcrumbs: KafkaConsumerBreadcrumb[] = []
    ): EventPipelineRunner {
        return new EventPipelineRunner(this.hub, event, this.hogTransformer, breadcrumbs)
    }

    private getEventPipelineRunnerV2(event: PipelineEvent): EventPipelineRunnerV2 {
        // Mostly a helper method for testing
        return new EventPipelineRunnerV2(this.hub, event, this.hogTransformer, true)
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

            let eventKey = `${event.token}:${event.distinct_id}`

            if (this.shouldSkipPerson(event.token, event.distinct_id)) {
                // If we are skipping person processing, then we can parallelize processing of this event for dramatic performance gains
                eventKey = new UUIDT().toString()
                event.properties = {
                    ...(event.properties ?? {}),
                    $process_person_profile: false,
                }
            }

            // We collect the events grouped by token and distinct_id so that we can process batches in parallel whilst keeping the order of events
            // for a given distinct_id
            if (!batches[eventKey]) {
                batches[eventKey] = {
                    token: event.token ?? '',
                    distinctId: event.distinct_id ?? '',
                    events: [],
                }
            }

            batches[eventKey].events.push({ message, event })
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
            (token && this.tokenDistinctIdsToDrop.includes(token)) ||
            (token && distinctId && this.tokenDistinctIdsToDrop.includes(`${token}:${distinctId}`))
        )
    }

    private shouldSkipPerson(token?: string, distinctId?: string) {
        return (
            (token && this.tokenDistinctIdsToSkipPersons.includes(token)) ||
            (token && distinctId && this.tokenDistinctIdsToSkipPersons.includes(`${token}:${distinctId}`))
        )
    }

    private shouldForceOverflow(token?: string, distinctId?: string) {
        return (
            (token && this.tokenDistinctIdsToForceOverflow.includes(token)) ||
            (token && distinctId && this.tokenDistinctIdsToForceOverflow.includes(`${token}:${distinctId}`))
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
                    headers: headers,
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
                    headers: message.headers,
                })
            )
        )
    }
}
