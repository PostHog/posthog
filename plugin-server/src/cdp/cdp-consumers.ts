import { features, librdkafkaVersion, Message } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import {
    KAFKA_APP_METRICS_2,
    KAFKA_CDP_FUNCTION_CALLBACKS,
    KAFKA_CDP_FUNCTION_OVERFLOW,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_LOG_ENTRIES,
} from '../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars, createRdProducerConfigFromEnvVars } from '../kafka/config'
import { createKafkaProducer } from '../kafka/producer'
import { addSentryBreadcrumbsEventListeners } from '../main/ingestion-queues/kafka-metrics'
import { runInstrumentedFunction } from '../main/utils'
import { AppMetric2Type, Hub, RawClickHouseEvent, TeamId, TimestampFormat } from '../types'
import { KafkaProducerWrapper } from '../utils/db/kafka-producer-wrapper'
import { status } from '../utils/status'
import { castTimestampOrNow } from '../utils/utils'
import { RustyHook } from '../worker/rusty-hook'
import { AsyncFunctionExecutor } from './async-function-executor'
import { GroupsManager } from './groups-manager'
import { HogExecutor } from './hog-executor'
import { HogFunctionManager } from './hog-function-manager'
import { HogWatcher } from './hog-watcher/hog-watcher'
import { HogWatcherState } from './hog-watcher/types'
import {
    CdpOverflowMessage,
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionMessageToProduce,
    HogFunctionOverflowedGlobals,
    HogFunctionType,
} from './types'
import { convertToCaptureEvent, convertToHogFunctionInvocationGlobals } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

