import { captureException } from '@sentry/node'
import { Message, MessageHeader } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import { HogTransformerService } from '../cdp/hog-transformations/hog-transformer.service'
import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../kafka/config'
import { KafkaProducerWrapper } from '../kafka/producer'
import { Hub, PipelineEvent, PluginServerService } from '../types'
import { runInstrumentedFunction } from '../utils/instrument'
import { eventDroppedCounter } from '../utils/metrics'
import { status } from '../utils/status'
import { EventDroppedError, EventPipelineRunnerV2 } from './event-pipeline-runner/event-pipeline-runner'
import { normalizeEvent } from './event-pipeline-runner/utils/event-utils'
import { PersonsDB } from './event-pipeline-runner/utils/persons-db'
import { sanitizeString } from './event-pipeline-runner/utils/utils'
import { EventIngestionBatchContext, IncomingEventsByTokenDistinctId, TokenDistinctId } from './types'
import { MemoryRateLimiter } from './utils/overflow-detector'

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

const ingestionOverflowingMessagesTotal = new Counter({
    name: 'ingestion_overflowing_messages_total',
    help: 'Count of messages rerouted to the overflow topic.',
})

export const setUsageInNonPersonEventsCounter = new Counter({
    name: 'set_usage_in_non_person_events',
    help: 'Count of events where $set usage was found in non-person events',
})

export const ingestionPartitionKeyOverflowed = new Counter({
    name: 'ingestion_partition_key_overflowed',
    help: 'Indicates that a given key has overflowed capacity and been redirected to a different topic. Value incremented once a minute.',
    labelNames: ['partition_key'],
})

export class IngestionConsumer {
    protected name = 'ingestion-consumer'
    protected groupId: string
    protected topic: string
    protected dlqTopic: string
    protected overflowTopic?: string

    batchConsumer?: BatchConsumer
    isStopping = false
    protected heartbeat = () => {}
    protected promises: Set<Promise<any>> = new Set()
    protected kafkaProducer?: KafkaProducerWrapper
    protected kafkaOverflowProducer?: KafkaProducerWrapper
    public hogTransformer: HogTransformerService
    public personsDB: PersonsDB

    private overflowRateLimiter: MemoryRateLimiter
    private ingestionWarningLimiter: MemoryRateLimiter
    private tokensToDrop: string[] = []
    private tokenDistinctIdsToDrop: string[] = []

    constructor(private hub: Hub) {
        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = hub.INGESTION_CONSUMER_GROUP_ID
        this.topic = hub.INGESTION_CONSUMER_CONSUME_TOPIC
        this.overflowTopic = hub.INGESTION_CONSUMER_OVERFLOW_TOPIC
        this.dlqTopic = hub.INGESTION_CONSUMER_DLQ_TOPIC
        this.tokensToDrop = hub.DROP_EVENTS_BY_TOKEN.split(',').filter((x) => !!x)
        this.tokenDistinctIdsToDrop = hub.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)

        this.name = `ingestion-consumer-${this.topic}`
        this.overflowRateLimiter = new MemoryRateLimiter(
            this.hub.EVENT_OVERFLOW_BUCKET_CAPACITY,
            this.hub.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE
        )

