import cyclotron from '@posthog/cyclotron'
import { captureException } from '@sentry/node'
import { Message } from 'node-rdkafka'
import { Counter, Histogram } from 'prom-client'

import {
    KAFKA_APP_METRICS_2,
    KAFKA_CDP_FUNCTION_CALLBACKS,
    KAFKA_EVENTS_JSON,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_LOG_ENTRIES,
} from '../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../kafka/config'
import { addSentryBreadcrumbsEventListeners } from '../main/ingestion-queues/kafka-metrics'
import { runInstrumentedFunction } from '../main/utils'
import { AppMetric2Type, Hub, RawClickHouseEvent, TeamId, TimestampFormat } from '../types'
import { createKafkaProducerWrapper } from '../utils/db/hub'
import { KafkaProducerWrapper } from '../utils/db/kafka-producer-wrapper'
import { captureTeamEvent } from '../utils/posthog'
import { status } from '../utils/status'
import { castTimestampOrNow } from '../utils/utils'
import { RustyHook } from '../worker/rusty-hook'
import { AsyncFunctionExecutor } from './async-function-executor'
import { GroupsManager } from './groups-manager'
import { HogExecutor } from './hog-executor'
import { HogFunctionManager } from './hog-function-manager'
import { HogMasker } from './hog-masker'
import { HogWatcher, HogWatcherState } from './hog-watcher'
import { CdpRedis, createCdpRedisPool } from './redis'
import {
    HogFunctionInvocation,
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionInvocationSerialized,
    HogFunctionMessageToProduce,
    HogFunctionType,
} from './types'
import {
    convertToCaptureEvent,
    convertToHogFunctionInvocationGlobals,
    createInvocation,
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

    protected abstract _handleKafkaBatch(messages: Message[]): Promise<void>

    protected async produceQueuedMessages() {
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

    protected async queueInvocations(invocation: HogFunctionInvocation[]) {
        await Promise.all(
            invocation.map(async (item) => {
                await this.queueInvocation(item)
            })
        )
    }

    protected async queueInvocation(invocation: HogFunctionInvocation) {
        // Depending on flags we enqueue either to kafka or to cyclotron

        // TODO: Add cylcotron check here
        // For now we just enqueue to kafka

        // For kafka style this is overkill to enqueue this way but it simplifies migrating to the new system

        // TODO: Convert to the right format for a job
        const request: HogFunctionInvocationSerialized = {
            state: await gzipObject(invocation),
        }

        // NOTE: This is very temporary as it is producing the response. the response will actually be produced by the 3rd party service
        // Later this will actually be the _request_ which we will push to the async function topic if we make one
        this.messagesToProduce.push({
            topic: KAFKA_CDP_FUNCTION_CALLBACKS,
            value: request,
            key: invocation.hogFunction.id,
        })
    }

    protected async startKafkaConsumer() {
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
                        await this._handleKafkaBatch(messages)
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

    public async start(): Promise<void> {
        // NOTE: This is only for starting shared services
        await Promise.all([
            this.hogFunctionManager.start(),
            this.hub.CYCLOTRON_DATABASE_URL
                ? cyclotron.initManager({ shards: [{ dbUrl: this.hub.CYCLOTRON_DATABASE_URL }] })
                : Promise.resolve(),
        ])

        this.kafkaProducer = await createKafkaProducerWrapper(this.hub)
        this.kafkaProducer.producer.connect()
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
        // TODO: Check either kafka consumer or cyclotron worker exists
        // and that whatever exists is healthy
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

    public async processBatch(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<HogFunctionInvocation[]> {
        if (!invocationGlobals.length) {
            return []
        }

        const invocationsToBeQueued = await this.runWithHeartbeat(() =>
            this.createHogFunctionInvocations(invocationGlobals)
        )
        await this.queueInvocations(invocationsToBeQueued)
        await this.produceQueuedMessages()

        return invocationsToBeQueued
    }

    /**
     * Finds all matching hog functions for the given globals.
     * Filters them for their disabled state as well as masking configs
     *
     */
    protected async createHogFunctionInvocations(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<HogFunctionInvocation[]> {
        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.queueMatchingFunctions`,
            func: async () => {
                const possibleInvocations: HogFunctionInvocation[] = []

                // TODO: Add a helper to hog functions to determine if they require groups or not and then only load those
                await this.groupsManager.enrichGroups(invocationGlobals)

                // Find all functions that could need running
                invocationGlobals.forEach((globals) => {
                    // TODO: Move that out of finding to somewhere else
                    const { matchingFunctions, nonMatchingFunctions } = this.hogExecutor.findMatchingFunctions(globals)

                    possibleInvocations.push(
                        ...matchingFunctions.map((hogFunction) => createInvocation(globals, hogFunction))
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

                return notMaskedInvocations
            },
        })
    }

    // This consumer always parses from kafka
    public async _handleKafkaBatch(messages: Message[]): Promise<void> {
        const invocationGlobals = await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
                func: async () => {
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
                },
            })
        )

        await this.processBatch(invocationGlobals)
    }
}

/**
 * This consumer handles actually invoking hog in a loop
 */
export class CdpFunctionCallbackConsumer extends CdpConsumerBase {
    protected name = 'CdpFunctionCallbackConsumer'
    protected topic = KAFKA_CDP_FUNCTION_CALLBACKS
    protected consumerGroupId = 'cdp-function-callback-consumer'

    public async processBatch(invocations: HogFunctionInvocation[]): Promise<void> {
        if (!invocations.length) {
            return
        }
        const invocationResults = await this.runWithHeartbeat(() => this.processInvocations(invocations))
        await this.processInvocationResults(invocationResults)
    }

    protected async processInvocations(invocations: HogFunctionInvocation[]): Promise<HogFunctionInvocationResult[]> {
        // These are either new invocations or responses
        // The key thing we need to consider is taking the response, adding it to the invocation state and then continuing
        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.executeInvocations`,
            func: async () => {
                // TODO: Handle if the invocation step is not "hog" so we should do fetch instead...

                const results = await this.runManyWithHeartbeat(invocations, (item) => this.hogExecutor.execute(item))
                await this.hogWatcher.observeResults(results)
                return results
            },
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
                            app_source_id: result.invocation.hogFunction.id,
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

                        if (!result.finished) {
                            // If it isn't finished then we need to put it back on the queue
                            await this.queueInvocation(result.invocation)
                        }
                    })
                )
            },
        })
    }

    public async _handleKafkaBatch(messages: Message[]): Promise<void> {
        const events = await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpConsumer.handleEachBatch.parseKafkaMessages`,
                func: async () => {
                    // TRICKY: In the future we won't use kafka. For now though we need to parse messages as Cyclotron style jobs
                    // or hoghooks async callbacks

                    const invocations: HogFunctionInvocation[] = []

                    // Parse the base message value
                    const entries: (HogFunctionInvocationAsyncResponse | HogFunctionInvocationSerialized)[] = messages
                        .map((message) => {
                            try {
                                return JSON.parse(message.value!.toString())
                            } catch (e) {
                                status.error('Error parsing message', e)
                            }

                            return undefined
                        })
                        .filter(Boolean)

                    // Deserialize the compressed data
                    await Promise.all(
                        entries.map(async (item) => {
                            // If it looks like a
                            try {
                                const invocation = await unGzipObject<HogFunctionInvocation>(item.state)
                                if ('asyncFunctionResponse' in item) {
                                    // This means it is a callback from hoghooks so we need to add the response to the invocation
                                    invocation.queue = 'hog'
                                    invocation.queueParameters = item.asyncFunctionResponse
                                }
                                invocations.push(invocation)
                            } catch (e) {
                                status.error('Error unzipping message', e, item.state)
                                captureException(e)
                            }
                        })
                    )

                    return invocations
                },
            })
        )

        await this.processBatch(events)
    }
}

// // TODO: Split out non-Kafka specific parts of CdpConsumerBase so that it can be used by the
// // Cyclotron worker below. Or maybe we can just wait, and rip the Kafka bits out once Cyclotron is
// // shipped (and rename it something other than consomer, probably). For now, this is an easy way to
// // use existing code and get an end-to-end demo shipped.
// export class CdpCyclotronWorker extends CdpConsumerBase {
//     protected name = 'CdpCyclotronWorker'
//     protected topic = 'UNUSED-CdpCyclotronWorker'
//     protected consumerGroupId = 'UNUSED-CdpCyclotronWorker'
//     private runningWorker: Promise<void> | undefined
//     private isUnhealthy = false

//     public async _handleEachBatch(_: Message[]): Promise<void> {
//         // Not called, we override `start` below to use Cyclotron instead.
//     }

//     private async innerStart() {
//         try {
//             const limit = 100 // TODO: Make configurable.
//             while (!this.isStopping) {
//                 const jobs = await cyclotron.dequeueJobsWithVmState('hog', limit)
//                 for (const job of jobs) {
//                     // TODO: Reassemble a HogFunctionInvocationAsyncResponse (or whatever proper type)
//                     // from the fields on the job, and then execute the next Hog step.
//                     console.log(job.id)
//                 }
//             }
//         } catch (err) {
//             this.isUnhealthy = true
//             console.error('Error in Cyclotron worker', err)
//             throw err
//         }
//     }

//     public async start() {
//         await cyclotron.initManager({ shards: [{ dbUrl: this.hub.CYCLOTRON_DATABASE_URL }] })
//         await cyclotron.initWorker({ dbUrl: this.hub.CYCLOTRON_DATABASE_URL })

//         // Consumer `start` expects an async task is started, and not that `start` itself blocks
//         // indefinitely.
//         this.runningWorker = this.innerStart()

//         return Promise.resolve()
//     }

//     public async stop() {
//         await super.stop()
//         await this.runningWorker
//     }

//     public isHealthy() {
//         return this.isUnhealthy
//     }
// }
