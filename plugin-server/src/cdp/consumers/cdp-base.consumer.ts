import { Message } from 'node-rdkafka'
import { Counter, Gauge, Histogram } from 'prom-client'

import {
    KAFKA_APP_METRICS_2,
    KAFKA_CDP_FUNCTION_CALLBACKS,
    KAFKA_EVENTS_PLUGIN_INGESTION,
    KAFKA_LOG_ENTRIES,
} from '../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../kafka/config'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { addSentryBreadcrumbsEventListeners } from '../../main/ingestion-queues/kafka-metrics'
import { runInstrumentedFunction } from '../../main/utils'
import { AppMetric2Type, Hub, PluginServerService, TeamId, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { castTimestampOrNow, UUIDT } from '../../utils/utils'
import { RustyHook } from '../../worker/rusty-hook'
import { CdpRedis, createCdpRedisPool } from '../redis'
import { FetchExecutorService } from '../services/fetch-executor.service'
import { GroupsManagerService } from '../services/groups-manager.service'
import { HogExecutorService } from '../services/hog-executor.service'
import { HogFunctionManagerService } from '../services/hog-function-manager.service'
import { HogMaskerService } from '../services/hog-masker.service'
import { HogWatcherService } from '../services/hog-watcher.service'
import {
    HogFunctionAppMetric,
    HogFunctionInvocation,
    HogFunctionInvocationResult,
    HogFunctionInvocationSerialized,
    HogFunctionInvocationSerializedCompressed,
    HogFunctionLogEntrySerialized,
    HogFunctionMessageToProduce,
    HogFunctionType,
    HogFunctionTypeType,
} from '../types'
import { fixLogDeduplication, gzipObject } from '../utils'
import { convertToCaptureEvent } from '../utils'

// Metrics that were at the top of the file
export const histogramKafkaBatchSize = new Histogram({
    name: 'cdp_function_executor_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

export const histogramKafkaBatchSizeKb = new Histogram({
    name: 'cdp_function_executor_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity],
})

export const counterFunctionInvocation = new Counter({
    name: 'cdp_function_invocation',
    help: 'A function invocation was evaluated with an outcome',
    labelNames: ['outcome'], // One of 'failed', 'succeeded', 'overflowed', 'disabled', 'filtered'
})

export const counterParseError = new Counter({
    name: 'cdp_function_parse_error',
    help: 'A function invocation was parsed with an error',
    labelNames: ['error'],
})

export const gaugeBatchUtilization = new Gauge({
    name: 'cdp_cyclotron_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['queue'],
})

export const counterJobsProcessed = new Counter({
    name: 'cdp_cyclotron_jobs_processed',
    help: 'The number of jobs we are managing to process',
    labelNames: ['queue'],
})

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

export abstract class CdpConsumerBase {
    batchConsumer?: BatchConsumer
    hogFunctionManager: HogFunctionManagerService
    fetchExecutor: FetchExecutorService
    hogExecutor: HogExecutorService
    hogWatcher: HogWatcherService
    hogMasker: HogMaskerService
    groupsManager: GroupsManagerService
    isStopping = false
    messagesToProduce: HogFunctionMessageToProduce[] = []
    redis: CdpRedis

    protected hogTypes: HogFunctionTypeType[] = []
    protected kafkaProducer?: KafkaProducerWrapper
    protected abstract name: string

    protected heartbeat = () => {}

    constructor(protected hub: Hub) {
        this.redis = createCdpRedisPool(hub)
        this.hogFunctionManager = new HogFunctionManagerService(hub)
        this.hogWatcher = new HogWatcherService(hub, this.redis)
        this.hogMasker = new HogMaskerService(this.redis)
        this.hogExecutor = new HogExecutorService(this.hub, this.hogFunctionManager)
        const rustyHook = this.hub?.rustyHook ?? new RustyHook(this.hub)
        this.fetchExecutor = new FetchExecutorService(this.hub, rustyHook)
        this.groupsManager = new GroupsManagerService(this.hub)
    }

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

    protected async produceQueuedMessages() {
        const messages = [...this.messagesToProduce]
        this.messagesToProduce = []

        await this.kafkaProducer!.queueMessages(
            messages.map((x) => ({
                topic: x.topic,
                messages: [
                    {
                        value: safeClickhouseString(JSON.stringify(x.value)),
                        key: x.key,
                    },
                ],
            }))
        ).catch((reason) => {
            status.error('⚠️', `failed to produce message: ${reason}`)
        })
    }

    protected produceAppMetric(metric: HogFunctionAppMetric) {
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
        const logs = fixLogDeduplication(
            result.logs.map((logEntry) => ({
                ...logEntry,
                team_id: result.invocation.hogFunction.team_id,
                log_source: 'hog_function',
                log_source_id: result.invocation.hogFunction.id,
                instance_id: result.invocation.id,
            }))
        )

        logs.forEach((logEntry) => {
            this.messagesToProduce.push({
                topic: KAFKA_LOG_ENTRIES,
                value: logEntry,
                key: logEntry.instance_id,
            })
        })
    }

    protected logFilteringError(item: HogFunctionType, error: string) {
        const logEntry: HogFunctionLogEntrySerialized = {
            team_id: item.team_id,
            log_source: 'hog_function',
            log_source_id: item.id,
            instance_id: new UUIDT().toString(), // random UUID, like it would be for an invocation
            timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
            level: 'error',
            message: error,
        }

        this.messagesToProduce.push({
            topic: KAFKA_LOG_ENTRIES,
            value: logEntry,
            key: logEntry.instance_id,
        })
    }

    // NOTE: These will be removed once we are only on Cyclotron
    protected async queueInvocationsToKafka(invocation: HogFunctionInvocation[]) {
        await Promise.all(
            invocation.map(async (item) => {
                await this.queueInvocationToKafka(item)
            })
        )
    }

    protected async queueInvocationToKafka(invocation: HogFunctionInvocation) {
        // NOTE: WE keep the queueParams args as kafka land still needs them
        const serializedInvocation: HogFunctionInvocationSerialized = {
            ...invocation,
            hogFunctionId: invocation.hogFunction.id,
        }

        if (invocation.queue === 'fetch') {
            // Track a metric purely to say a fetch was attempted (this may be what we bill on in the future)
            this.produceAppMetric({
                team_id: invocation.teamId,
                app_source_id: invocation.hogFunction.id,
                metric_kind: 'other',
                metric_name: 'fetch',
                count: 1,
            })
        }

        delete (serializedInvocation as any).hogFunction

        const request: HogFunctionInvocationSerializedCompressed = {
            state: await gzipObject(serializedInvocation),
        }

        // NOTE: This is very temporary as it is producing the response. the response will actually be produced by the 3rd party service
        // Later this will actually be the _request_ which we will push to the async function topic if we make one
        this.messagesToProduce.push({
            topic: KAFKA_CDP_FUNCTION_CALLBACKS,
            value: request,
            key: `${invocation.hogFunction.id}:${invocation.id}`,
        })
    }

    protected async processInvocationResults(results: HogFunctionInvocationResult[]): Promise<void> {
        return await runInstrumentedFunction({
            statsKey: `cdpConsumer.handleEachBatch.produceResults`,
            func: async () => {
                await this.hogWatcher.observeResults(results)

                await Promise.all(
                    results.map(async (result) => {
                        if (result.finished || result.error) {
                            this.produceAppMetric({
                                team_id: result.invocation.teamId,
                                app_source_id: result.invocation.hogFunction.id,
                                metric_kind: result.error ? 'failure' : 'success',
                                metric_name: result.error ? 'failed' : 'succeeded',
                                count: 1,
                            })
                        }

                        this.produceLogs(result)

                        // Clear the logs so we don't pass them on to the next invocation
                        result.logs = []

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
                    })
                )
            },
        })
    }

    protected async startKafkaConsumer(options: {
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
            this.hogFunctionManager.start(this.hogTypes),
            KafkaProducerWrapper.create(this.hub).then((producer) => {
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
        status.info('🔁', `${this.name} - stopping hog function manager and hog watcher`)
        await Promise.all([this.hogFunctionManager.stop()])

        status.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy() {
        return this.batchConsumer?.isHealthy()
    }
}