        this.ingestionWarningLimiter = new MemoryRateLimiter(1, 1.0 / 3600)
        this.hogTransformer = new HogTransformerService(hub)
        this.personsDB = new PersonsDB(hub.postgres, hub.kafkaProducer)
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
            this.hogTransformer.start(),
        ])
    }

    public async stop(): Promise<void> {
        status.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        status.info('🔁', `${this.name} - stopping batch consumer`)
        await this.batchConsumer?.stop()
        status.info('🔁', `${this.name} - stopping kafka producer`)
        await this.kafkaProducer?.disconnect()
        status.info('🔁', `${this.name} - stopping kafka overflow producer`)
        await this.kafkaOverflowProducer?.disconnect()
        status.info('🔁', `${this.name} - stopping hog transformer`)
        await this.hogTransformer.stop()
        status.info('👍', `${this.name} - stopped!`)
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
        const context = await this.runInstrumented('parseKafkaMessages', () => this.parseKafkaBatch(messages))
        await this.runInstrumented('processBatch', () => this.processBatch(context))

        status.debug('🔁', `Waiting for promises`, { promises: this.promises.size })
        await this.runInstrumented('awaitScheduledWork', () => Promise.all(this.promises))
        status.debug('🔁', `Processed batch`)
    }

    private getEventPipelineRunner(event: PipelineEvent, context: EventIngestionBatchContext): EventPipelineRunnerV2 {
        // Mostly a helper method for testing
        return new EventPipelineRunnerV2(this.hub, event, this.personsDB, this.hogTransformer, context)
    }

    private async processBatch(context: EventIngestionBatchContext) {
        await Promise.all(
            Object.values(context.eventsByTokenDistinctId).map(async (incomingEvents) => {
                await this.runInstrumented('processEvents', async () => {
                    for (const { message, event } of incomingEvents) {
                        try {
                            status.debug('🔁', `Processing event`, {
                                event,
                            })
                            const runner = this.getEventPipelineRunner(event, context)
                            try {
                                await runner.run()
                            } catch (error) {
                                await this.handleProcessingError(error, message, event)
                            }

                            // TRICKY: We want to later catch anything that goes wrong with flushing
                            // the promises so we can send the event to the DLQ
                            this.scheduleWork(Promise.all(runner.getPromises())).catch((error) => {
                                return this.handleProcessingError(error, message, event)
                            })
                        } catch (error) {
                            await this.handleProcessingError(error, message, event)
                        }
                    }
                })
            })
        )
    }

    private async parseKafkaBatch(messages: Message[]): Promise<EventIngestionBatchContext> {
        const context: EventIngestionBatchContext = {
            eventsByTokenDistinctId: {},
            teamsByToken: {},
        }

        const eventsByTokenDistinctId: IncomingEventsByTokenDistinctId = {}
        const tokens = new Set<string>()

        for (const message of messages) {
            let distinctId: string | undefined
            let token: string | undefined

            // Parse the headers so we can early exit if found and should be dropped
            message.headers?.forEach((header) => {
                if (header.key === 'distinct_id') {
                    distinctId = header.value.toString()
                }
                if (header.key === 'token') {
                    token = sanitizeString(header.value.toString())
                }
            })

            if (this.shouldDropEvent(token, distinctId)) {
                this.logDroppedEvent(token, distinctId)
                continue
            }

            // Parse the message payload into the event object
            const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
            const event: PipelineEvent = normalizeEvent({ ...JSON.parse(dataStr), ...rawEvent })

            token = sanitizeString(event.token!)

            // In case the headers were not set we check the parsed message now
            if (this.shouldDropEvent(token, event.distinct_id)) {
                this.logDroppedEvent(token, event.distinct_id)
                continue
            }

            const eventKey = `${token}:${event.distinct_id}` as TokenDistinctId
            tokens.add(token)
            // We collect the events grouped by token and distinct_id so that we can process batches in parallel whilst keeping the order of events
            // for a given distinct_id
            if (!eventsByTokenDistinctId[eventKey]) {
                eventsByTokenDistinctId[eventKey] = []
            }

            eventsByTokenDistinctId[eventKey].push({ message, event })
        }

        // Move all events to overflow if they should be overflowed
        if (this.overflowEnabled()) {
            for (const [teamDistinctId, incomingEvents] of Object.entries(eventsByTokenDistinctId)) {
                // If overflow is enabled and the rate limiter kicks in send all the events to overflow
                const timestamp = incomingEvents[0].message.timestamp
                const isBelowRateLimit = this.overflowRateLimiter.consume(
                    teamDistinctId,
                    incomingEvents.length,
                    timestamp
                )

                if (!isBelowRateLimit) {
                    void this.scheduleWork(this.emitToOverflow(incomingEvents.map((x) => x.message)))

                    delete context.eventsByTokenDistinctId[teamDistinctId as TokenDistinctId]
                    continue
                }
            }
        }

        // Add all teams to our context
        context.teamsByToken = (await this.hub.teamManager.getTeams(Array.from(tokens))).byToken
        return context
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
            fetchBatchSize: this.hub.KAFKA_CONSUMPTION_BATCH_SIZE,
            batchingTimeoutMs: this.hub.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicCreationTimeoutMs: this.hub.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            topicMetadataRefreshInterval: this.hub.KAFKA_TOPIC_METADATA_REFRESH_INTERVAL_MS,
            eachBatch: async (messages, { heartbeat }) => {
                status.info('🔁', `${this.name} - handling batch`, {
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

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            if (!this.isStopping) {
                return
            }
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', `${this.name} batch consumer disconnected, cleaning up`, { err })
            await this.stop()
        })
    }

    private async handleProcessingError(error: any, message: Message, event: PipelineEvent) {
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

                await this.kafkaProducer!.produce({
                    topic: this.dlqTopic,
                    value: message.value,
                    key: message.key ?? null, // avoid undefined, just to be safe
                    headers: headers,
                })
            } catch (error) {
                status.error('🔥', `Error pushing to DLQ`, {
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

    private logDroppedEvent(token?: string, distinctId?: string) {
        status.debug('🔁', `Dropped event`, {
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
        return !!this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC && this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC !== this.topic
    }

    private async emitToOverflow(kafkaMessages: Message[]) {
        const overflowTopic = this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC
        if (!overflowTopic) {
            throw new Error('No overflow topic configured')
        }

        ingestionOverflowingMessagesTotal.inc(kafkaMessages.length)
        // TODO: Do we want this as a flag?
        const useRandomPartitioning = true

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
}
