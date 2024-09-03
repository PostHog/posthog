import cyclotron from '@posthog/cyclotron'
import { captureException } from '@sentry/node'
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
import { captureTeamEvent } from '../utils/posthog'
import { status } from '../utils/status'
import { castTimestampOrNow } from '../utils/utils'
import { RustyHook } from '../worker/rusty-hook'
import { AsyncFunctionExecutor } from './async-function-executor'
import { ExceptionsManager } from './exceptions-manager'
import { GroupsManager } from './groups-manager'
import { HogExecutor } from './hog-executor'
import { HogFunctionManager } from './hog-function-manager'
import { HogMasker } from './hog-masker'
import { HogWatcher, HogWatcherState } from './hog-watcher'
import { CdpRedis, createCdpRedisPool } from './redis'
import {
    CdpOverflowMessage,
    HogFunctionAsyncFunctionResponse,
    HogFunctionInvocation,
    HogFunctionInvocationAsyncRequest,
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionMessageToProduce,
    HogFunctionOverflowedGlobals,
    HogFunctionType,
} from './types'
import {
    convertToCaptureEvent,
    convertToHogFunctionInvocationGlobals,
    gzipObject,
    prepareLogEntriesForClickhouse,
    unGzipObject,
} from './utils'

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
    hogMasker: HogMasker
    groupsManager: GroupsManager
    exceptionsManager: ExceptionsManager
    isStopping = false
    messagesToProduce: HogFunctionMessageToProduce[] = []
    redis: CdpRedis

    protected kafkaProducer?: KafkaProducerWrapper
    protected abstract name: string
    protected abstract topic: string
    protected abstract consumerGroupId: string

    protected heartbeat = () => {}

    constructor(protected hub: Hub) {
        this.redis = createCdpRedisPool(hub)
        this.hogFunctionManager = new HogFunctionManager(hub.postgres, hub)
        this.hogWatcher = new HogWatcher(hub, this.redis, (id, state) => {
            void this.captureInternalPostHogEvent(id, 'hog function state changed', { state })
        })
        this.hogMasker = new HogMasker(this.redis)
        this.hogExecutor = new HogExecutor(this.hogFunctionManager)
        const rustyHook = this.hub?.rustyHook ?? new RustyHook(this.hub)
        this.asyncFunctionExecutor = new AsyncFunctionExecutor(this.hub, rustyHook)
        this.groupsManager = new GroupsManager(this.hub)
        this.exceptionsManager = new ExceptionsManager(this.hub)
    }

    private async captureInternalPostHogEvent(
        hogFunctionId: HogFunctionType['id'],
        event: string,
        properties: any = {}
    ) {
        const hogFunction = this.hogFunctionManager.getHogFunction(hogFunctionId)
        if (!hogFunction) {
            return
        }
        const team = await this.hub.teamManager.fetchTeam(hogFunction.team_id)

        if (!team) {
            return
        }

        captureTeamEvent(team, event, {
            ...properties,
            hog_function_id: hogFunctionId,
            hog_function_url: `${this.hub.SITE_URL}/project/${team.id}/pipeline/destinations/hog-${hogFunctionId}`,
        })
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
                }).catch((reason) => {
                    status.error('⚠️', `failed to produce message: ${reason}`)
                })
            )
        )
    }

    protected produceAppMetric(
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

    protected produceLogs(result: HogFunctionInvocationResult) {
        const logs = prepareLogEntriesForClickhouse(result)

        logs.forEach((logEntry) => {
            this.messagesToProduce.push({
                topic: KAFKA_LOG_ENTRIES,
                value: logEntry,
                key: logEntry.instance_id,
            })
        })
    }

    protected async processInvocationResults(results: HogFunctionInvocationResult[]): Promise<void> {
        await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.produceResults`,
            func: async () => {
                await Promise.all(
                    results.map(async (result) => {
                        // Tricky: We want to pull all the logs out as we don't want them to be passed around to any subsequent functions

                        this.produceAppMetric({
                            team_id: result.invocation.teamId,
                            app_source_id: result.invocation.hogFunctionId,
                            metric_kind: result.error ? 'failure' : 'success',
                            metric_name: result.error ? 'failed' : 'succeeded',
                            count: 1,
                        })

                        this.produceLogs(result)

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
                            const request: HogFunctionInvocationAsyncRequest = {
                                state: await gzipObject(result.invocation),
                                teamId: result.invocation.teamId,
                                hogFunctionId: result.invocation.hogFunctionId,
                                asyncFunctionRequest: result.asyncFunctionRequest,
                            }
                            const res = await this.runWithHeartbeat(() => this.asyncFunctionExecutor.execute(request))

                            // NOTE: This is very temporary as it is producing the response. the response will actually be produced by the 3rd party service
                            // Later this will actually be the _request_ which we will push to the async function topic if we make one
                            if (res) {
                                this.messagesToProduce.push({
                                    topic: KAFKA_CDP_FUNCTION_CALLBACKS,
                                    value: res,
                                    key: res.hogFunctionId,
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
                asyncResponses.forEach((x) => {
                    counterAsyncFunctionResponse.inc({
                        outcome: x.asyncFunctionResponse.error ? 'failed' : 'succeeded',
                    })
                })

                const invocationsWithResponses: [HogFunctionInvocation, HogFunctionAsyncFunctionResponse][] = []

                // Deserialize the compressed data
                await Promise.all(
                    asyncResponses.map(async (item) => {
                        try {
                            const invocation = await unGzipObject<HogFunctionInvocation>(item.state)
                            invocationsWithResponses.push([invocation, item.asyncFunctionResponse])
                        } catch (e) {
                            status.error('Error unzipping message', e, item.state)
                            captureException(e, {
                                extra: { hogFunctionId: item.hogFunctionId, teamId: item.teamId },
                            })
                        }
                    })
                )

                const results = await this.runManyWithHeartbeat(invocationsWithResponses, (item) =>
                    this.hogExecutor.executeAsyncResponse(...item)
                )

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
                const possibleInvocations: { globals: HogFunctionInvocationGlobals; hogFunction: HogFunctionType }[] =
                    []

                // TODO: Add a helper to hog functions to determine if they require groups or not and then only load those
                await this.groupsManager.enrichGroups(invocationGlobals)

                // TODO: Add a helper to hog functions to determine if they were created from the exceptions template and only load those
                await this.exceptionsManager.enrichExceptions(invocationGlobals)

                // Find all functions that could need running
                invocationGlobals.forEach((globals) => {
                    const { matchingFunctions, nonMatchingFunctions } = this.hogExecutor.findMatchingFunctions(globals)

                    possibleInvocations.push(
                        ...matchingFunctions.map((hogFunction) => ({
                            globals,
                            hogFunction,
                        }))
                    )

                    nonMatchingFunctions.forEach((item) =>
                        this.produceAppMetric({
                            team_id: item.team_id,
                            app_source_id: item.id,
                            metric_kind: 'other',
                            metric_name: 'filtered',
                            count: 1,
                        })
                    )
                })

                const states = await this.hogWatcher.getStates(possibleInvocations.map((x) => x.hogFunction.id))

                const notDisabledInvocations = possibleInvocations.filter((item) => {
                    const state = states[item.hogFunction.id].state
                    if (state >= HogWatcherState.disabledForPeriod) {
                        this.produceAppMetric({
                            team_id: item.globals.project.id,
                            app_source_id: item.hogFunction.id,
                            metric_kind: 'failure',
                            metric_name:
                                state === HogWatcherState.disabledForPeriod
                                    ? 'disabled_temporarily'
                                    : 'disabled_permanently',
                            count: 1,
                        })
                        return false
                    }

                    return true
                })

                // Now we can filter by masking configs
                const { masked, notMasked: notMaskedInvocations } = await this.hogMasker.filterByMasking(
                    notDisabledInvocations
                )

                masked.forEach((item) => {
                    this.produceAppMetric({
                        team_id: item.globals.project.id,
                        app_source_id: item.hogFunction.id,
                        metric_kind: 'other',
                        metric_name: 'masked',
                        count: 1,
                    })
                })

                const overflowGlobalsAndFunctions: Record<string, HogFunctionOverflowedGlobals> = {}

                const notOverflowedInvocations = notMaskedInvocations.filter((item) => {
                    const state = states[item.hogFunction.id].state

                    if (state === HogWatcherState.degraded) {
                        const key = `${item.globals.project.id}-${item.globals.event.uuid}`
                        overflowGlobalsAndFunctions[key] = overflowGlobalsAndFunctions[key] || {
                            globals: item.globals,
                            hogFunctionIds: [],
                        }

                        overflowGlobalsAndFunctions[key].hogFunctionIds.push(item.hogFunction.id)
                        counterFunctionInvocation.inc({ outcome: 'overflowed' }, 1)
                        return false
                    }

                    return true
                })

                Object.values(overflowGlobalsAndFunctions).forEach((item) => {
                    this.messagesToProduce.push({
                        topic: KAFKA_CDP_FUNCTION_OVERFLOW,
                        value: {
                            source: 'event_invocations',
                            payload: item,
                        },
                        key: item.globals.event.uuid,
                    })
                })

                const results = (
                    await this.runManyWithHeartbeat(notOverflowedInvocations, (item) =>
                        this.hogExecutor.executeFunction(item.globals, item.hogFunction)
                    )
                ).filter((x) => !!x) as HogFunctionInvocationResult[]

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

        await Promise.all([
            this.hogFunctionManager.start(),
            this.hub.CYCLOTRON_DATABASE_URL
                ? cyclotron.initManager({ shards: [{ dbUrl: this.hub.CYCLOTRON_DATABASE_URL }] })
                : Promise.resolve(),
        ])

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
        await Promise.all([this.hogFunctionManager.stop()])

        status.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy() {
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
                const event = JSON.parse(message.value!.toString())
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
        const overflowedGlobals = await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
                func: () => Promise.resolve(this.parseMessages(messages)),
            })
        )

        const invocationResults = await this.executeOverflowedFunctions(overflowedGlobals)

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

                // TODO: Add a helper to hog functions to determine if they were created from the exceptions template and only load those
                await this.exceptionsManager.enrichExceptions(invocationGlobals.map((x) => x.globals))

                const invocations = invocationGlobals
                    .map((item) =>
                        item.hogFunctionIds.map((hogFunctionId) => ({
                            globals: item.globals,
                            hogFunctionId,
                        }))
                    )
                    .flat()

                const states = await this.hogWatcher.getStates(invocationGlobals.map((x) => x.hogFunctionIds).flat())

                const results = (
                    await this.runManyWithHeartbeat(invocations, (item) => {
                        const state = states[item.hogFunctionId].state
                        if (state >= HogWatcherState.disabledForPeriod) {
                            this.produceAppMetric({
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

                await this.hogWatcher.observeResults(results)
                return results
            },
        })
    }

    private parseMessages(messages: Message[]): HogFunctionOverflowedGlobals[] {
        const invocationGlobals: HogFunctionOverflowedGlobals[] = []
        messages.map((message) => {
            try {
                const parsed = JSON.parse(message.value!.toString()) as CdpOverflowMessage

                if (parsed.source === 'event_invocations') {
                    invocationGlobals.push(parsed.payload)
                }
            } catch (e) {
                // TODO: We probably want to crash here right as this means something went really wrong and needs investigating?
                status.error('Error parsing message', e)
            }
        })

        return invocationGlobals
    }
}

// TODO: Split out non-Kafka specific parts of CdpConsumerBase so that it can be used by the
// Cyclotron worker below. Or maybe we can just wait, and rip the Kafka bits out once Cyclotron is
// shipped (and rename it something other than consomer, probably). For now, this is an easy way to
// use existing code and get an end-to-end demo shipped.
export class CdpCyclotronWorker extends CdpConsumerBase {
    protected name = 'CdpCyclotronWorker'
    protected topic = 'UNUSED-CdpCyclotronWorker'
    protected consumerGroupId = 'UNUSED-CdpCyclotronWorker'
    private runningWorker: Promise<void> | undefined
    private isUnhealthy = false

    public async _handleEachBatch(_: Message[]): Promise<void> {
        // Not called, we override `start` below to use Cyclotron instead.
    }

    private async innerStart() {
        try {
            const limit = 100 // TODO: Make configurable.
            while (!this.isStopping) {
                const jobs = await cyclotron.dequeueJobsWithVmState('hog', limit)
                for (const job of jobs) {
                    // TODO: Reassemble a HogFunctionInvocationAsyncResponse (or whatever proper type)
                    // from the fields on the job, and then execute the next Hog step.
                    console.log(job.id)
                }
            }
        } catch (err) {
            this.isUnhealthy = true
            console.error('Error in Cyclotron worker', err)
            throw err
        }
    }

    public async start() {
        await cyclotron.initManager({ shards: [{ dbUrl: this.hub.CYCLOTRON_DATABASE_URL }] })
        await cyclotron.initWorker({ dbUrl: this.hub.CYCLOTRON_DATABASE_URL })

        // Consumer `start` expects an async task is started, and not that `start` itself blocks
        // indefinitely.
        this.runningWorker = this.innerStart()

        return Promise.resolve()
    }

    public async stop() {
        await super.stop()
        await this.runningWorker
    }

    public isHealthy() {
        return this.isUnhealthy
    }
}
