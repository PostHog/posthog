import { features, librdkafkaVersion, Message } from 'node-rdkafka'
import { Histogram } from 'prom-client'

import {
    KAFKA_CDP_FUNCTION_CALLBACKS,
    KAFKA_CDP_OVERFLOW,
    KAFKA_EVENTS_JSON,
    KAFKA_LOG_ENTRIES,
} from '../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars, createRdProducerConfigFromEnvVars } from '../kafka/config'
import { createKafkaProducer } from '../kafka/producer'
import { addSentryBreadcrumbsEventListeners } from '../main/ingestion-queues/kafka-metrics'
import { runInstrumentedFunction } from '../main/utils'
import { GroupTypeToColumnIndex, Hub, RawClickHouseEvent, TeamId, TimestampFormat } from '../types'
import { KafkaProducerWrapper } from '../utils/db/kafka-producer-wrapper'
import { status } from '../utils/status'
import { castTimestampOrNow } from '../utils/utils'
import { AppMetrics } from '../worker/ingestion/app-metrics'
import { RustyHook } from '../worker/rusty-hook'
import { AsyncFunctionExecutor } from './async-function-executor'
import { HogExecutor } from './hog-executor'
import { HogFunctionManager } from './hog-function-manager'
import { HogWatcher } from './hog-watcher'
import {
    CdpOverflowMessage,
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionMessageToQueue,
} from './types'
import { convertToHogFunctionInvocationGlobals, convertToParsedClickhouseEvent } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
const BUCKETS_KB_WRITTEN = [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity]

