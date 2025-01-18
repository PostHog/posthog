import * as Sentry from '@sentry/node'
import { Message, MessageHeader } from 'node-rdkafka'
import { Histogram } from 'prom-client'

import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../kafka/config'
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
import { Hub, PipelineEvent, PluginServerService } from '../types'
import { createKafkaProducerWrapper } from '../utils/db/hub'
import { KafkaProducerWrapper } from '../utils/db/kafka-producer-wrapper'
import { normalizeEvent } from '../utils/event'
import { retryIfRetriable } from '../utils/retries'
import { status } from '../utils/status'
import { ConfiguredLimiter, LoggingLimiter } from '../utils/token-bucket'
import { EventPipelineRunner } from '../worker/ingestion/event-pipeline/runner'

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

type GroupedIncomingEvents = {
    [key: string]: { message: Message; event: PipelineEvent }[]
}

const PERSON_EVENTS = new Set(['$set', '$identify', '$create_alias', '$merge_dangerously', '$groupidentify'])
const KNOWN_SET_EVENTS = new Set([
    '$feature_interaction',
    '$feature_enrollment_update',
    'survey dismissed',
    'survey sent',
])

abstract class IngestionConsumer {
    batchConsumer?: BatchConsumer
    isStopping = false
    protected kafkaProducer?: KafkaProducerWrapper
    protected abstract name: string
    protected heartbeat = () => {}
    protected promises: Set<Promise<any>> = new Set()

    protected scheduleWork<T>(promise: Promise<T>): Promise<T> {
        this.promises.add(promise)
        void promise.finally(() => this.promises.delete(promise))
        return promise
    }