const histogramKafkaBatchSize = new Histogram({
    name: 'cdp_function_executor_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

const histogramKafkaBatchSizeKb = new Histogram({
    name: 'cdp_function_executor_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity],
})

const counterFunctionInvocation = new Counter({
    name: 'cdp_function_invocation',
    help: 'A function invocation was evaluated with an outcome',
    labelNames: ['outcome'], // One of 'failed', 'succeeded', 'overflowed', 'disabled', 'filtered'
})

const counterAsyncFunctionResponse = new Counter({
    name: 'cdp_async_function_response',
    help: 'An async function response was received with an outcome',
    labelNames: ['outcome'], // One of 'failed', 'succeeded', 'overflowed', 'disabled', 'filtered'
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
    groupsManager: GroupsManager
    isStopping = false
    messagesToProduce: HogFunctionMessageToProduce[] = []

    protected kafkaProducer?: KafkaProducerWrapper
    protected abstract name: string
    protected abstract topic: string
    protected abstract consumerGroupId: string

    protected heartbeat = () => {}

    constructor(protected hub: Hub) {
        this.hogWatcher = new HogWatcher(hub)
        this.hogFunctionManager = new HogFunctionManager(hub.postgres, hub)
        this.hogExecutor = new HogExecutor(this.hogFunctionManager)
        const rustyHook = this.hub?.rustyHook ?? new RustyHook(this.hub)
        this.asyncFunctionExecutor = new AsyncFunctionExecutor(this.hub, rustyHook)
        this.groupsManager = new GroupsManager(this.hub)
    }

    protected async runWithHeartbeat<T>(func: () => Promise<T> | T): Promise<T> {
        // Helper function to ensure that looping over lots of hog functions doesn't block up the thread, killing the consumer
        const res = await func()
        this.heartbeat()
        await new Promise((resolve) => process.nextTick(resolve))

        return res
    }

    protected async runManyWithHeartbeat<T, R>(items: T[], func: (item: T) => Promise<R> | R): Promise<R[]> {
        // Helper function to ensure that looping over lots of hog functions doesn't block up the thread, killing the consumer
        const results = []

        for (const item of items) {
            results.push(await this.runWithHeartbeat(() => func(item)))
        }
        return results
    }

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        status.info('🔁', `${this.name} - handling batch`, {
            size: messages.length,
        })

        this.heartbeat = heartbeat

        histogramKafkaBatchSize.observe(messages.length)
        histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch`,
            sendTimeoutGuardToSentry: false,
            func: async () => {
                await this._handleEachBatch(messages)
                await this.produceQueuedMessages()
            },
        })
    }

    protected abstract _handleEachBatch(messages: Message[]): Promise<void>

    private async produceQueuedMessages() {
        const messages = [...this.messagesToProduce]
        this.messagesToProduce = []
        await Promise.all(
            messages.map((x) =>
                this.kafkaProducer!.produce({
                    topic: x.topic,
                    value: Buffer.from(JSON.stringify(x.value)),
                    key: x.key,
                    waitForAck: true,
                })
            )
        )
    }

    protected logAppMetrics(
        metric: Pick<AppMetric2Type, 'team_id' | 'app_source_id' | 'metric_kind' | 'metric_name' | 'count'>
    ) {
        const appMetric: AppMetric2Type = {
            app_source: 'hog_function',
            ...metric,
            timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
        }

        this.messagesToProduce.push({
            topic: KAFKA_APP_METRICS_2,
            value: appMetric,
            key: appMetric.app_source_id,
        })

        counterFunctionInvocation.inc({ outcome: appMetric.metric_name }, appMetric.count)
    }

    protected async processInvocationResults(results: HogFunctionInvocationResult[]): Promise<void> {
        await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.produceResults`,
            func: async () => {
                await Promise.all(
                    results.map(async (result) => {
                        // Tricky: We want to pull all the logs out as we don't want them to be passed around to any subsequent functions
                        const logs = result.logs
                        result.logs = []

                        this.logAppMetrics({
                            team_id: result.teamId,
                            app_source_id: result.hogFunctionId,
                            metric_kind: result.error ? 'failure' : 'success',
                            metric_name: result.error ? 'failed' : 'succeeded',
                            count: 1,
                        })

                        logs.forEach((x) => {
                            const sanitized = {
                                ...x,
                                timestamp: castTimestampOrNow(x.timestamp, TimestampFormat.ClickHouse),
                            }
                            // Convert timestamps to ISO strings
                            this.messagesToProduce.push({
                                topic: KAFKA_LOG_ENTRIES,
                                value: sanitized,
                                key: sanitized.instance_id,
                            })
                        })

                        // PostHog capture events
                        const capturedEvents = result.capturedPostHogEvents
                        delete result.capturedPostHogEvents

                        for (const event of capturedEvents ?? []) {
                            const team = await this.hub.teamManager.fetchTeam(event.team_id)
                            if (!team) {
                                continue
                            }
                            this.messagesToProduce.push({
                                topic: KAFKA_EVENTS_PLUGIN_INGESTION,
                                value: convertToCaptureEvent(event, team),
                                key: `${team!.api_token}:${event.distinct_id}`,
                            })
                        }

                        if (result.asyncFunctionRequest) {
                            const res = await this.runWithHeartbeat(() => this.asyncFunctionExecutor.execute(result))

                            // NOTE: This is very temporary as it is producing the response. the response will actually be produced by the 3rd party service
                            // Later this will actually be the _request_ which we will push to the async function topic if we make one
                            if (res) {
                                this.messagesToProduce.push({
                                    topic: KAFKA_CDP_FUNCTION_CALLBACKS,
                                    value: res,
                                    key: res.id,
                                })
                            }
                        }
                    })
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
                this.hogWatcher.currentObservations.observeAsyncFunctionResponses(asyncResponses)
                asyncResponses.forEach((x) => {
                    counterAsyncFunctionResponse.inc({
                        outcome: x.asyncFunctionResponse.error ? 'failed' : 'succeeded',
                    })
                })

                // Filter for blocked functions
                const asyncResponsesToRun: HogFunctionInvocationAsyncResponse[] = []

                for (const item of asyncResponses) {
                    const functionState = this.hogWatcher.getFunctionState(item.hogFunctionId)

                    if (functionState === HogWatcherState.overflowed) {
                        // TODO: _Maybe_ report to AppMetrics 2 when it is ready
                        this.messagesToProduce.push({
                            topic: KAFKA_CDP_FUNCTION_OVERFLOW,
                            value: {
                                source: 'hog_function_callback',
                                payload: item,
                            },
                            key: item.id,
                        })
                        // We don't report overflowed metric to appmetrics as it is sort of a meta-metric
                        counterFunctionInvocation.inc({ outcome: 'overflowed' })
                    } else if (functionState > HogWatcherState.disabledForPeriod) {
                        this.logAppMetrics({
                            team_id: item.teamId,
                            app_source_id: item.hogFunctionId,
                            metric_kind: 'failure',
                            metric_name:
                                functionState === HogWatcherState.disabledForPeriod
                                    ? 'disabled_temporarily'
                                    : 'disabled_permanently',
                            count: 1,
                        })
                        continue
                    } else {
                        asyncResponsesToRun.push(item)
                    }
                }

                const results = await this.runManyWithHeartbeat(asyncResponsesToRun, (item) =>
                    this.hogExecutor.executeAsyncResponse(item)
                )

                this.hogWatcher.currentObservations.observeResults(results)
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
                const invocations: { globals: HogFunctionInvocationGlobals; hogFunction: HogFunctionType }[] = []

                // TODO: Add a helper to hog functions to determine if they require groups or not and then only load those
                await this.groupsManager.enrichGroups(invocationGlobals)

                invocationGlobals.forEach((globals) => {
                    const { matchingFunctions, nonMatchingFunctions } = this.hogExecutor.findMatchingFunctions(globals)

                    nonMatchingFunctions.forEach((item) =>
                        this.logAppMetrics({
                            team_id: item.team_id,
                            app_source_id: item.id,
                            metric_kind: 'other',
                            metric_name: 'filtered',
                            count: 1,
                        })
                    )

                    // Filter for overflowed and disabled functions
                    const hogFunctionsByState = matchingFunctions.reduce((acc, item) => {
                        const state = this.hogWatcher.getFunctionState(item.id)
                        return {
                            ...acc,
                            [state]: [...(acc[state] ?? []), item],
                        }
                        return acc
                    }, {} as Record<HogWatcherState, HogFunctionType[] | undefined>)

                    if (hogFunctionsByState[HogWatcherState.overflowed]?.length) {
                        const overflowed = hogFunctionsByState[HogWatcherState.overflowed]!
                        // Group all overflowed functions into one event
                        counterFunctionInvocation.inc({ outcome: 'overflowed' }, overflowed.length)

                        this.messagesToProduce.push({
                            topic: KAFKA_CDP_FUNCTION_OVERFLOW,
                            value: {
                                source: 'event_invocations',
                                payload: {
                                    hogFunctionIds: overflowed.map((x) => x.id),
                                    globals,
                                },
                            },
                            key: globals.event.uuid,
                        })
                    }

                    hogFunctionsByState[HogWatcherState.disabledForPeriod]?.forEach((item) => {
                        this.logAppMetrics({
                            team_id: item.team_id,
                            app_source_id: item.id,
                            metric_kind: 'failure',
                            metric_name: 'disabled_temporarily',
                            count: 1,
                        })
                    })

                    hogFunctionsByState[HogWatcherState.disabledIndefinitely]?.forEach((item) => {
                        this.logAppMetrics({
                            team_id: item.team_id,
                            app_source_id: item.id,
                            metric_kind: 'failure',
                            metric_name: 'disabled_permanently',
                            count: 1,
                        })
                    })

                    hogFunctionsByState[HogWatcherState.healthy]?.forEach((item) => {
                        invocations.push({
                            globals,
                            hogFunction: item,
                        })
                    })
                })

                const results = (
                    await this.runManyWithHeartbeat(invocations, (item) =>
                        this.hogExecutor.executeFunction(item.globals, item.hogFunction)
                    )
                ).filter((x) => !!x) as HogFunctionInvocationResult[]

                this.hogWatcher.currentObservations.observeResults(results)
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
            topicMetadataRefreshInterval: this.hub.KAFKA_TOPIC_METADATA_REFRESH_INTERVAL_MS,
            eachBatch: async (messages, { heartbeat }) => {
                return await this.handleEachBatch(messages, heartbeat)
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
        status.info('🔁', `${this.name} - stopping hog function manager and hog watcher`)
        await Promise.all([this.hogFunctionManager.stop(), this.hogWatcher.stop()])

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

    public async _handleEachBatch(messages: Message[]): Promise<void> {
        const invocationGlobals = await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
                func: async () => await this.parseMessages(messages),
            })
        )

        if (!invocationGlobals.length) {
            return
        }

        const invocationResults = await this.runWithHeartbeat(() => this.executeMatchingFunctions(invocationGlobals))

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

                    const team = await this.hub.teamManager.fetchTeam(clickHouseEvent.team_id)
                    if (!team) {
                        return
                    }
                    events.push(
                        convertToHogFunctionInvocationGlobals(
                            clickHouseEvent,
                            team,
                            this.hub.SITE_URL ?? 'http://localhost:8000'
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

    public async _handleEachBatch(messages: Message[]): Promise<void> {
        const events = await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
                func: () => Promise.resolve(this.parseMessages(messages)),
            })
        )

        if (!events.length) {
            return
        }

        const invocationResults = await this.runWithHeartbeat(() => this.executeAsyncResponses(events))

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
    protected topic = KAFKA_CDP_FUNCTION_OVERFLOW
    protected consumerGroupId = 'cdp-overflow-consumer'

    public async _handleEachBatch(messages: Message[]): Promise<void> {
        // This consumer can receive both events and callbacks so needs to check the message being parsed
        const [overflowedGlobals, callbacks] = await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
                func: () => Promise.resolve(this.parseMessages(messages)),
            })
        )

        const invocationResults = (
            await this.runWithHeartbeat(() =>
                Promise.all([this.executeAsyncResponses(callbacks), this.executeOverflowedFunctions(overflowedGlobals)])
            )
        ).flat()

        await this.processInvocationResults(invocationResults)
    }

    protected async executeOverflowedFunctions(
        invocationGlobals: HogFunctionOverflowedGlobals[]
    ): Promise<HogFunctionInvocationResult[]> {
        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.executeOverflowedFunctions`,
            func: async () => {
                // TODO: Add a helper to hog functions to determine if they require groups or not and then only load those
                await this.groupsManager.enrichGroups(invocationGlobals.map((x) => x.globals))

                const invocations = invocationGlobals
                    .map((item) =>
                        item.hogFunctionIds.map((hogFunctionId) => ({
                            globals: item.globals,
                            hogFunctionId,
                        }))
                    )
                    .flat()

                const results = (
                    await this.runManyWithHeartbeat(invocations, (item) => {
                        const state = this.hogWatcher.getFunctionState(item.hogFunctionId)
                        if (state >= HogWatcherState.disabledForPeriod) {
                            this.logAppMetrics({
                                team_id: item.globals.project.id,
                                app_source_id: item.hogFunctionId,
                                metric_kind: 'failure',
                                metric_name:
                                    state === HogWatcherState.disabledForPeriod
                                        ? 'disabled_temporarily'
                                        : 'disabled_permanently',
                                count: 1,
                            })
                            return
                        }
                        return this.hogExecutor.executeFunction(item.globals, item.hogFunctionId)
                    })
                ).filter((x) => !!x) as HogFunctionInvocationResult[]

                this.hogWatcher.currentObservations.observeResults(results)
                return results
            },
        })
    }

    private parseMessages(messages: Message[]): [HogFunctionOverflowedGlobals[], HogFunctionInvocationAsyncResponse[]] {
        const invocationGlobals: HogFunctionOverflowedGlobals[] = []
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