const histogramKafkaBatchSize = new Histogram({
    name: 'cdp_function_executor_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

const histogramKafkaBatchSizeKb = new Histogram({
    name: 'cdp_function_executor_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: BUCKETS_KB_WRITTEN,
})

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

abstract class CdpConsumerBase {
    batchConsumer?: BatchConsumer
    hogFunctionManager: HogFunctionManager
    asyncFunctionExecutor: AsyncFunctionExecutor
    hogExecutor: HogExecutor
    hogWatcher: HogWatcher
    appMetrics?: AppMetrics
    isStopping = false

    protected kafkaProducer?: KafkaProducerWrapper
    protected abstract name: string
    protected abstract topic: string
    protected abstract consumerGroupId: string

    constructor(protected hub: Hub) {
        this.hogWatcher = new HogWatcher(hub)
        this.hogFunctionManager = new HogFunctionManager(hub.postgres, hub)
        this.hogExecutor = new HogExecutor(hub, this.hogFunctionManager)
        const rustyHook = this.hub?.rustyHook ?? new RustyHook(this.hub)
        this.asyncFunctionExecutor = new AsyncFunctionExecutor(this.hub, rustyHook)
    }

    public abstract handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void>

    protected async processInvocationResults(results: HogFunctionInvocationResult[]): Promise<void> {
        // TODO: Follow up - process metrics from the invocationResults
        await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.produceResults`,
            func: async () => {
                const messagesToProduce: HogFunctionMessageToQueue[] = []

                await Promise.all(
                    results.map(async (result) => {
                        // Tricky: We want to pull all the logs out as we don't want them to be passed around to any subsequent functions
                        const logs = result.logs
                        result.logs = []

                        logs.forEach((x) => {
                            const sanitized = {
                                ...x,
                                timestamp: castTimestampOrNow(x.timestamp, TimestampFormat.ClickHouse),
                            }
                            // Convert timestamps to ISO strings
                            messagesToProduce.push({
                                topic: KAFKA_LOG_ENTRIES,
                                value: sanitized,
                                key: sanitized.instance_id,
                            })
                        })

                        if (result.asyncFunctionRequest) {
                            const res = await this.asyncFunctionExecutor.execute(result)

                            // NOTE: This is very temporary as it is producing the response. the response will actually be produced by the 3rd party service
                            // Later this will actually be the _request_ which we will push to the async function topic if we make one
                            if (res) {
                                messagesToProduce.push({
                                    topic: KAFKA_CDP_FUNCTION_CALLBACKS,
                                    value: res,
                                    key: res.id,
                                })
                            }
                        }
                    })
                )

                await Promise.all(
                    messagesToProduce.map((x) =>
                        this.kafkaProducer!.produce({
                            topic: x.topic,
                            value: Buffer.from(JSON.stringify(x.value)),
                            key: x.key,
                            waitForAck: true,
                        })
                    )
                )
            },
        })
    }

    protected async executeAsyncResponses(
        asyncResponses: HogFunctionInvocationAsyncResponse[]
    ): Promise<HogFunctionInvocationResult[]> {
        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.executeAsyncResponses`,
            func: async () => {
                await this.hogWatcher.observeAsyncFunctionResponses(asyncResponses)
                // Filter for blocked functions
                asyncResponses = asyncResponses.filter((e) => {
                    // if (this.hogWatcher.isHogFunctionOverflowed(e.hogFunctionId)) {
                    //     // TODO: Move to overflow
                    //     return false
                    // }
                    // if (this.hogWatcher.isHogFunctionDisabled(e.hogFunctionId)) {
                    //     // TODO: We probably want to log some metric that it was blocked
                    //     return false
                    // }
                    return true
                })

                const results = await Promise.all(asyncResponses.map((e) => this.hogExecutor.executeAsyncResponse(e)))
                await this.hogWatcher.observeResults(results)
                return results
            },
        })
    }

    protected async executeMatchingFunctions(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<HogFunctionInvocationResult[]> {
        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.executeMatchingFunctions`,
            func: async () => {
                const results = (
                    await Promise.all(
                        invocationGlobals.map((e) => {
                            // TODO: Load all functions related to this event
                            // Check if they are overflowed - if so move to the overflow queue
                            // BUT only one event and a list of hog function IDs, as we don't want to duplicate the overflow situation
                            // Check if they are disabled - if so we log and drop it entirely

                            return this.hogExecutor.executeMatchingFunctions(e)
                        })
                    )
                ).flat()
                await this.hogWatcher.observeResults(results)
                return results
            },
        })
    }

    public async start(): Promise<void> {
        status.info('🔁', `${this.name} - starting`, {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        // NOTE: This is the only place where we need to use the shared server config
        const globalConnectionConfig = createRdConnectionConfigFromEnvVars(this.hub)
        const globalProducerConfig = createRdProducerConfigFromEnvVars(this.hub)

        await Promise.all([this.hogFunctionManager.start(), this.hogWatcher.start()])

        this.kafkaProducer = new KafkaProducerWrapper(
            await createKafkaProducer(globalConnectionConfig, globalProducerConfig)
        )

        this.appMetrics =
            this.hub?.appMetrics ??
            new AppMetrics(
                this.kafkaProducer,
                this.hub.APP_METRICS_FLUSH_FREQUENCY_MS,
                this.hub.APP_METRICS_FLUSH_MAX_QUEUE_SIZE
            )
        this.kafkaProducer.producer.connect()

        this.batchConsumer = await startBatchConsumer({
            connectionConfig: createRdConnectionConfigFromEnvVars(this.hub),
            groupId: this.consumerGroupId,
            topic: this.topic,
            autoCommit: true,
            sessionTimeout: this.hub.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
            maxPollIntervalMs: this.hub.KAFKA_CONSUMPTION_MAX_POLL_INTERVAL_MS,
            // the largest size of a message that can be fetched by the consumer.
            // the largest size our MSK cluster allows is 20MB
            // we only use 9 or 10MB but there's no reason to limit this 🤷️
            consumerMaxBytes: this.hub.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.hub.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            // our messages are very big, so we don't want to buffer too many
            // queuedMinMessages: this.hub.KAFKA_QUEUE_SIZE,
            consumerMaxWaitMs: this.hub.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: this.hub.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            fetchBatchSize: this.hub.INGESTION_BATCH_SIZE,
            batchingTimeoutMs: this.hub.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicCreationTimeoutMs: this.hub.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            eachBatch: async (messages, { heartbeat }) => {
                status.info('🔁', `${this.name} - handling batch`, {
                    size: messages.length,
                })

                histogramKafkaBatchSize.observe(messages.length)
                histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                return await runInstrumentedFunction({
                    statsKey: `cdpConsumer.handleEachBatch`,
                    sendTimeoutGuardToSentry: false,
                    func: async () => {
                        return await this.handleEachBatch(messages, heartbeat)
                    },
                })
            },
            callEachBatchWhenEmpty: false,
        })

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', `${this.name} batch consumer disconnected, cleaning up`, { err })
            await this.stop()
        })
    }

    public async stop(): Promise<void> {
        status.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        status.info('🔁', `${this.name} - stopping batch consumer`)
        await this.batchConsumer?.stop()
        status.info('🔁', `${this.name} - stopping kafka producer`)
        await this.kafkaProducer?.disconnect()
        status.info('🔁', `${this.name} - stopping hog function manager`)
        await this.hogFunctionManager.stop()

        status.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy() {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.batchConsumer?.isHealthy()
    }
}

/**
 * This consumer handles incoming events from the main clickhouse topic
 */

export class CdpProcessedEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpProcessedEventsConsumer'
    protected topic = KAFKA_EVENTS_JSON
    protected consumerGroupId = 'cdp-processed-events-consumer'

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        const invocationGlobals = await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
            func: async () => await this.parseMessages(messages),
        })
        heartbeat()

        if (!invocationGlobals.length) {
            return
        }

        const invocationResults = await this.executeMatchingFunctions(invocationGlobals)
        heartbeat()

        await this.processInvocationResults(invocationResults)
    }

    private async parseMessages(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []
        await Promise.all(
            messages.map(async (message) => {
                try {
                    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent

                    if (!this.hogFunctionManager.teamHasHogFunctions(clickHouseEvent.team_id)) {
                        // No need to continue if the team doesn't have any functions
                        return
                    }

                    let groupTypes: GroupTypeToColumnIndex | undefined = undefined

                    if (
                        await this.hub.organizationManager.hasAvailableFeature(
                            clickHouseEvent.team_id,
                            'group_analytics'
                        )
                    ) {
                        // If the organization has group analytics enabled then we enrich the event with group data
                        groupTypes = await this.hub.groupTypeManager.fetchGroupTypes(clickHouseEvent.team_id)
                    }

                    const team = await this.hub.teamManager.fetchTeam(clickHouseEvent.team_id)
                    if (!team) {
                        return
                    }
                    events.push(
                        convertToHogFunctionInvocationGlobals(
                            convertToParsedClickhouseEvent(clickHouseEvent),
                            team,
                            this.hub.SITE_URL ?? 'http://localhost:8000',
                            groupTypes
                        )
                    )
                } catch (e) {
                    status.error('Error parsing message', e)
                }
            })
        )

        return events
    }
}

/**
 * This consumer handles callbacks from async functions.
 */
export class CdpFunctionCallbackConsumer extends CdpConsumerBase {
    protected name = 'CdpFunctionCallbackConsumer'
    protected topic = KAFKA_CDP_FUNCTION_CALLBACKS
    protected consumerGroupId = 'cdp-function-callback-consumer'

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        const events = await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
            func: () => Promise.resolve(this.parseMessages(messages)),
        })
        heartbeat()

        if (!events.length) {
            return
        }

        const invocationResults = await this.executeAsyncResponses(events)
        heartbeat()

        await this.processInvocationResults(invocationResults)
    }

    private parseMessages(messages: Message[]): HogFunctionInvocationAsyncResponse[] {
        const events: HogFunctionInvocationAsyncResponse[] = []
        messages.map((message) => {
            try {
                const event = JSON.parse(message.value!.toString()) as unknown

                events.push(event as HogFunctionInvocationAsyncResponse)
            } catch (e) {
                status.error('Error parsing message', e)
            }
        })

        return events
    }
}

/**
 * This consumer handles overflow for both incoming events as well as callbacks.
 * In the future we might want multiple consumers but for now this is fine.
 */

export class CdpOverflowConsumer extends CdpConsumerBase {
    protected name = 'CdpOverflowConsumer'
    protected topic = KAFKA_CDP_OVERFLOW
    protected consumerGroupId = 'cdp-overflow-consumer'

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        // This consumer can receive both events and callbacks so needs to check the message being parsed
        const [invocationGlobals, callbacks] = await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
            func: () => Promise.resolve(this.parseMessages(messages)),
        })

        heartbeat()

        const invocationResults = (
            await Promise.all([this.executeAsyncResponses(callbacks), this.executeMatchingFunctions(invocationGlobals)])
        ).flat()

        heartbeat()

        await this.processInvocationResults(invocationResults)
    }

    private parseMessages(messages: Message[]): [HogFunctionInvocationGlobals[], HogFunctionInvocationAsyncResponse[]] {
        const invocationGlobals: HogFunctionInvocationGlobals[] = []
        const callbacks: HogFunctionInvocationAsyncResponse[] = []
        messages.map((message) => {
            try {
                const parsed = JSON.parse(message.value!.toString()) as CdpOverflowMessage

                if (parsed.source === 'event_invocations') {
                    invocationGlobals.push(parsed.payload)
                } else if (parsed.source === 'hog_function_callback') {
                    callbacks.push(parsed.payload)
                }
            } catch (e) {
                // TODO: We probably want to crash here right as this means something went really wrong and needs investigating?
                status.error('Error parsing message', e)
            }
        })

        return [invocationGlobals, callbacks]
    }
}