    constructor(protected hub: Hub) {}

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
            batchConsumer: this.batchConsumer,
        }
    }

    protected async runWithHeartbeat<T>(func: () => Promise<T> | T): Promise<T> {
        // Helper function to ensure that looping over lots of hog functions doesn't block up the thread, killing the consumer
        const res = await func()
        this.heartbeat()
        await new Promise((resolve) => process.nextTick(resolve))

        return res
    }

    protected async runManyWithHeartbeat<T, R>(items: T[], func: (item: T) => Promise<R> | R): Promise<R[]> {
        // Helper function to ensure that looping over lots of hog functions doesn't block up the event loop, leading to healthcheck failures
        const results = []

        for (const item of items) {
            results.push(await this.runWithHeartbeat(() => func(item)))
        }
        return results
    }

    // protected async produceQueuedMessages() {
    //     const messages = [...this.messagesToProduce]
    //     this.messagesToProduce = []
    //     await Promise.all(
    //         messages.map((x) =>
    //             this.kafkaProducer!.produce({
    //                 topic: x.topic,
    //                 value: Buffer.from(safeClickhouseString(JSON.stringify(x.value))),
    //                 key: x.key,
    //                 waitForAck: true,
    //             }).catch((reason) => {
    //                 status.error('⚠️', `failed to produce message: ${reason}`)
    //             })
    //         )
    //     )
    // }

    protected async startKafkaConsumer(options: {
        topic: string
        groupId: string
        handleBatch: (messages: Message[]) => Promise<void>
    }): Promise<void> {
        this.batchConsumer = await startBatchConsumer({
            ...options,
            connectionConfig: createRdConnectionConfigFromEnvVars(this.hub),
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

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

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

    public async start(): Promise<void> {
        // NOTE: This is only for starting shared services
        await Promise.all([
            createKafkaProducerWrapper(this.hub).then((producer) => {
                this.kafkaProducer = producer
                this.kafkaProducer.producer.connect()
            }),
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

        status.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy() {
        return this.batchConsumer?.isHealthy()
    }
}

/**
 * This consumer handles incoming events from the main kafka ingestion topic
 */
export class EventsIngestionConsumer extends IngestionConsumer {
    protected name = 'EventsIngestionConsumer'
    protected groupId: string
    protected topic: string
    protected dlqTopic: string
    protected overflowTopic?: string

    private tokensToDrop: string[] = []
    private tokenDistinctIdsToDrop: string[] = []

    constructor(hub: Hub) {
        super(hub)

        // The group and topic are configurable allowing for multiple ingestion consumers to be run in parallel
        this.groupId = hub.INGESTION_CONSUMER_GROUP_ID
        this.topic = hub.INGESTION_CONSUMER_CONSUME_TOPIC
        this.overflowTopic = hub.INGESTION_CONSUMER_OVERFLOW_TOPIC
        this.dlqTopic = hub.INGESTION_CONSUMER_DLQ_TOPIC
        this.tokensToDrop = hub.DROP_EVENTS_BY_TOKEN.split(',')
        this.tokenDistinctIdsToDrop = hub.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',')
    }

    public async processBatch(groupedIncomingEvents: GroupedIncomingEvents): Promise<void> {
        await this.runManyWithHeartbeat(Object.values(groupedIncomingEvents), async (eventsForDistinctId) => {
            // Process every message sequentially, stash promises to await on later
            for (const { message, event } of eventsForDistinctId) {
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
                    const result = await retryIfRetriable(async () => {
                        const runner = new EventPipelineRunner(this.hub, event)
                        return await runner.runEventPipeline(event)
                    })

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
        })

        await Promise.all(this.promises)
    }

    private async handleProcessingError(error: any, message: Message, event: PipelineEvent) {
        status.error('🔥', `Error processing message`, {
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
            const sentryEventId = Sentry.captureException(error)
            const headers: MessageHeader[] = message.headers ?? []
            headers.push({ ['sentry-event-id']: sentryEventId })
            headers.push({ ['event-id']: event.uuid })
            try {
                await this.kafkaProducer!.produce({
                    topic: this.dlqTopic,
                    value: message.value,
                    key: message.key ?? null, // avoid undefined, just to be safe
                    headers: headers,
                    waitForAck: true,
                })
            } catch (error) {
                // If we can't send to the DLQ and it's not retriable, just continue. We'll commit the
                // offset and move on.
                if (error?.isRetriable === false) {
                    status.error('🔥', `Error pushing to DLQ`, {
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
            (distinctId && this.tokenDistinctIdsToDrop.includes(`${token}:${distinctId}`))
        )
    }

    private overflowEnabled() {
        return !!this.hub.INGESTION_OVERFLOW_ENABLED
    }

    private async emitToOverflow(kafkaMessages: Message[]) {
        const overflowTopic = this.hub.INGESTION_CONSUMER_OVERFLOW_TOPIC
        if (!overflowTopic) {
            throw new Error('No overflow topic configured')
        }

        ingestionOverflowingMessagesTotal.inc(kafkaMessages.length)

        const overflowMode = this.hub.INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY
            ? IngestionOverflowMode.Reroute
            : IngestionOverflowMode.RerouteRandomly

        const useRandomPartitioning = overflowMode === IngestionOverflowMode.RerouteRandomly

        await Promise.all(
            kafkaMessages.map((message) =>
                this.kafkaProducer!.produce({
                    topic: this.overflowTopic!,
                    value: message.value,
                    // ``message.key`` should not be undefined here, but in the
                    // (extremely) unlikely event that it is, set it to ``null``
                    // instead as that behavior is safer.
                    key: useRandomPartitioning ? null : message.key ?? null,
                    headers: message.headers,
                    waitForAck: true,
                })
            )
        )
    }

    // This consumer always parses from kafka
    public _parseKafkaBatch(messages: Message[]): Promise<GroupedIncomingEvents> {
        return runInstrumentedFunction({
            statsKey: `ingestionConsumer.handleEachBatch.parseKafkaMessages`,
            func: () => {
                // 1. Parse the messages filtering out the ones that should be dropped

                const batches: GroupedIncomingEvents = {}

                for (const message of messages) {
                    let distinctId: string | undefined
                    let token: string | undefined

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

                    const { data: dataStr, ...rawEvent } = JSON.parse(message.value!.toString())
                    const combinedEvent: PipelineEvent = { ...JSON.parse(dataStr), ...rawEvent }
                    const event: PipelineEvent = normalizeEvent({
                        ...combinedEvent,
                    })

                    // In case the headers were not set we check the parsed message now
                    if (this.shouldDropEvent(combinedEvent.token, combinedEvent.distinct_id)) {
                        this.logDroppedEvent(combinedEvent.token, combinedEvent.distinct_id)
                        continue
                    }

                    const eventKey = `${event.token}:${event.distinct_id}`

                    if (this.overflowEnabled() && !ConfiguredLimiter.consume(eventKey, 1, message.timestamp)) {
                        // Local overflow detection triggering, reroute to overflow topic too
                        ingestionPartitionKeyOverflowed.labels(`${event.team_id ?? event.token}`).inc()
                        if (LoggingLimiter.consume(eventKey, 1)) {
                            status.warn('🪣', `Local overflow detection triggered on key ${eventKey}`)
                        }

                        void this.scheduleWork(this.emitToOverflow([message]))
                        continue
                    }

                    // TODO: Add back in overflow detection logic

                    // We collect the events grouped by token and distinct_id so that we can process batches in parallel whilst keeping the order of events
                    // for a given distinct_id
                    if (!batches[eventKey]) {
                        batches[eventKey] = []
                    }

                    batches[eventKey].push({ message, event })
                }

                // 2. Overflow the ones that are supposed to be overflowed

                return Promise.resolve(batches)
            },
        })
    }

    public async start(): Promise<void> {
        await super.start()
        await this.startKafkaConsumer({
            topic: this.topic,
            groupId: this.groupId,
            handleBatch: async (messages) => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                await this.processBatch(invocationGlobals)
                for (const message of messages) {
                    if (message.timestamp) {
                        latestOffsetTimestampGauge
                            .labels({ partition: message.partition, topic: message.topic, groupId: this.groupId })
                            .set(message.timestamp)
                    }
                }
            },
        })
    }
}
